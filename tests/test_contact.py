"""Masthead contact row: one list of the contact items, each led by a decorative inline SVG glyph,
with LinkedIn's In bug on the LinkedIn link. tests/test_parity.py pins the text and the links;
this file pins the list, the glyphs, the brand mark and their styles. Owner rule: LinkedIn is the
only profile link on the resume."""

import re
import unittest
from html.parser import HTMLParser

from resume_kit import cssscan, htmlfacts, pagecss, refs, svgcheck
from resume_kit.common import INDEX, PUBLIC, read_text, rel, report
from resume_kit.htmlfacts import VOID

NOT_FOUND = PUBLIC / "404.html"
LINKEDIN = "https://www.linkedin.com/in/chenyang"
ADDRESS = "zhenyoung@gmail.com"
ITEMS = (
    "Cell: (917) 582-2826",
    ADDRESS,
    "https://resume.chenyang.us/",
    "linkedin.com/in/chenyang",
)
# The 404 page keeps its masthead as it was: the same items without LinkedIn.
PAGE_ITEMS = {INDEX: ITEMS, NOT_FOUND: ITEMS[:3]}
# (href, rel tokens it must carry, accessible name) of each contact link on index.html.
LINKS = (
    (f"mailto:{ADDRESS}", {"me"}, ADDRESS),
    ("https://resume.chenyang.us", set(), "https://resume.chenyang.us/"),
    (LINKEDIN, {"me"}, "linkedin.com/in/chenyang"),
)
# LinkedIn's In bug as linkedin.com draws it: a 34x34 rounded square with the "in" knocked out,
# filled with currentColor. Brand rule: unaltered proportions, so change it only to a newer
# official asset.
BUG_VIEWBOX = (0.0, 0.0, 34.0, 34.0)
BUG_PATH = (
    "M34,2.5v29A2.5,2.5,0,0,1,31.5,34H2.5A2.5,2.5,0,0,1,0,31.5V2.5A2.5,2.5,0,0,1,2.5,0h29A2.5,"
    "2.5,0,0,1,34,2.5ZM10,13H5V29h5Zm.45-5.5A2.88,2.88,0,0,0,7.59,4.6H7.5a2.9,2.9,0,0,0,0,5.8h0"
    "a2.88,2.88,0,0,0,2.95-2.81ZM29,19.28c0-4.81-3.06-6.68-6.1-6.68a5.7,5.7,0,0,0-5.06,2.58H17.7"
    "V13H13V29h5V20.49a3.32,3.32,0,0,1,3-3.58h.19c1.59,0,2.77,1,2.77,3.52V29h5Z"
)
LINKEDIN_BLUE = "#0a66c2"  # LinkedIn Blue, the bug's only screen color (brand.linkedin.com)
BUG_SELECTOR = ".contact .linkedin-bug"
GLYPH_SELECTOR = ".contact svg"
SCREENS = (320, 390, 600, 768, 1024, 1440)
# Brand rule: no rotation, outline or effect on the bug; the glyphs follow the same rule.
EFFECT_ATTRS = ("transform", "filter", "opacity", "stroke", "mask", "clip-path", "style")
EFFECT_PROPS = ("transform", "rotate", "scale", "filter", "opacity", "box-shadow", "outline")
# What a decorative glyph may hold: plain shapes, nothing that names, links, loads or runs.
SHAPES = frozenset({"path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "g"})
ARIA_NAMES = ("role", "aria-label", "aria-labelledby", "aria-describedby", "tabindex")


class _ContactTree(HTMLParser):
    """The first class="contact" element as (tag, attrs, children); text children are str."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = None
        self.stack = []
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs_list):
        attrs = {name: value or "" for name, value in attrs_list}
        node = (tag, attrs, [])
        if self.stack:
            self.stack[-1][2].append(node)
        elif self.root is None and "contact" in attrs.get("class", "").split():
            self.root = node
        else:
            return
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for depth in range(len(self.stack) - 1, -1, -1):
            if self.stack[depth][0] == tag:
                del self.stack[depth:]
                return

    def handle_data(self, data):
        if self.stack:
            self.stack[-1][2].append(data)


def contact(path):
    return _ContactTree(read_text(path, "page under test")).root


def norm(text):
    return " ".join(text.split())


def content(node):
    """Child elements and non-blank text, in order."""
    return [k for k in node[2] if not isinstance(k, str) or k.strip()]


def is_tag(node, tag):
    return not isinstance(node, str) and node[0] == tag


def nodes_in(node):
    """Every element below `node`, depth first, in document order."""
    found = []
    for kid in node[2]:
        if not isinstance(kid, str):
            found += [kid] + nodes_in(kid)
    return found


def descendants(node, tag):
    return [n for n in nodes_in(node) if n[0] == tag]


def name_of(node):
    """Accessible name from content: text, skipping aria-hidden subtrees."""
    if node[1].get("aria-hidden") == "true":
        return ""
    return norm("".join(k if isinstance(k, str) else name_of(k) for k in node[2]))


def items(path):
    """(li, the element its glyph and text live in: the link or the li itself) per list item."""
    root = contact(path)
    lists = content(root) if root else []
    if len(lists) != 1 or not is_tag(lists[0], "ul"):
        return []
    found = []
    for li in content(lists[0]):
        kids = content(li) if is_tag(li, "li") else []
        holder = kids[0] if len(kids) == 1 and is_tag(kids[0], "a") else li
        found.append((li, holder))
    return found


def glyph_problems(svg):
    """Problems with one decorative glyph: hidden, unfocusable, square, inert."""
    attrs = svg[1]
    problems = []
    if attrs.get("aria-hidden") != "true":
        problems.append('no aria-hidden="true"')
    if attrs.get("focusable") != "false":
        problems.append('no focusable="false"')
    problems += [f"carries {a}" for a in ARIA_NAMES if a in attrs]
    box = svgcheck.parse_viewbox(attrs.get("viewbox"))
    if box is None or box[2] != box[3]:
        problems.append(f"viewBox {attrs.get('viewbox')!r} is not square")
    width, height = attrs.get("width", ""), attrs.get("height", "")
    if not (width.isdigit() and width == height):
        problems.append(f"width={width!r} height={height!r} are not equal integers")
    if "style" in attrs:
        problems.append("carries a style attribute (the CSP blocks it)")
    tags = {n[0] for n in nodes_in(svg)} - SHAPES
    if tags:
        problems.append(f"holds {sorted(tags)}; a glyph is shapes only")
    if any(name.startswith("on") for node in [svg] + nodes_in(svg) for name in node[1]):
        problems.append("carries an event handler")
    return problems


def screen_sheet():
    """The page sheet without forced-colors rules: cssscan treats that feature as always on."""
    sheet = pagecss.page_sheet()
    rules = [r for r in sheet.rules if not any("forced-colors" in q for q in r.media)]
    return cssscan.Sheet(rules, sheet.media_queries)


def resolved(sheet, width, selector, prop, media="screen"):
    eff = cssscan.effective(sheet, width, media)
    value = eff.get(selector, {}).get(prop, ("", False))[0]
    return cssscan.resolve_vars(value, eff.get(selector, {}), cssscan.root_scope(eff)).strip()


class ContactListTest(unittest.TestCase):
    def test_contact_is_one_list_of_exactly_the_approved_items(self):
        problems = []
        for path, expected in PAGE_ITEMS.items():
            root = contact(path)
            kids = content(root) if root else []
            if len(kids) != 1 or not is_tag(kids[0], "ul"):
                problems.append(f"{rel(path)}: .contact must hold one <ul> and nothing else")
                continue
            ul = kids[0]
            if ul[1].get("role") != "list":
                # Safari drops the list role once CSS removes the markers.
                problems.append(f'{rel(path)}: the <ul> needs role="list"')
            texts = [name_of(li) if is_tag(li, "li") else repr(li)[:40] for li in content(ul)]
            if texts != list(expected):
                problems.append(f"{rel(path)}: items {texts}, expected {list(expected)}")
        report(self, "contact list", problems)

    def test_every_item_leads_with_one_decorative_glyph(self):
        problems = []
        for path in PAGE_ITEMS:
            found = items(path)
            if not found:
                problems.append(f"{rel(path)}: no contact list items")
            for li, holder in found:
                label = name_of(li) or "?"
                svgs = descendants(li, "svg")
                first = content(holder)[:1]
                if len(svgs) != 1:
                    problems.append(f"{rel(path)} '{label}': {len(svgs)} <svg>, expected 1")
                elif not first or first[0] is not svgs[0]:
                    problems.append(f"{rel(path)} '{label}': the glyph is not before the text")
                else:
                    problems += [f"{rel(path)} '{label}': {p}" for p in glyph_problems(svgs[0])]
        report(self, "contact glyphs", problems)

    def test_links_keep_href_rel_and_their_visible_text_as_name(self):
        anchors = [holder for _, holder in items(INDEX) if is_tag(holder, "a")]
        problems = []
        if len(anchors) != len(LINKS):
            problems.append(f"{len(anchors)} contact links, expected {len(LINKS)}")
        for a, (href, rels, name) in zip(anchors, LINKS):
            got_rel = set(a[1].get("rel", "").lower().split())
            if a[1].get("href") != href:
                problems.append(f"link {name!r}: href {a[1].get('href')!r}, expected {href!r}")
            if not rels <= got_rel:
                problems.append(f"link {name!r}: rel {sorted(got_rel)} lacks {sorted(rels)}")
            if name_of(a) != name:
                problems.append(f"link {href!r}: accessible name {name_of(a)!r}, expected {name!r}")
            # WCAG 2.5.3: the visible text is the name; no ARIA name may replace it.
            problems += [f"link {href!r} carries {k}" for k in ARIA_NAMES if k in a[1]]
        report(self, "contact links", problems)

    def test_both_pages_link_the_address_with_mailto(self):
        # Visitors need the mailto: link, and Cloudflare obfuscates it at the edge. The edge skips
        # JSON-LD and llms.txt, so tests/test_seo.py keeps the address out of both.
        problems = []
        for path in PAGE_ITEMS:
            anchors = [h for _, h in items(path) if is_tag(h, "a") and name_of(h) == ADDRESS]
            hrefs = [a[1].get("href") for a in anchors]
            if hrefs != [f"mailto:{ADDRESS}"]:
                problems.append(f"{rel(path)}: {ADDRESS} links {hrefs}, expected one mailto: link")
        report(self, "visible email links", problems)

    def test_linkedin_is_the_only_profile_link(self):
        own = refs.host_of("https://resume.chenyang.us/")
        anchors = [h[1] for _, h in items(INDEX) if is_tag(h, "a")]
        anchors += [a for a in htmlfacts.page(INDEX).anchors if "me" in a.get("rel", "").split()]
        profiles = {
            refs.norm_link(a.get("href", ""))
            for a in anchors
            if refs.kind(a.get("href", "")) == "external" and refs.host_of(a.get("href", "")) != own
        }
        self.assertEqual(profiles, {refs.norm_link(LINKEDIN)}, "profile links on index.html")


class LinkedInBugTest(unittest.TestCase):
    def test_linkedin_link_shows_the_unaltered_in_bug_before_its_text(self):
        links = [h for _, h in items(INDEX) if is_tag(h, "a") and h[1].get("href") == LINKEDIN]
        if len(links) != 1:
            self.fail(f"{len(links)} LinkedIn links in the contact list, expected 1")
        kids = content(links[0])
        svg = kids[0] if kids and is_tag(kids[0], "svg") else None
        if svg is None:
            self.fail("the LinkedIn link does not start with an inline <svg>")
        problems = []
        if "linkedin-bug" not in svg[1].get("class", "").split():
            problems.append('the bug <svg> lacks class="linkedin-bug"')
        if svgcheck.parse_viewbox(svg[1].get("viewbox")) != BUG_VIEWBOX:
            problems.append(f"viewBox {svg[1].get('viewbox')!r}, expected 0 0 34 34")
        paths = nodes_in(svg)
        if len(paths) != 1 or paths[0][0] != "path":
            problems.append(f"holds {[n[0] for n in paths]}, expected one <path>")
        else:
            if paths[0][1].get("d") != BUG_PATH:
                problems.append("the path is not LinkedIn's In bug")
            if paths[0][1].get("fill") != "currentColor":
                problems.append(f"fill={paths[0][1].get('fill')!r}, expected currentColor")
        for node in [svg] + paths:
            problems += [f"<{node[0]}> carries {a}" for a in EFFECT_ATTRS if a in node[1]]
        if [norm(k) for k in kids[1:] if isinstance(k, str)] != ["linkedin.com/in/chenyang"]:
            problems.append("the bug is not followed by exactly linkedin.com/in/chenyang")
        report(self, "LinkedIn In bug", problems)

    def test_bug_is_linkedin_blue_and_glyphs_are_secondary_on_screen(self):
        sheet = screen_sheet()
        problems = []
        for width in SCREENS:
            bug = resolved(sheet, width, BUG_SELECTOR, "color").lower()
            glyph = resolved(sheet, width, GLYPH_SELECTOR, "color").lower()
            root = cssscan.root_scope(cssscan.effective(sheet, width))
            secondary = root.get("--color-secondary", ("--color-secondary unset", False))[0]
            if bug != LINKEDIN_BLUE:
                problems.append(f"{width}px: the bug is {bug!r}, expected {LINKEDIN_BLUE}")
            if glyph != secondary.lower():
                problems.append(f"{width}px: glyphs are {glyph!r}, expected {secondary}")
        report(self, "contact glyph colors", problems)

    def test_glyphs_follow_the_users_palette_in_forced_colors(self):
        # Forced colors: the glyphs and the bug take the text or link color; the knocked-out
        # "in" then shows the user's background.
        tokens = {}
        for rule in pagecss.page_sheet().rules:
            if rule.selector == ":root" and any("forced-colors: active" in q for q in rule.media):
                tokens.update({p: v for p, v, _ in rule.decls})
        problems = [
            f"forced colors sets {t} to {tokens.get(t)!r}, expected currentColor"
            for t in ("--color-glyph", "--color-linkedin")
            if tokens.get(t, "").lower() != "currentcolor"
        ]
        report(self, "forced-colors palette", problems)


class ContactStyleTest(unittest.TestCase):
    def test_glyphs_are_square_and_scale_with_the_text(self):
        sheet = screen_sheet()
        problems = []
        for width in SCREENS:
            w = resolved(sheet, width, GLYPH_SELECTOR, "width")
            h = resolved(sheet, width, GLYPH_SELECTOR, "height")
            match = cssscan.LENGTH.match(w)
            if w != h:
                problems.append(f"{width}px: glyphs are {w!r} x {h!r}, not square")
            elif not match or match.group(2) != "em" or not 1 <= float(match.group(1)) <= 1.5:
                problems.append(f"{width}px: glyph size {w!r} is not 1em-1.5em")
        report(self, "glyph size", problems)

    def test_no_rotation_outline_or_effect_on_the_glyphs(self):
        sheet = pagecss.page_sheet()
        problems = []
        for width, media in [(w, "screen") for w in SCREENS] + [(720, "print")]:
            for selector in (GLYPH_SELECTOR, BUG_SELECTOR):
                props = cssscan.effective(sheet, width, media).get(selector, {})
                problems += [
                    f"{media} {width}px: {selector} sets {p}" for p in EFFECT_PROPS if p in props
                ]
        report(self, "glyph effects", sorted(set(problems)))

    def test_print_hides_the_glyphs_and_screens_show_them(self):
        sheet = pagecss.page_sheet()
        problems = []
        for width, media, hidden in [(w, "screen", False) for w in SCREENS] + [
            (720, "print", True),
            (698, "print", True),
        ]:
            display = resolved(sheet, width, GLYPH_SELECTOR, "display", media)
            if (display == "none") != hidden:
                problems.append(f"{media} {width}px: glyph display is {display!r}")
        report(self, "glyphs by medium", problems)

    def test_contact_links_keep_the_focus_ring_and_motion_respects_reduced_motion(self):
        problems = []
        for rule in pagecss.page_sheet().rules:
            if ".contact" not in rule.selector:
                continue
            for prop, value, _ in rule.decls:
                if prop.startswith("outline") and re.match(r"^(none|0)\b", value.strip()):
                    problems.append(f"{rule.selector} removes the focus ring ({prop}: {value})")
                quiet = any("prefers-reduced-motion: no-preference" in q for q in rule.media)
                if prop in ("transition", "animation") and not quiet:
                    problems.append(f"{rule.selector} animates without a Reduce Motion guard")
        report(self, "contact focus and motion", problems)


if __name__ == "__main__":
    unittest.main()
