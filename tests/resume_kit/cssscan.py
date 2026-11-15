"""Small tolerant CSS reader: url() scan, rule and media parse, media-query width bounds."""

__unittest = True  # keeps helper frames out of unittest failure reports

import math
import re
from dataclasses import dataclass

VIEWPORT = 390  # iPhone-class viewport the fixed-width guard is evaluated at
COMMENT = re.compile(r"/\*.*?\*/", re.S)
URL_FN = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)\s"'][^)]*?))\s*\)""", re.I)
IMPORT_STR = re.compile(r"""@import\s+(?:"([^"]+)"|'([^']+)')""", re.I)
QUOTED = re.compile(r""""([^"]+)"|'([^']+)'""")
LENGTH = re.compile(r"^\s*(-?\d*\.?\d+)\s*([a-z%]*)\s*$", re.I)
PX_PER = {
    "px": 1.0, "pt": 96 / 72, "pc": 16.0, "in": 96.0, "cm": 96 / 2.54, "mm": 96 / 25.4,
    "q": 96 / 101.6, "em": 16.0, "rem": 16.0, "ex": 8.0, "ch": 8.0,
}  # fmt: skip
REL_UNITS = ("%", "vw", "vi", "dvw", "dvi", "svw", "svi", "lvw", "lvi", "vmin", "cqw", "cqi")
INLINE_SIZE = {
    "inline-size": "width", "min-inline-size": "min-width", "max-inline-size": "max-width",
    "block-size": "height", "min-block-size": "min-height", "max-block-size": "max-height",
}  # fmt: skip
VAR = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*((?:[^()]|\([^()]*\))*))?\)")


@dataclass
class Rule:
    media: tuple
    selector: str
    decls: list  # (property, value, important)


@dataclass
class Sheet:
    rules: list
    media_queries: list


def strip_comments(text):
    return COMMENT.sub(" ", text)


def _first(match):
    return next(g for g in match.groups() if g is not None)


def _balanced(text, open_idx):
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1 : i]
    return text[open_idx + 1 :]


def urls(text):
    """Raw URL strings from url(), @import "x" and image-set("x"); data: and #frag kept for callers."""
    text = strip_comments(text)
    found = [_first(m) for m in URL_FN.finditer(text)]
    found += [_first(m) for m in IMPORT_STR.finditer(text)]
    for m in re.finditer(r"image-set\(", text, re.I):
        found += [_first(q) for q in QUOTED.finditer(_balanced(text, m.end() - 1))]
    return list(dict.fromkeys(u.strip() for u in found if u.strip()))


def font_face_bodies(text):
    return re.findall(r"@font-face\s*\{([^{}]*)\}", strip_comments(text), re.I)


# --- rule parser -------------------------------------------------------------
def _scan(text, i, end):
    """Index of the next ; { } outside quotes and parentheses, or `end`."""
    quote, depth = None, 0
    while i < end:
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and c in ";{}":
            return i
        i += 1
    return end


def _match(text, open_i, end):
    depth, quote, paren = 0, None, 0
    i = open_i
    while i < end:
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "(":
            paren += 1
        elif c == ")":
            paren = max(0, paren - 1)
        elif paren == 0 and c == "{":
            depth += 1
        elif paren == 0 and c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return end


def _decl(text):
    if ":" not in text or text.lstrip().startswith("@"):
        return None
    prop, _, value = text.partition(":")
    value = value.strip()
    important = bool(re.search(r"!\s*important\s*$", value, re.I))
    value = re.sub(r"\s*!\s*important\s*$", "", value, flags=re.I)
    name = prop.strip()
    return (name if name.startswith("--") else name.lower()), value, important


def _join(parent, child):
    return child.replace("&", parent) if "&" in child else f"{parent} {child}"


def _block(text, i, end, media, selector, rules, media_queries):
    decls = []
    while i < end:
        j = _scan(text, i, end)
        prelude = text[i:j].strip()
        if j >= end:
            if prelude:
                decls.append(prelude)
            break
        if text[j] == ";":
            if prelude:
                decls.append(prelude)
            i = j + 1
        elif text[j] == "}":
            i = j + 1
        else:
            k = _match(text, j, end)
            name = re.match(r"@([\w-]+)", prelude)
            if prelude.startswith("@"):
                at = name.group(1).lower() if name else ""
                if at in ("media", "supports", "layer", "container", "scope"):
                    query = prelude[len(at) + 1 :].strip()
                    inner_media = media + (query,) if at == "media" else media
                    if at == "media":
                        media_queries.append(query)
                    inner = _block(text, j + 1, k, inner_media, selector, rules, media_queries)
                    if selector is not None and inner:
                        rules.append(Rule(inner_media, selector, _decls(inner)))
            else:
                sel = prelude if selector is None else _join(selector, prelude)
                rule = Rule(media, sel, [])
                rules.append(rule)  # parent first, so nested rules cascade after it
                rule.decls = _decls(_block(text, j + 1, k, media, sel, rules, media_queries))
            i = k + 1
    return decls


