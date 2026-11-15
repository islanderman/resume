"""One-pass HTML scan shared by every check; edge=True also undoes Cloudflare injections."""

__unittest = True  # keeps helper frames out of unittest failure reports

import unicodedata
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

from . import cloudflare as cf
from .common import read_text

VOID = frozenset(
    "area base basefont br col embed frame hr img input keygen link meta param source track wbr".split()
)
BLOCK = frozenset(
    "address article aside blockquote body br dd details dialog div dl dt fieldset figcaption figure "
    "footer form h1 h2 h3 h4 h5 h6 header hgroup hr li main nav ol p pre section summary table tbody "
    "td tfoot th thead tr ul".split()
)
HIDDEN = frozenset("head title script style template noscript desc".split())
# Elements whose end tag may not be omitted; the others (p, li, td, ...) close implicitly.
STRICT = frozenset(
    "a article aside b blockquote button code details div dl em figcaption figure footer form h1 h2 "
    "h3 h4 h5 h6 header i label main nav ol pre section select small span strong summary svg table "
    "textarea u ul".split()
)
URL_ATTRS = {
    "a": ("href",),
    "area": ("href",),
    "link": ("href",),
    "base": ("href",),
    "script": ("src",),
    "img": ("src", "srcset"),
    "source": ("src", "srcset"),
    "iframe": ("src",),
    "embed": ("src",),
    "object": ("data",),
    "audio": ("src",),
    "video": ("src", "poster"),
    "track": ("src",),
    "input": ("src",),
    "form": ("action",),
    "use": ("href", "xlink:href"),
    "image": ("href", "xlink:href"),
}
EXECUTABLE_TYPES = frozenset(
    {"", "text/javascript", "application/javascript", "module", "text/ecmascript"}
)


@dataclass
class Ref:
    tag: str
    attr: str
    value: str
    attrs: dict


@dataclass
class Script:
    attrs: dict
    text: str
    kind: object  # None, "cloudflare-edge" or "cloudflare-web-analytics"

    @property
    def type(self):
        return self.attrs.get("type", "").strip().lower()

    @property
    def executable(self):
        return self.type in EXECUTABLE_TYPES

    @property
    def json_ld(self):
        return self.type == "application/ld+json"


@dataclass
class Style:
    attrs: dict
    text: str


