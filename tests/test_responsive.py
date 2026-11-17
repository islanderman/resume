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
# Contact list columns by screen width: 1 below 36em, 2 from 36em, a wrapping row from 64em. Print
# sets it as one text line with generated '|' separators, so no screen layout has a separator.
CONTACT_LAYOUT = {
    320: "1", 390: "1", 575: "1", 580: "2", 600: "2", 768: "2", 1023: "2", 1024: "row", 1440: "row",
}  # fmt: skip
CONTACT_QUERIES = {"(width < 36em)", "screen and (width >= 64em)"}
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


def contact_layout(sheet, width, media="screen"):
    """'row' for a wrapping flex row, else the grid's column count, of .contact ul at `width`."""
    rule = cssscan.effective(sheet, width, media).get(".contact ul", {})
    display = rule.get("display", ("",))[0]
    if display == "flex":
        return "row" if rule.get("flex-wrap", ("",))[0] == "wrap" else "nowrap"
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


if __name__ == "__main__":
    unittest.main()