def _decls(raw):
    return [d for d in (_decl(r) for r in raw) if d]


def parse(text):
    rules, media_queries = [], []
    clean = strip_comments(text)
    _block(clean, 0, len(clean), (), None, rules, media_queries)
    return Sheet(rules, media_queries)


# --- lengths and media queries -------------------------------------------------
def to_px(value, rem=16.0):
    """Absolute length in CSS px (rem/em use `rem`), or None for %, vw, functions, keywords."""
    match = LENGTH.match(value)
    if not match:
        return None
    number, unit = float(match.group(1)), match.group(2).lower()
    if unit in ("rem", "em"):
        return number * rem
    if unit in PX_PER:
        return number * PX_PER[unit]
    return 0.0 if unit == "" and number == 0 else None


def _split_top(text, sep=","):
    parts, depth, cur = [], 0, []
    for c in text:
        depth += c == "("
        depth -= c == ")"
        if c == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    parts.append("".join(cur))
    return parts


def alternatives(query_list):
    return [a.strip() for a in _split_top(query_list) if a.strip()]


RANGE = re.compile(
    r"^(?:(?P<a>[^<>=]+?)\s*(?P<o1>[<>]=?)\s*)?(?:device-)?width"
    r"(?:\s*(?P<o2>[<>]=?)\s*(?P<b>[^<>=]+?))?$"
)


def _bounds(cond):
    cond = cond.strip().lower()
    match = re.match(r"^(min|max)-(?:device-)?width\s*:\s*(.+)$", cond)
    if match:
        px = to_px(match.group(2))
        if px is None:
            return 0.0, math.inf
        return (px, math.inf) if match.group(1) == "min" else (0.0, px)
    match = re.match(r"^(?:device-)?width\s*:\s*(.+)$", cond)
    if match:
        px = to_px(match.group(1))
        return (0.0, math.inf) if px is None else (px, px)
    match = RANGE.match(cond)
    lo, hi = 0.0, math.inf
    if match and (match.group("o1") or match.group("o2")):
        if match.group("o1"):
            a = to_px(match.group("a"))
            if a is not None:
                lo, hi = (a, hi) if match.group("o1").startswith("<") else (lo, a)
        if match.group("o2"):
            b = to_px(match.group("b"))
            if b is not None:
                lo, hi = (max(lo, b), hi) if match.group("o2").startswith(">") else (lo, min(hi, b))
    return lo, hi


def width_range(alternative):
    """(lo, hi) viewport width in px that one media query alternative accepts."""
    lo, hi = 0.0, math.inf
    for cond in re.findall(r"\(([^()]*)\)", alternative):
        c_lo, c_hi = _bounds(cond)
        lo, hi = max(lo, c_lo), min(hi, c_hi)
    return lo, hi


def media_types(alternative):
    head = alternative.split("(", 1)[0].lower()
    return set(re.findall(r"[a-z-]+", head)) & {"screen", "print", "speech", "all"}


def applies(query_list, width, media="screen"):
    """True when an @media prelude can match `width` px for the given media type."""
    alts = alternatives(query_list)
    if not alts:
        return True
    for alt in alts:
        if re.match(r"^\s*not\b", alt, re.I):
            return True  # negated queries are not evaluated; assume they may match
        types = media_types(alt)
        if types and media not in types and "all" not in types:
            continue
        lo, hi = width_range(alt)
        if lo <= width <= hi:
            return True
    return False


# Phone: upper bound <= 600px, or a lower bound at a phone size (480px and under).
def phone_like(lo, hi):
    return hi <= 600 or 0 < lo <= 480


# Tablet: lower bound 481-1023px, or an upper bound above 600px up to 1024px.
def tablet_like(lo, hi):
    return 481 <= lo < 1024 or 600 < hi <= 1024


