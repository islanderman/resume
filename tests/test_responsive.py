"""Mobile and tablet guards: static heuristics, not a layout engine.

The no-overflow check at 390/768/1024/1440 px runs separately in a browser.
"""

import re
import unittest

from resume_kit import cssscan, htmlfacts, pagecss
from resume_kit.common import INDEX, report

MIN_ZOOM_CEILING = 5.0  # WCAG 1.4.4: a maximum-scale below 5 stops users from zooming text.


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


if __name__ == "__main__":
    unittest.main()