class PageFacts(HTMLParser):
    def __init__(self, html, edge=False):
        super().__init__(convert_charrefs=True)
        self.edge = edge
        self.doctype = None
        self.lang = None
        self.title = ""
        self.metas, self.links, self.refs = [], [], []
        self.anchors, self.images = [], []
        self.scripts, self.styles, self.style_attrs = [], [], []
        self.ids = set()
        self.class_tokens = set()
        self.svg_inline = 0
        self.artifacts = []
        self.balance_errors = []
        self._stack = []
        self._chunks = []
        self._hidden = Counter()
        self._current = None
        self._mail = None
        self.feed(html)
        self.close()
        for tag in self._stack:
            if tag in STRICT:
                self.balance_errors.append(f"<{tag}> is never closed")

    # --- balance bookkeeping -------------------------------------------------
    def _open(self, tag):
        if tag not in VOID:
            self._stack.append(tag)

    def _close(self, tag):
        if tag in VOID:
            return
        if tag not in self._stack:
            if tag in STRICT:
                self.balance_errors.append(f"stray </{tag}>")
            return
        while True:
            top = self._stack.pop()
            if top == tag:
                return
            if top in STRICT:
                self.balance_errors.append(f"<{top}> is closed implicitly by </{tag}>")

    # --- HTMLParser hooks ----------------------------------------------------
    def handle_decl(self, decl):
        if decl.lower().startswith("doctype"):
            self.doctype = decl.strip()

    def handle_starttag(self, tag, attrs_list):
        attrs = {}
        for name, value in attrs_list:
            attrs.setdefault(name, "" if value is None else value)
        self._open(tag)
        if self._mail:
            if tag == self._mail[0]:
                self._mail[1] += 1
            return
        self._note_artifacts(tag, attrs)
        if self.edge:
            self._undo_email(tag, attrs)
        if tag == "body" or (tag in BLOCK and self._hidden["head"]):
            self._hidden["head"] = 0
        getattr(self, "_on_" + tag, lambda a: None)(attrs)
        for attr in URL_ATTRS.get(tag, ()):
            if attr in attrs:
                self.refs.append(Ref(tag, attr, attrs[attr], attrs))
        self.class_tokens.update(attrs.get("class", "").split())
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "a" and "name" in attrs:
            self.ids.add(attrs["name"])
        if "style" in attrs:
            self.style_attrs.append((tag, attrs["style"]))
        if tag in BLOCK:
            self._chunks.append(" ")
        if tag in HIDDEN:
            self._hidden[tag] += 1

    def handle_endtag(self, tag):
        self._close(tag)
        if self._mail:
            if tag == self._mail[0]:
                self._mail[1] -= 1
                if self._mail[1] == 0:
                    self._mail = None
            return
        if self._hidden[tag] > 0:
            self._hidden[tag] -= 1
        if self._current and self._current[0] == tag:
            self._finish_current()
        if tag in BLOCK:
            self._chunks.append(" ")

    def handle_data(self, data):
        if self._mail:
            return
        if self._current:
            self._current[2].append(data)
        elif self._hidden["title"]:
            if "svg" not in self._stack:
                self.title += data
        elif not any(self._hidden[t] for t in HIDDEN):
            self._chunks.append(data)

    # --- per-tag hooks -------------------------------------------------------
    def _on_html(self, attrs):
        self.lang = attrs.get("lang")

    def _on_meta(self, attrs):
        self.metas.append(attrs)

    def _on_link(self, attrs):
        self.links.append(attrs)

    def _on_a(self, attrs):
        self.anchors.append(attrs)

    _on_area = _on_a

    def _on_img(self, attrs):
        self.images.append(attrs)

    def _on_svg(self, attrs):
        self.svg_inline += 1

    def _on_script(self, attrs):
        self._current = ("script", attrs, [])

    def _on_style(self, attrs):
        self._current = ("style", attrs, [])

    # --- edge handling -------------------------------------------------------
    def _note_artifacts(self, tag, attrs):
        if "data-cfemail" in attrs or "__cf_email__" in attrs.get("class", ""):
            self.artifacts.append(f"<{tag}> carries Cloudflare email obfuscation")
        for name in ("href", "src"):
            if cf.EDGE_PATH in attrs.get(name, ""):
                self.artifacts.append(f"<{tag} {name}={attrs[name]!r}> points at /cdn-cgi/")
        if tag == "script" and (
            "data-cf-settings" in attrs or cf.ROCKET_TYPE.match(attrs.get("type", ""))
        ):
            self.artifacts.append("<script> rewritten by Rocket Loader")

    def _undo_email(self, tag, attrs):
        if "data-cfemail" in attrs:
            address = cf.decode_cfemail(attrs["data-cfemail"])
            self._chunks.append(address)
            if tag == "a" and attrs.get("href", "").startswith("/cdn-cgi/l/email-protection"):
                attrs["href"] = "mailto:" + address
            if tag not in VOID:
                self._mail = [tag, 1]
        elif tag == "a":
            mailto = cf.decode_email_href(attrs.get("href", ""))
            if mailto:
                attrs["href"] = mailto

    def _finish_current(self):
        kind, attrs, parts = self._current
        self._current = None
        text = "".join(parts)
        if kind == "style":
            self.styles.append(Style(attrs, text))
            return
        script_kind = cf.classify_script(attrs, text)
        if script_kind == "cloudflare-edge" and cf.EDGE_PATH not in attrs.get("src", ""):
            self.artifacts.append("inline <script> injected by Cloudflare (__CF$cv$params)")
        if self.edge:
            attrs = cf.clean_script_attrs(attrs)
        self.scripts.append(Script(attrs, text, script_kind))

    # --- derived views -------------------------------------------------------
    def visible_text(self):
        text = unicodedata.normalize("NFC", "".join(self._chunks))
        return " ".join(text.split())

    def all_artifacts(self):
        found = list(self.artifacts)
        if "[email protected]" in self.visible_text():
            found.append("visible text contains the '[email protected]' placeholder")
        return found

    def meta(self, key, value):
        """Content of the first <meta> whose `key` attribute (name/property) equals `value`."""
        for attrs in self.metas:
            if attrs.get(key, "").lower() == value:
                return attrs.get("content")
        return None

    def link_href(self, rel):
        for attrs in self.links:
            if rel in attrs.get("rel", "").lower().split():
                return attrs.get("href")
        return None


def parse(html, edge=False):
    return PageFacts(html, edge=edge)


@lru_cache(maxsize=None)
def _cached(path, edge, mtime_ns, size):
    return PageFacts(read_text(path, "page under test"), edge=edge)


def page(path, edge=False):
    """Parse an HTML file once per (path, edge, mtime); missing files raise InputProblem."""
    path = Path(path)
    if not path.is_file():
        read_text(path, "page under test")  # raises the standard missing-file AssertionError
    stat = path.stat()
    return _cached(str(path), edge, stat.st_mtime_ns, stat.st_size)
