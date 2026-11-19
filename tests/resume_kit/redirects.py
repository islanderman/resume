"""Cloudflare Pages `_redirects` model: a port of the parser Pages runs on the file and of the order
in which it matches the rules it keeps (workers-shared parseRedirects and its rules engine, as
wrangler 4.155.0 bundles them), JavaScript string semantics included. Each line Pages drops is a
problem."""

__unittest = True  # keeps helper frames out of unittest failure reports

import re
from dataclasses import dataclass

MAX_LINE = 2000  # in UTF-16 code units: Pages measures a JavaScript string's length
MAX_STATIC = 2000
MAX_DYNAMIC = 100
STATUSES = frozenset({200, 301, 302, 303, 307, 308})
DEFAULT_STATUS = 302
# ECMAScript WhiteSpace and LineTerminator: what trim() and \s remove in Pages' parser.
JS_SPACE = (
    "\t\n\v\f\r \u00a0\u1680"
    + "".join(map(chr, range(0x2000, 0x200B)))
    + "\u2028\u2029\u202f\u205f\u3000\ufeff"
)
SPACE_RUN = re.compile(f"[{re.escape(JS_SPACE)}]+")
JS_DOT = "[^\n\r\u2028\u2029]"  # JavaScript's '.' stops at every line terminator
INLINE_COMMENT = re.compile(f"[{re.escape(JS_SPACE)}]+#{JS_DOT}*\\Z")
# What JavaScript's Number() reads from a string with no spaces; anything else is NaN.
JS_NUMBER = re.compile(
    r"[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)"
    r"|0[xX][0-9a-fA-F]+|0[oO][0-7]+|0[bB][01]+"
)
DYNAMIC = re.compile(r"\*|:[A-Za-z]")  # a splat or a :placeholder makes a rule dynamic
PLACEHOLDER = re.compile(r":([A-Za-z][A-Za-z0-9_]*)")
ABSOLUTE = re.compile(f"https://+(?P<host>[^/]+)/?(?P<path>{JS_DOT}*)")  # Pages' URL_REGEX
INDEX_TARGET = re.compile(f"/index({JS_DOT}html)?\\Z")  # Pages' own regex, unescaped '.' and all
# WHATWG URL percent-encode sets for a non-special URL; each adds to the C0 control set.
FRAGMENT_SET = frozenset(' "<>`')
QUERY_SET = frozenset(' "#<>')
PATH_SET = QUERY_SET | frozenset("?^`{}")
C0_OR_SPACE = "".join(map(chr, range(0x21)))


@dataclass
class Rule:
    source: str  # normalized as Pages stores it: dot segments resolved, query and fragment gone
    target: str
    status: int
    line: int
    dynamic: bool = False  # matched in file order after the exact static lookup


@dataclass
class Parsed:
    rules: list
    problems: list  # each line Pages would reject or ignore


def utf16_len(text):
    return len(text.encode("utf-16-le")) // 2


def js_number(text):
    """JavaScript's Number(text) for a string with no spaces; None stands for NaN."""
    if not JS_NUMBER.fullmatch(text):
        return None
    return int(text, 0) if text[:2].lower() in ("0x", "0o", "0b") else float(text)


def _encode(text, extra):
    return "".join(
        "".join(f"%{b:02X}" for b in ch.encode("utf-8"))
        if ord(ch) < 0x20 or ord(ch) > 0x7E or ch in extra
        else ch
        for ch in text
    )


def _dots(segment):
    """2 for a '..' segment, 1 for '.', 0 otherwise; %2e counts as a dot, as in URL parsing."""
    return {"..": 2, ".": 1}.get(segment.lower().replace("%2e", "."), 0)


def url_parts(path):
    """(pathname, search, hash) of new URL('//' + path, 'relative://'), for a path that starts
    with '/': the WHATWG parse of a non-special URL with an empty host."""
    text = ("//" + path).strip(C0_OR_SPACE)
    text = "".join(ch for ch in text if ch not in "\t\n\r")[2:]
    cut = min((i for i in (text.find("?"), text.find("#")) if i >= 0), default=len(text))
    head, tail = text[:cut], text[cut:]
    query = fragment = ""
    if tail.startswith("?"):
        query, _, fragment = tail[1:].partition("#")
    elif tail.startswith("#"):
        fragment = tail[1:]
    segments = []
    parts = head[1:].split("/")
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        dots = _dots(part)
        if dots == 2 and segments:
            segments.pop()
        if dots and last:
            segments.append("")
        elif not dots:
            segments.append(_encode(part, PATH_SET))
    search = "?" + _encode(query, QUERY_SET) if query else ""
    hash_ = "#" + _encode(fragment, FRAGMENT_SET) if fragment else ""
    return "".join("/" + s for s in segments), search, hash_


