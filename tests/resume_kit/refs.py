"""Reference extraction and resolution against public/ with case-exact matching."""

__unittest = True  # keeps helper frames out of unittest failure reports

import os
import re
from collections import namedtuple
from urllib.parse import unquote, urlsplit

from . import cssscan
from .common import PUBLIC

Found = namedtuple("Found", "role where value attrs")

# Cloudflare Pages consumes these at deploy time and never serves them.
PAGES_CONTROL_FILES = frozenset({"_headers", "_redirects", "_routes.json", "_worker.js"})
RESOURCE_RELS = frozenset(
    "stylesheet icon shortcut apple-touch-icon apple-touch-icon-precomposed mask-icon preload "
    "prefetch modulepreload manifest prerender image_src".split()
)
HINT_RELS = frozenset({"preconnect", "dns-prefetch"})


def kind(value):
    """empty, fragment, special (data:/javascript:/...), other-scheme (mailto:/tel:), external, local."""
    text = value.strip()
    low = text.lower()
    if not text:
        return "empty"
    if text.startswith("#"):
        return "fragment"
    if low.startswith("//"):
        return "external"
    match = re.match(r"^([a-z][a-z0-9+.-]*):", low)
    if not match:
        return "local"
    scheme = match.group(1)
    if scheme in ("http", "https"):
        return "external"
    return "special" if scheme in ("data", "blob", "javascript", "about") else "other-scheme"


def host_of(value):
    """Lowercase hostname of an absolute or protocol-relative URL, else None."""
    text = value.strip()
    if text.startswith("//"):
        text = "https:" + text
    return urlsplit(text).hostname if kind(value) == "external" else None


def split_srcset(value):
    """URL candidates of a srcset attribute (descriptors dropped)."""
    out, i, n = [], 0, len(value)
    while i < n:
        while i < n and (value[i].isspace() or value[i] == ","):
            i += 1
        j = i
        while j < n and not value[j].isspace():
            j += 1
        url = value[i:j]
        if not url:
            break
        stripped = url.rstrip(",")
        out.append(stripped)
        i = j
        if stripped == url:
            while i < n and value[i] != ",":
                i += 1
    return out


def role(ref):
    """resource (loaded), origin-hint (preconnect), navigation (a/area) or metadata."""
    if ref.tag in ("a", "area"):
        return "navigation"
    if ref.tag in ("base", "form"):
        return "metadata"
    if ref.tag == "link":
        rels = set(ref.attrs.get("rel", "").lower().split())
        if rels & RESOURCE_RELS:
            return "resource"
        return "origin-hint" if rels & HINT_RELS else "metadata"
    return "resource"


def html_refs(facts):
    """Every URL an HTML page points at: attributes, inline <style> and style="" values."""
    found = []
    for ref in facts.refs:
        values = split_srcset(ref.value) if ref.attr == "srcset" else [ref.value]
        found += [Found(role(ref), f"<{ref.tag} {ref.attr}>", v, ref.attrs) for v in values]
    for style in facts.styles:
        found += [Found("resource", "<style>", u, {}) for u in cssscan.urls(style.text)]
    for tag, value in facts.style_attrs:
        found += [Found("resource", f"<{tag} style>", u, {}) for u in cssscan.urls(value)]
    return found


def css_refs(text, where="css"):
    return [Found("resource", where, u, {}) for u in cssscan.urls(text)]


def _walk_exact(root, names):
    """Walk `names` below `root`; names must match on-disk case exactly."""
    current = root
    for i, name in enumerate(names):
        try:
            entries = os.listdir(current)
        except OSError:
            return None, f"{'/'.join(names[:i]) or 'public'} is not a directory"
        if name not in entries:
            folded = {e.casefold(): e for e in entries}
            if name.casefold() in folded:
                return None, (
                    f"case mismatch: '{name}' vs '{folded[name.casefold()]}' on disk "
                    "(macOS ignores case, Cloudflare Pages does not)"
                )
            return None, "no such file"
        current = current / name
    return current, None


def resolve(value, base_dir):
    """Resolve a local URL; returns (Path, None) for a served file or (None, reason)."""
    parts = urlsplit(value.strip())
    path = unquote(parts.path)
    absolute = path.startswith("/")
    try:
        stack = [] if absolute else list(base_dir.relative_to(PUBLIC).parts)
    except ValueError:
        return None, "base file is outside public/"
    for seg in path.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not stack:
                return None, "path escapes public/"
            stack.pop()
        else:
            stack.append(seg)
    if len(stack) == 1 and stack[0] in PAGES_CONTROL_FILES:
        return None, f"{stack[0]} is a Pages control file and is not served"
    found, why = _walk_exact(PUBLIC, stack)
    if found is not None and found.is_dir():
        found, why = _walk_exact(PUBLIC, stack + ["index.html"])
    if found is None and stack and not path.endswith("/") and "." not in stack[-1]:
        found, why = _walk_exact(PUBLIC, stack[:-1] + [stack[-1] + ".html"])
    if found is not None and not found.is_file():
        return None, "not a file"
    return found, (why if found is None else None)


def norm_link(value):
    """Canonical form for set comparison: lowercase scheme/host, empty path equals '/'."""
    text = value.strip()
    parts = urlsplit(text)
    scheme = parts.scheme.lower()
    if scheme in ("http", "https"):
        out = f"{scheme}://{parts.netloc.lower()}{parts.path or '/'}"
        out += f"?{parts.query}" if parts.query else ""
        return out + (f"#{parts.fragment}" if parts.fragment else "")
    if scheme in ("mailto", "tel"):
        return f"{scheme}:{text[len(scheme) + 1 :].strip()}"
    return text


def external_hrefs(facts):
    """Set of normalized https/http/mailto/tel hrefs on <a> and <area>."""
    out = set()
    for attrs in facts.anchors:
        href = attrs.get("href", "").strip()
        scheme = urlsplit(href).scheme.lower()
        if kind(href) == "external" or scheme in ("mailto", "tel"):
            out.add(norm_link("https:" + href if href.startswith("//") else href))
    return out
