"""Mobile, tablet and desktop guards: static heuristics, not a layout engine.

The no-overflow check at 390/768/1024/1440 px runs separately in a browser.
"""

import re
import unittest

from resume_kit import cssscan, elements, htmlfacts, pagecss
from resume_kit.common import INDEX, public_files, rel, report

MIN_ZOOM_CEILING = 5.0  # WCAG 1.4.4: a maximum-scale below 5 stops users from zooming text.
MEASURE_EM = (44.0, 52.0)  # Scanned bullets: about 95-100 characters, the printed line's length.
WIDE_SCREENS = (600, 768, 1024, 1440)  # Tablet and desktop; on phones the viewport sets the width.
# Contact list columns by screen width, the column's container query aside: 1 below 36em, 2 from
# 36em, so four items set 2 + 2 and the 404 page's three 2 + 1. Print sets one text line with
# generated '|' separators, so no screen layout has a separator.
CONTACT_LAYOUT = {
    320: "1", 390: "1", 575: "1", 580: "2", 600: "2", 768: "2", 1023: "2", 1024: "2", 1440: "2",
}  # fmt: skip
CONTACT_QUERIES = {"(width < 36em)"}
# One row is a container query on the column, in the contact text's own em, so it switches where
# the row fits at any default font size; a viewport query cannot know the column or the font.
CONTACT_CONTAINER = "contact"
ROW_QUERY = re.compile(rf"^{CONTACT_CONTAINER}\s*\(\s*width\s*>=\s*(\d+(?:\.\d+)?)em\s*\)$")
# Natural width of the four-item row in the contact text's em, measured in Chromium at default
# font sizes of 12-16px: SF Pro at 12px is the widest (56.43em); Noto Sans and its fallback face
# measure 56.28em. Measure it again when the contact text, glyphs or gaps change.
CONTACT_ROW_EM = 56.5
DESKTOP = 1440
PRINT_WIDTHS = (720, 698)  # Letter and A4 text width at 96dpi
SEPARATOR = ".contact li + li::before"


def viewport_settings(content):
    settings = {}
    for part in re.split(r"[,;]", content or ""):
        key, _, value = part.partition("=")
        if key.strip():
            settings[key.strip().lower()] = value.strip().lower()
    return settings


def width_queries():
    """Width-bounded @media alternatives from the stylesheets the page actually links or inlines."""
    return cssscan.width_queries(pagecss.page_sheet())


def measure_problems(sheet, widths=WIDE_SCREENS):
    """One problem per width where :root --measure-text is not an em length inside MEASURE_EM."""
    low, high = MEASURE_EM
    problems = []
    for width in widths:
        scope = cssscan.root_scope(cssscan.effective(sheet, width))
        value = scope.get("--measure-text", ("", False))[0]
        match = cssscan.LENGTH.match(value)
        if not match or match.group(2).lower() != "em":
            problems.append(f"at {width}px --measure-text is {value!r}, not an em length")
        elif not low <= float(match.group(1)) <= high:
            problems.append(f"at {width}px --measure-text is {value}, outside {low:g}em-{high:g}em")
    return problems


class ViewportTest(unittest.TestCase):
    def test_viewport_is_device_width_with_initial_scale_1(self):
        content = htmlfacts.page(INDEX).meta("name", "viewport")
        settings = viewport_settings(content)
        problems = []
        if settings.get("width") != "device-width":
            problems.append(f"width is {settings.get('width')!r}, expected 'device-width'")
        try:
            scale = float(settings.get("initial-scale", ""))
        except ValueError:
            scale = None
        if scale != 1.0:
            problems.append(f"initial-scale is {settings.get('initial-scale')!r}, expected 1")
        report(self, f"viewport '{content}'", problems)

    def test_viewport_does_not_block_zooming(self):
        settings = viewport_settings(htmlfacts.page(INDEX).meta("name", "viewport"))
        problems = []
        if settings.get("user-scalable") in ("no", "0", "false"):
            problems.append("user-scalable disables pinch zoom")
        try:
            if float(settings.get("maximum-scale", "10")) < MIN_ZOOM_CEILING:
                problems.append(
                    f"maximum-scale={settings['maximum-scale']} is below {MIN_ZOOM_CEILING}"
                )
        except ValueError:
            problems.append(f"maximum-scale={settings.get('maximum-scale')!r} is not a number")
        report(self, "zoom restrictions", problems)