def _pathname(path, search=False, fragment=False):
    """Pages' extractPathname."""
    name, query, frag = url_parts(path if path.startswith("/") else "/" + path)
    return name + (query if search else "") + (frag if fragment else "")


def _validate(token, relative_only=False, search=False, fragment=False):
    """Pages' validateUrl: the normalized URL, or None where Pages rejects the token."""
    absolute = ABSOLUTE.match(token)
    if absolute:
        if relative_only:
            return None
        return f"https://{absolute['host']}{_pathname(absolute['path'], search, fragment)}"
    if relative_only and not token.startswith("/"):
        token = "/" + token  # Pages reads a source with no leading slash as a /path
    return _pathname(token, search, fragment) if token.startswith("/") else None


def parse(text):
    rules, problems, seen = [], [], set()
    static = dynamic = 0
    for number, raw in enumerate(text.split("\n"), 1):
        line = raw.strip(JS_SPACE)
        if not line or line.startswith("#"):
            continue
        units = utf16_len(line)
        if units > MAX_LINE:
            problems.append(f"line {number}: length {units} exceeds Pages' {MAX_LINE} limit")
            continue
        fields = SPACE_RUN.split(INLINE_COMMENT.sub("", line, count=1))
        if len(fields) not in (2, 3):
            problems.append(f"line {number}: want 2 or 3 fields, got {len(fields)}")
            continue
        source = _validate(fields[0], relative_only=True)
        if source is None:
            problems.append(f"line {number}: source '{fields[0]}' must be a relative /path")
            continue
        # Pages counts every rule after the first dynamic one as dynamic too, valid or not.
        if dynamic or DYNAMIC.search(source):
            dynamic += 1
            if dynamic > MAX_DYNAMIC:
                problems.append(f"line {number}: over Pages' {MAX_DYNAMIC} dynamic rules")
                break
        else:
            static += 1
            if static > MAX_STATIC:
                problems.append(f"line {number}: over Pages' {MAX_STATIC} static rules")
                continue
        target = _validate(fields[1], search=True, fragment=True)
        if target is None:
            problems.append(f"line {number}: target '{fields[1]}' needs a /path or an https:// host")
            continue
        status_text = fields[2] if len(fields) == 3 else str(DEFAULT_STATUS)
        status = js_number(status_text)
        if status not in STATUSES:
            problems.append(f"line {number}: status '{status_text}' is not in {sorted(STATUSES)}")
            continue
        relative = not ABSOLUTE.match(target)
        if relative and INDEX_TARGET.search(target) and source.endswith(("/", "/*")):
            # Pages strips /index or .html with a redirect, which would hit this rule again.
            problems.append(f"line {number}: '{source} {target}' loops; Pages drops it")
            continue
        if source in seen:
            problems.append(f"line {number}: duplicate rule for '{source}'; Pages keeps the first")
            continue
        seen.add(source)
        if status == 200 and not relative:
            problems.append(f"line {number}: a 200 rewrite needs a relative target, got '{target}'")
            continue
        rules.append(Rule(source, target, int(status), number))
    # Exact static lookups hold only the rules above the first dynamic one; the rest match in order.
    static_slot = True
    for rule in rules:
        static_slot = static_slot and not DYNAMIC.search(rule.source)
        rule.dynamic = not static_slot
    return Parsed(rules, problems)


def pattern(source):
    """Pages' regex for a dynamic source, or None where JavaScript rejects it: such a rule never
    matches (two splats or two placeholders of one name repeat a group name)."""
    text = f"(?P<splat>{JS_DOT}*)".join(re.escape(part) for part in source.split("*"))
    for found in PLACEHOLDER.finditer(text):
        text = text.replace(found.group(0), f"(?P<{found.group(1)}>[^/]+)")
    try:
        return re.compile(f"\\A{text}\\Z")
    except re.error:
        return None


def match(parsed, path):
    """The rule Pages applies to a request for `path` (a URL pathname): the exact static rule
    first, then the first dynamic rule that matches, in file order; None when none does."""
    for rule in parsed.rules:
        if not rule.dynamic and rule.source == path:
            return rule
    for rule in parsed.rules:
        regex = pattern(rule.source) if rule.dynamic else None
        if regex and regex.match(path):
            return rule
    return None
