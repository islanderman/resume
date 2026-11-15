"""Cloudflare Pages `_headers` parser (mirrors Pages' own rules) and CSP source matching."""

__unittest = True  # keeps helper frames out of unittest failure reports

import base64
import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

MAX_RULES = 100
MAX_LINE = 2000
PATH_LINE = re.compile(r"^([^\s]+://|/)")  # Pages decides "this line starts a rule" with this test
HTTPS_URL = re.compile(r"^https://+(?P<host>[^/]+)/?(?P<path>.*)")
HASH_PREFIXES = ("'sha256-", "'sha384-", "'sha512-")


@dataclass
class HeaderRule:
    pattern: str
    line: int
    headers: dict = field(default_factory=dict)  # lowercase name -> [values]
    unset: list = field(default_factory=list)

    def value(self, name):
        values = self.headers.get(name.lower())
        return ", ".join(values) if values else None

    @property
    def host(self):
        match = HTTPS_URL.match(self.pattern)
        return match.group("host").lower() if match else None


@dataclass
class Parsed:
    rules: list
    problems: list
    duplicates: list  # "<pattern>: <header> set N times"


def parse(text):
    rules, problems, duplicates = [], [], []
    current = None

    def close():
        if current is None:
            return
        if current.headers or current.unset:
            rules.append(current)
        else:
            problems.append(f"line {current.line}: rule '{current.pattern}' has no headers")

    for number, raw in enumerate(text.split("\n"), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if len(line) > MAX_LINE:
            problems.append(f"line {number}: {len(line)} chars exceeds Pages' {MAX_LINE} limit")
            continue
        if PATH_LINE.match(line):
            close()
            current = None
            if line.startswith("/") or HTTPS_URL.match(line):
                host = HTTPS_URL.match(line)
                if host and re.search(r":\d+$", host.group("host")):
                    problems.append(f"line {number}: ports are not supported in '{line}'")
                else:
                    current = HeaderRule(line, number)
            else:
                problems.append(f"line {number}: '{line}' must be a /path or an https:// URL")
            continue
        if ":" not in line:
            if current and line.startswith("! "):
                current.unset.append(line[2:].strip())
            else:
                problems.append(f"line {number}: expected 'Name: value', got '{line}'")
            continue
        name, _, value = line.partition(":")
        name, value = name.strip().lower(), value.strip()
        if " " in name or not name:
            problems.append(f"line {number}: bad header name '{name}'")
        elif not value:
            problems.append(f"line {number}: header '{name}' has no value")
        elif current is None:
            problems.append(f"line {number}: header '{name}' appears before any path")
        else:
            current.headers.setdefault(name, []).append(value)
            if len(current.headers[name]) == 2:
                duplicates.append(f"{current.pattern}: '{name}' is set more than once")
    close()
    if len(rules) > MAX_RULES:
        problems.append(f"{len(rules)} rules exceed Pages' limit of {MAX_RULES}")
    seen = {}
    for rule in rules:
        if rule.pattern in seen:
            problems.append(
                f"line {rule.line}: pattern '{rule.pattern}' repeats line {seen[rule.pattern]}"
            )
        seen.setdefault(rule.pattern, rule.line)
    return Parsed(rules, problems, duplicates)


# --- Content-Security-Policy -----------------------------------------------------
FALLBACKS = {
    "script-src-elem": ("script-src", "default-src"),
    "script-src": ("default-src",),
    "style-src-elem": ("style-src", "default-src"),
    "style-src": ("default-src",),
    "style-src-attr": ("style-src", "default-src"),
    "frame-src": ("child-src", "default-src"),
}


def parse_csp(value):
    """List of policies (one per comma); each maps directive -> source list, first one wins."""
    policies = []
    for chunk in value.split(","):
        policy = {}
        for part in chunk.split(";"):
            tokens = part.split()
            if tokens:
                policy.setdefault(tokens[0].lower(), tokens[1:])
        if policy:
            policies.append(policy)
    return policies


def effective(policy, directive):
    """Source list that governs `directive` after fallbacks, or None when unrestricted."""
    for name in (directive,) + FALLBACKS.get(directive, ("default-src",)):
        if name in policy:
            return policy[name]
    return None


def _host_source(source, scheme, host, port, path):
    match = re.match(
        r"^(?:(?P<scheme>[a-z][a-z0-9+.-]*)://)?(?P<host>\*\.[^/:]+|\*|[^/:*]+)"
        r"(?::(?P<port>\d+|\*))?(?P<path>/.*)?$",
        source,
    )
    if not match:
        return False
    src_scheme = match.group("scheme")
    if src_scheme and src_scheme != scheme and not (src_scheme == "http" and scheme == "https"):
        return False
    if not src_scheme and scheme not in ("http", "https"):
        return False
    src_host = match.group("host")
    if src_host.startswith("*."):
        if not (host.endswith(src_host[1:]) and host != src_host[2:]):
            return False
    elif src_host != "*" and src_host != host:
        return False
    src_port = match.group("port")
    default = 443 if scheme == "https" else 80
    if src_port and src_port != "*" and int(src_port) != (port or default):
        return False
    src_path = match.group("path")
    if src_path:
        return path.startswith(src_path) if src_path.endswith("/") else path == src_path
    return True


def allows(sources, url=None):
    """Does a source list admit `url`? url=None means a same-origin resource."""
    if sources is None:
        return True
    lowered = [s.lower() for s in sources]
    if url is None:
        return any(s in ("'self'", "*", "https:", "http:") for s in lowered)
    parts = urlsplit(url)
    scheme, host, port, path = parts.scheme, (parts.hostname or ""), parts.port, parts.path or "/"
    for source in lowered:
        if source == "'none'" or source.startswith("'"):
            continue
        if source in ("https:", "http:", "wss:", "ws:", "data:", "blob:"):
            if source == scheme + ":" or (source == "http:" and scheme == "https"):
                return True
        elif source == "*":
            if scheme in ("http", "https", "ws", "wss"):
                return True
        elif _host_source(source, scheme, host, port, path):
            return True
    return False


def inline_allowed(sources, text, attribute=False):
    """Is an inline script/style (or a style="" attribute) permitted by this source list?"""
    if sources is None:
        return True
    lowered = [s.lower() for s in sources]
    nonce_or_hash = any(s.startswith(("'nonce-",) + HASH_PREFIXES) for s in lowered)
    if "'unsafe-inline'" in lowered and not nonce_or_hash:
        return True
    if attribute and "'unsafe-hashes'" not in lowered:
        return False
    return any(hash_source(text, algo) in sources for algo in ("sha256", "sha384", "sha512"))


def hash_source(text, algo="sha256"):
    digest = base64.b64encode(hashlib.new(algo, text.encode("utf-8")).digest()).decode()
    return f"'{algo}-{digest}'"


def permissions_denied(value):
    """Features a Permissions-Policy turns off completely, e.g. camera=()."""
    denied = set()
    depth, chunk, parts = 0, [], []
    for c in value:
        depth += c == "("
        depth -= c == ")"
        if c == "," and depth == 0:
            parts.append("".join(chunk))
            chunk = []
        else:
            chunk.append(c)
    parts.append("".join(chunk))
    for part in parts:
        name, _, allow = part.partition("=")
        if allow.strip() == "()":
            denied.add(name.strip().lower())
    return denied