class MediaQueryTest(unittest.TestCase):
    def test_css_has_a_phone_media_query(self):
        # Phone: width upper bound <= 600px, or a lower bound of 480px or less.
        if not any(cssscan.phone_like(lo, hi) for _, lo, hi in width_queries()):
            self.fail(
                "no phone-width @media query (e.g. @media (max-width: 480px)); found " + _found()
            )

    def test_css_has_a_tablet_media_query(self):
        # Tablet: lower bound 481-1023px, or an upper bound above 600px up to 1024px.
        if not any(cssscan.tablet_like(lo, hi) for _, lo, hi in width_queries()):
            self.fail(
                "no tablet-width @media query (e.g. @media (min-width: 768px)); found " + _found()
            )

    def test_print_styles_are_preserved(self):
        queries = pagecss.page_sheet().media_queries
        if not any(
            "print" in cssscan.media_types(alt) for q in queries for alt in cssscan.alternatives(q)
        ):
            self.fail("no @media print rules; the original page is tuned for printing")


def _found():
    return str([(q, lo, hi) for q, lo, hi in width_queries()] or "no width-based queries")


class FixedWidthTest(unittest.TestCase):
    def test_no_container_is_fixed_wider_than_390px_without_a_max_width_fallback(self):
        # Evaluated per selector at a 390px screen; calc()/min()/clamp() widths count as fluid.
        report(
            self, "fixed widths that overflow a phone", cssscan.width_problems(pagecss.page_sheet())
        )


class MeasureTest(unittest.TestCase):
    def test_content_column_measure_is_44_to_52em_on_tablet_and_desktop(self):
        report(self, "content column measure", measure_problems(pagecss.page_sheet()))


class MeasureProblemsSelfTest(unittest.TestCase):
    def test_only_an_em_measure_from_44_to_52_passes(self):
        cases = [("48em", 0), ("44em", 0), ("52em", 0), ("30em", 1), ("56em", 1), ("48rem", 1)]
        cases += [("864px", 1), ("calc(48em + 1px)", 1), (None, 1)]
        for value, count in cases:
            with self.subTest(value):
                css = ":root { --x: 1em }" if value is None else f":root {{ --measure-text: {value} }}"
                problems = measure_problems(cssscan.parse(css), widths=(1024,))
                self.assertEqual(len(problems), count, problems)

    def test_a_narrower_desktop_override_fails_only_from_its_breakpoint(self):
        css = ":root { --measure-text: 48em } @media (width >= 1024px) { :root { --measure-text: 30em } }"
        problems = measure_problems(cssscan.parse(css))
        self.assertEqual([p.split("px")[0] for p in problems], ["at 1024", "at 1440"], problems)



def _with_class(name):
    return lambda tag, attrs, parents: name in elements.classes(attrs)