def width_queries(sheet, extra=()):
    """(query, lo, hi) for every width-bounded, screen-capable media query alternative."""
    out = []
    for query in list(sheet.media_queries) + list(extra):
        for alt in alternatives(query):
            types = media_types(alt)
            lo, hi = width_range(alt)
            if (types and not types & {"screen", "all"}) or (lo == 0 and hi == math.inf):
                continue
            out.append((alt, lo, hi))
    return out


# --- cascade-lite ----------------------------------------------------------------
def effective(sheet, width, media="screen", match=None):
    """selector -> {property: (value, important)} for rules active at `width` (later wins)."""
    out = {}
    for rule in sheet.rules:
        if match and not match(rule.selector):
            continue
        if not all(applies(q, width, media) for q in rule.media):
            continue
        slot = out.setdefault(rule.selector, {})
        for prop, value, important in rule.decls:
            prop = INLINE_SIZE.get(prop, prop)
            if prop in slot and slot[prop][1] and not important:
                continue
            slot[prop] = (value, important)
    return out


def resolve_vars(value, *scopes):
    """Substitute var(--x[, fallback]) from the given scopes (dicts of property -> (value, important))."""

    def pick(match):
        for scope in scopes:
            if match.group(1) in scope:
                return scope[match.group(1)][0]
        return match.group(2).strip() if match.group(2) else match.group(0)

    for _ in range(5):
        replaced = VAR.sub(pick, value)
        if replaced == value:
            break
        value = replaced
    return value


def root_scope(eff):
    """Custom properties and font-size declared on html/:root (:root is more specific)."""
    scope = {}
    for selector in ("html", ":root"):
        scope.update(eff.get(selector, {}))
    return scope


def root_font_px(scope):
    value = scope.get("font-size", ("", False))[0].strip()
    match = LENGTH.match(value)
    if match and match.group(2) == "%":
        return 16.0 * float(match.group(1)) / 100
    return to_px(value) or 16.0


def _length(props, name, root, rem):
    if name not in props:
        return None
    text = resolve_vars(props[name][0], props, root)
    return None if "(" in text else to_px(text, rem)


def resolved_sizes(sheet, width, media="screen", match=None):
    """selector -> (width px, height px, filter) with var() and rem resolved in that media context."""
    eff = effective(sheet, width, media)
    root = root_scope(eff)
    rem = root_font_px(root)
    out = {}
    for selector, props in eff.items():
        if match and not match(selector):
            continue
        flt = resolve_vars(props.get("filter", ("", False))[0], props, root).lower()
        out[selector] = (
            _length(props, "width", root, rem),
            _length(props, "height", root, rem),
            flt,
        )
    return out


def _relative(value):
    match = LENGTH.match(value)
    if match and match.group(2).lower() in REL_UNITS:
        return float(match.group(1))
    return None


def _has_fallback(value, rem=16.0):
    low = value.strip().lower()
    if "(" in low:
        return any(unit in low for unit in ("%", "vw", "vi", "vmin"))
    rel = _relative(low)
    if rel is not None:
        return rel <= 100
    px = to_px(low, rem)
    return px is not None and px <= VIEWPORT


def width_problems(sheet, viewport=VIEWPORT):
    """Fixed widths that overflow a `viewport`-px screen (heuristic, per selector string)."""
    problems = []
    eff = effective(sheet, viewport)
    root = root_scope(eff)
    rem = root_font_px(root)
    for selector, props in eff.items():
        text = {
            k: resolve_vars(props[k][0], props, root)
            for k in ("width", "min-width", "max-width")
            if k in props
        }
        if "width" in text:
            px = None if "(" in text["width"] else to_px(text["width"], rem)
            rel = _relative(text["width"])
            fallback = "max-width" in text and _has_fallback(text["max-width"], rem)
            if px is not None and px > viewport and not fallback:
                problems.append(
                    f"{selector} {{ width: {text['width']} }} is over {viewport}px with no max-width fallback"
                )
            if rel is not None and rel > 100:
                problems.append(
                    f"{selector} {{ width: {text['width']} }} is wider than its container"
                )
        if "min-width" in text:
            px = None if "(" in text["min-width"] else to_px(text["min-width"], rem)
            if px is not None and px > viewport:
                problems.append(
                    f"{selector} {{ min-width: {text['min-width']} }} forces overflow at {viewport}px"
                )
    return problems
