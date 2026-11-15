"""External hosts a page reaches: markup, CSS and script literals, checked against the allow-list."""

__unittest = True  # keeps helper frames out of unittest failure reports

import re

from . import cssscan, htmlfacts, refs
from .common import FIXTURES, INDEX, public_files, read_json, read_text, rel

HOST_PATTERN = re.compile(r"^(\*\.)?[a-z0-9-]+(\.[a-z0-9-]+)+$")
SCRIPT_URL = re.compile(
    r"https?://(?P<a>[A-Za-z0-9.-]+\.[A-Za-z]{2,})|['\"`]//(?P<b>[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
)
FONT_CDNS = (
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "use.typekit.net",
    "p.typekit.net",
    "fonts.bunny.net",
    "use.fontawesome.com",
    "kit.fontawesome.com",
    "cdnjs.cloudflare.com",
)


def load_allowed():
    data = read_json(FIXTURES / "allowed_hosts.json", "allow-list of external hosts")
    hosts = data.get("hosts") if isinstance(data, dict) else data
    if not isinstance(hosts, list):
        raise AssertionError("allowed_hosts.json must hold a list under 'hosts'")
    return [str(h).lower() for h in hosts]


def host_allowed(host, allowed):
    host = host.lower()
    for pattern in allowed:
        if pattern.startswith("*."):
            if host.endswith(pattern[1:]) and host != pattern[2:]:
                return True
        elif host == pattern:
            return True
    return False


def _script_texts(facts, base):
    """(where, text) for inline executable scripts and the same-origin scripts the page loads."""
    out = [
        ("inline <script>", s.text)
        for s in facts.scripts
        if s.executable and not s.attrs.get("src")
    ]
    for script in facts.scripts:
        src = script.attrs.get("src", "")
        if src and refs.kind(src) == "local":
            path, _ = refs.resolve(src, base)
            if path is not None:
                out.append((rel(path), read_text(path, "script referenced by the page")))
    return out


def page_external_urls(index=INDEX):
    """List of (where, host, url) for every external reference the page and its CSS/JS make."""
    facts = htmlfacts.page(index)
    found = []
    for item in refs.html_refs(facts):
        if item.role in ("resource", "origin-hint") and refs.kind(item.value) == "external":
            found.append((item.where, refs.host_of(item.value), item.value))
    for css in public_files(".css"):
        for item in refs.css_refs(read_text(css, "stylesheet"), rel(css)):
            if refs.kind(item.value) == "external":
                found.append((item.where, refs.host_of(item.value), item.value))
    for where, text in _script_texts(facts, index.parent):
        for match in SCRIPT_URL.finditer(text):
            host = (match.group("a") or match.group("b")).lower()
            found.append((where, host, match.group(0).lstrip("'\"`")))
    return found


def page_font_urls(index=INDEX):
    """Every URL inside @font-face blocks plus <link rel=preload as=font> targets."""
    facts = htmlfacts.page(index)
    urls = []
    for css in public_files(".css"):
        for body in cssscan.font_face_bodies(read_text(css, "stylesheet")):
            urls += [(rel(css), u) for u in cssscan.urls(body)]
    for style in facts.styles:
        for body in cssscan.font_face_bodies(style.text):
            urls += [("<style>", u) for u in cssscan.urls(body)]
    for attrs in facts.links:
        if attrs.get("as", "").lower() == "font":
            urls.append(("<link rel=preload as=font>", attrs.get("href", "")))
    return urls