def contact_layout(sheet, width, media="screen", container=None):
    """Of .contact ul at `width`: 'balanced' for inline items whose lines break balanced, 'row'
    for a wrapping flex row, else the grid's column count."""
    eff = cssscan.effective(sheet, width, media, container=container)
    rule = eff.get(".contact ul", {})
    display = rule.get("display", ("",))[0]
    if display == "flex":
        return "row" if rule.get("flex-wrap", ("",))[0] == "wrap" else "nowrap"
    if display == "block":
        item = eff.get(".contact li", {}).get("display", ("",))[0]
        wrap = rule.get("text-wrap", rule.get("text-wrap-style", ("",)))[0]
        return "balanced" if item.startswith("inline") and "balance" in wrap else "block"
    if display != "grid":
        return display or "unset"
    columns = rule.get("grid-template-columns", ("",))[0].strip()
    match = re.match(r"^repeat\(\s*(\d+)\s*,", columns)
    if match:
        return match.group(1)
    depth, count, gap = 0, 0, True
    for ch in columns:
        depth += (ch == "(") - (ch == ")")
        if depth == 0 and ch.isspace():
            gap = True
        elif gap:
            count, gap = count + 1, False
    return str(count)


def rem(value):
    """A rem length as a number, or None."""
    match = cssscan.LENGTH.match(value or "")
    return float(match.group(1)) if match and match.group(2) == "rem" else None


def sum_rem(value, em):
    """A calc() sum of em and rem lengths in rem, em being `em` rem; None for anything else."""
    flat = value.replace("calc(", " ").replace("(", " ").replace(")", " ")
    total = 0.0
    for term in flat.split("+"):
        match = cssscan.LENGTH.match(term)
        if not match or match.group(2) not in ("em", "rem"):
            return None
        total += float(match.group(1)) * (em if match.group(2) == "em" else 1.0)
    return total


def desktop_column_em(sheet):
    """The full column, --measure on body, in the contact text's em at the desktop width."""
    root = cssscan.root_scope(cssscan.effective(sheet, DESKTOP))

    def token(name):
        return cssscan.resolve_vars(root.get(name, ("", False))[0], root)

    base, contact = rem(token("--text-base")), rem(token("--text-contact"))
    measure = sum_rem(token("--measure"), base) if base else None
    return measure / contact if measure and contact else None


def container_of(props):
    """(name, type) that a container shorthand or its longhands declare."""
    name, _, kind = props.get("container", ("", False))[0].partition("/")
    name = props.get("container-name", (name, False))[0].strip()
    return name, props.get("container-type", (kind.strip() or "normal", False))[0].strip()


def one_row_problems(sheet):
    """Why the one-row contact layout could set a row that does not fit the column."""
    rules = [r for r in sheet.rules if r.containers and r.selector.startswith(".contact")]
    preludes = {q for r in rules for q in r.containers}
    if not rules:
        return ["no @container rule sets the contact row; a viewport query cannot see the column"]
    problems = [f"{r.selector} also applies to print" for r in rules if "screen" not in r.media]
    found = [ROW_QUERY.match(" ".join(q.split())) for q in preludes]
    if len(found) != 1 or not found[0]:
        return problems + [f"want one '{CONTACT_CONTAINER} (width >= Nem)' query, got {preludes}"]
    least = float(found[0].group(1))
    box = cssscan.effective(sheet, DESKTOP).get(".contact", {})
    if container_of(box) != (CONTACT_CONTAINER, "inline-size"):
        problems.append(f".contact is no '{CONTACT_CONTAINER}' inline-size container: {box}")
    if least < CONTACT_ROW_EM:
        problems.append(f"one row from {least:g}em, but the row needs {CONTACT_ROW_EM}em")
    column = desktop_column_em(sheet)
    if column is None or least > column:
        problems.append(f"desktops never get one row: a {column}em column, a {least:g}em query")
    inside = contact_layout(sheet, DESKTOP, container=lambda prelude: True)
    if inside != "balanced":
        problems.append(f"inside the query the list is {inside!r}; a wide font would break 3 + 1")
    return problems


class ContactRowTest(unittest.TestCase):
    def test_contact_markup_has_no_literal_or_markup_separators(self):
        problems = []
        for path in public_files(".html", ".htm"):
            for e in elements.pick_in(path, _with_class("contact")):
                if "|" in e.text:
                    problems.append(f"{rel(path)}: the contact text holds a literal '|'")
            if elements.pick_in(path, _with_class("sep")):
                problems.append(f"{rel(path)}: a .sep element is left; items are list items now")
        report(self, "contact separators in the markup", problems)

    def test_contact_columns_step_with_the_width(self):
        sheet = pagecss.page_sheet()
        problems = [
            f"{width}px: layout {contact_layout(sheet, width)!r}, expected {want!r}"
            for width, want in CONTACT_LAYOUT.items()
            if contact_layout(sheet, width) != want
        ]
        report(self, "contact list layout", problems)

    def test_one_row_only_where_the_column_fits_the_whole_row(self):
        # Old flaw: a 64em viewport query set one row while the column was still 54em wide, so a
        # 12-15px default font put LinkedIn alone on a second line. Outside the query: 2 + 2.
        report(self, "one-row contact layout", one_row_problems(pagecss.page_sheet()))

    def test_contact_columns_switch_on_the_readers_font_size(self):
        # A media query em is the reader's default font size: a larger default font keeps the
        # narrower layout until the wider one fits.
        queries = {
            " ".join(alt.split())
            for rule in pagecss.page_sheet().rules
            if rule.selector == ".contact ul"
            and any(prop in ("display", "grid-template-columns") for prop, _, _ in rule.decls)
            for query in rule.media
            for alt in cssscan.alternatives(query)
        }
        missing = sorted(CONTACT_QUERIES - queries)
        if missing:
            self.fail(f"the contact layout needs {missing}; found {sorted(queries)}")

    def test_separators_are_generated_only_for_print(self):
        sheet = pagecss.page_sheet()
        problems = []
        contexts = [(w, "screen", False) for w in CONTACT_LAYOUT] + [
            (w, "print", True) for w in PRINT_WIDTHS
        ]
        for width, media, wanted in contexts:
            content = cssscan.effective(sheet, width, media).get(SEPARATOR, {}).get("content")
            shown = bool(content) and "|" in content[0]
            if shown != wanted:
                problems.append(f"{media} {width}px: separator content is {content!r}")
        report(self, "contact separators by medium", problems)


class OneRowProblemsSelfTest(unittest.TestCase):
    TOKENS = """
        :root { --text-base: 1.125rem; --text-contact: 1rem; --icon-size: 2.5rem;
          --icon-gap: 0.875rem; --rail: calc(var(--icon-size) + var(--icon-gap));
          --measure-text: 48em; --measure: calc(var(--measure-text) + var(--rail)) }
        .contact { container: contact / inline-size }
        .contact ul { display: grid; grid-template-columns: repeat(2, minmax(0, max-content)) }
    """
    QUERY = """@container contact (width >= 57em) {
        .contact ul { display: block; text-wrap: balance }
        .contact li { display: inline-flex } }"""
    ROW = f"@media screen {{ {QUERY} }}"

    def problems(self, css):
        return one_row_problems(cssscan.parse(self.TOKENS + css))

    def test_a_balanced_row_in_a_column_query_that_fits_passes(self):
        self.assertEqual(self.problems(self.ROW), [])

    def test_the_old_viewport_query_fails(self):
        old = "@media screen and (width >= 64em) { .contact ul { display: flex; flex-wrap: wrap } }"
        self.assertTrue(any("@container" in p for p in self.problems(old)))

    def test_a_threshold_below_the_row_or_above_the_column_fails(self):
        self.assertTrue(any("needs" in p for p in self.problems(self.ROW.replace("57em", "50em"))))
        self.assertTrue(any("never" in p for p in self.problems(self.ROW.replace("57em", "60em"))))

    def test_a_greedy_row_or_a_print_leak_fails(self):
        greedy = self.ROW.replace("text-wrap: balance", "flex-wrap: wrap")
        self.assertTrue(any("3 + 1" in p for p in self.problems(greedy)))
        self.assertTrue(any("print" in p for p in self.problems(self.QUERY)))


if __name__ == "__main__":
    unittest.main()
