"""Self-tests for the CSS, header, SVG and analytics helpers; independent of public/."""

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_analytics_ga as ga
import test_icons as icons
import test_parity as parity
import test_responsive as responsive
import test_structure as structure
from resume_kit import cssscan, headers as hdr, hosts, htmlfacts, pagecss, refs, svgcheck
from resume_kit import redirects as rdr
from resume_kit.common import FIXTURES, read_text

SVG_OPEN = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'


class CssUrlTest(unittest.TestCase):
    def test_every_url_form_is_found_and_comments_are_ignored(self):
        css = """
        a { background: url(img/a.svg); }
        b { background: url( "img/b.svg" ); }
        c { background: url('img/c.png') }
        /* url(commented.png) */
        d { background: url(data:image/svg+xml;utf8,<svg xmlns='x'></svg>) }
        @import "extra.css";
        @import url(other.css) screen;
        e { background-image: image-set("img/e1.png" 1x, url(img/e2.png) 2x); }
        """
        found = cssscan.urls(css)
        for expected in (
            "img/a.svg",
            "img/b.svg",
            "img/c.png",
            "extra.css",
            "other.css",
            "img/e1.png",
            "img/e2.png",
        ):
            self.assertIn(expected, found)
        self.assertTrue(any(u.startswith("data:image/svg+xml") for u in found))
        self.assertNotIn("commented.png", found)

    def test_font_face_bodies_isolate_font_urls(self):
        css = '@font-face { font-family: F; src: url(fonts/f.woff2) format("woff2"); } a { background: url(x.png) }'
        bodies = cssscan.font_face_bodies(css)
        self.assertEqual([cssscan.urls(b) for b in bodies], [["fonts/f.woff2"]])


class CssParseTest(unittest.TestCase):
    def test_rules_keep_source_order_and_media_context(self):
        sheet = cssscan.parse(
            """
            .container { max-width: 100%; margin: 0 auto }
            @media (min-width: 721px) { .container { max-width: 800px } }
            @media print { .container { max-width: none } }
            @page { margin: 0.35in }
            @font-face { font-family: F; src: url(f.woff2) }
            """
        )
        self.assertEqual(
            [(r.media, r.selector) for r in sheet.rules],
            [
                ((), ".container"),
                (("(min-width: 721px)",), ".container"),
                (("print",), ".container"),
            ],
        )
        self.assertEqual(sheet.media_queries, ["(min-width: 721px)", "print"])

    def test_braces_and_semicolons_inside_strings_and_urls_do_not_split_rules(self):
        sheet = cssscan.parse(
            'a::after { content: "}{;"; width: 5px } b { background: url(data:image/png;base64,AA) ; height: 2px }'
        )
        self.assertEqual(
            [(r.selector, [d[0] for d in r.decls]) for r in sheet.rules],
            [("a::after", ["content", "width"]), ("b", ["background", "height"])],
        )

    def test_css_nesting_cascades_after_the_parent(self):
        sheet = cssscan.parse(
            ".card { width: 800px; & .title { width: 5px } @media (max-width: 600px) { width: 100% } }"
        )
        self.assertEqual(
            [(r.selector, r.media) for r in sheet.rules],
            [(".card", ()), (".card .title", ()), (".card", ("(max-width: 600px)",))],
        )
        self.assertEqual(cssscan.width_problems(sheet), [])  # the phone override wins at 390px

    def test_important_beats_a_later_normal_declaration(self):
        sheet = cssscan.parse(".a { width: 900px !important } .a { width: auto }")
        self.assertEqual(len(cssscan.width_problems(sheet)), 1)


class CssLengthAndMediaTest(unittest.TestCase):
    def test_to_px(self):
        cases = {
            "20px": 20,
            "1.25rem": 20,
            "2em": 32,
            "0": 0,
            "1in": 96,
            "72pt": 96,
            "10mm": 10 * 96 / 25.4,
        }
        for value, expected in cases.items():
            self.assertAlmostEqual(cssscan.to_px(value), expected, places=1, msg=value)
        for value in ("100%", "50vw", "auto", "calc(1px + 2px)", "min(1px, 2px)"):
            self.assertIsNone(cssscan.to_px(value), value)

    def test_width_ranges(self):
        inf = math.inf
        cases = {
            "(max-width: 480px)": (0, 480), "(min-width: 721px)": (721, inf),
            "screen and (min-width: 600px) and (max-width: 900px)": (600, 900),
            "(min-width: 48em)": (768, inf), "(max-width: 37.5rem)": (0, 600),
            "(width >= 768px)": (768, inf), "(width < 600px)": (0, 600), "(400px <= width <= 700px)": (400, 700),
            "(600px <= width)": (600, inf), "(width: 500px)": (500, 500),
            "(orientation: landscape)": (0, inf), "print": (0, inf), "(min-width: 600px) and (min-width: 700px)": (700, inf),
        }  # fmt: skip
        for alt, expected in cases.items():
            self.assertEqual(cssscan.width_range(alt), expected, alt)

    def test_phone_and_tablet_classification(self):
        cases = {
            "(max-width: 480px)": (True, False), "(max-width: 600px)": (True, False), "(width <= 600px)": (True, False),
            "(min-width: 375px)": (True, False), "(min-width: 480px)": (True, False),
            "(min-width: 600px)": (False, True), "(min-width: 721px)": (False, True), "(min-width: 481px)": (False, True),
            "(min-width: 768px) and (max-width: 1023px)": (False, True), "(max-width: 767px)": (False, True),
            "(max-width: 1024px)": (False, True), "(min-width: 1024px)": (False, False), "(min-width: 1200px)": (False, False),
        }  # fmt: skip
        for alt, (phone, tablet) in cases.items():
            lo, hi = cssscan.width_range(alt)
            self.assertEqual(
                (cssscan.phone_like(lo, hi), cssscan.tablet_like(lo, hi)), (phone, tablet), alt
            )

    def test_applies_by_width_and_media_type(self):
        self.assertFalse(cssscan.applies("(min-width: 721px)", 390))
        self.assertTrue(cssscan.applies("(min-width: 721px)", 794, "print"))
        self.assertTrue(cssscan.applies("(max-width: 480px)", 390))
        self.assertFalse(cssscan.applies("print", 390))
        self.assertTrue(cssscan.applies("print", 794, "print"))
        self.assertTrue(cssscan.applies("screen and (max-width: 600px), print", 390))
        self.assertFalse(cssscan.applies("screen and (min-width: 600px)", 794, "print"))
        self.assertTrue(cssscan.applies("not print", 390))
        self.assertTrue(cssscan.applies("", 390))

    def test_width_queries_skip_print_only_and_unbounded_queries(self):
        sheet = cssscan.parse(
            "@media print { a { color: red } } @media (prefers-reduced-motion: reduce) { a { color: red } } @media (max-width: 480px) { a { color: red } }"
        )
        self.assertEqual([q for q, _, _ in cssscan.width_queries(sheet)], ["(max-width: 480px)"])


class FixedWidthGuardTest(unittest.TestCase):
    def problems(self, css):
        return cssscan.width_problems(cssscan.parse(css))

    def test_fluid_and_scoped_widths_pass(self):
        good = [
            ".c { max-width: 100%; margin: 0 auto } @media (min-width: 721px) { .c { max-width: 800px } .w { width: 900px } }",
            ".p { width: 800px; max-width: 100% } .q { width: 800px; max-width: 360px }",
            ".p { width: 800px } @media (max-width: 600px) { .p { width: auto } }",
            ".p { width: min(800px, 100%) } .b { width: calc(100% - 2rem) } .c { width: clamp(300px, 90%, 800px) }",
            ".p { width: 800px } .p { max-width: 100% }",
            ".ok { width: 20em } .icon { width: 24px; height: 24px } .vw { width: 100vw }",
            "@media print { .p { width: 800px } }",
        ]  # fmt: skip
        for css in good:
            self.assertEqual(self.problems(css), [], css)

    def test_overflowing_widths_fail(self):
        bad = [
            ".page { width: 800px }", ".page { width: 30em }", ".page { min-width: 500px }",
            ".page { width: 120% }", ".card { @media (max-width: 600px) { width: 700px } }",
            ".page { width: 800px; max-width: none }", ".page { width: 800px; max-width: 800px }",
            ".page { inline-size: 800px }", "body { min-width: 1024px }",
        ]  # fmt: skip
        for css in bad:
            self.assertEqual(len(self.problems(css)), 1, css)

    def test_the_original_stylesheet_passes_the_width_guard_and_has_tablet_and_print_queries(self):
        sheet = cssscan.parse(read_text(FIXTURES / "original.css", "original stylesheet"))
        self.assertEqual(cssscan.width_problems(sheet), [])
        queries = cssscan.width_queries(sheet)
        self.assertTrue(any(cssscan.tablet_like(lo, hi) for _, lo, hi in queries))
        self.assertFalse(
            any(cssscan.phone_like(lo, hi) for _, lo, hi in queries)
        )  # the port must add one
        self.assertIn("print", sheet.media_queries)


class IconPolicyEvaluatorTest(unittest.TestCase):
    def test_original_css_yields_the_20_24_16_grayscale_policy(self):
        sheet = cssscan.parse(read_text(FIXTURES / "original.css", "original stylesheet"))
        size = icons.IconSizingTest._sizes
        self.assertEqual(size(sheet, 390, "screen"), {".company-icon": (20.0, 20.0, "")})
        self.assertEqual(size(sheet, 1440, "screen"), {".company-icon": (24.0, 24.0, "")})
        self.assertEqual(
            size(sheet, 794, "print"), {".company-icon": (16.0, 16.0, "grayscale(100%)")}
        )

    def test_favicon_fallback_names(self):
        for name in (
            "favicon.ico",
            "apple-touch-icon.png",
            "apple-touch-icon-180x180.png",
            "favicon-32x32.png",
        ):
            self.assertTrue(icons.is_favicon_fallback(name), name)
        for name in (
            "apple.ico",
            "favicon-32x16.png",
            "favicon-33x33.png",
            "logo.png",
            "favicon.png",
        ):
            self.assertFalse(icons.is_favicon_fallback(name), name)


MODERN_CSS = """
:root { --icon-size: 1.25rem; }
@media (width >= 721px) { :root { --icon-size: 1.5rem; } }
@media print { :root { --icon-size: 16px; } .company-icon { filter: grayscale(100%); } }
.company-icon { inline-size: var(--icon-size); block-size: var(--icon-size); margin-inline-end: 0.5rem; }
"""


class ModernCssPolicyTest(unittest.TestCase):
    def sizes(self, css, width, media="screen"):
        return icons.IconSizingTest._sizes(cssscan.parse(css), width, media)

    def test_tokens_in_root_resolve_per_media_context(self):
        expected = {390: 20.0, 720: 20.0, 721: 24.0, 1440: 24.0}
        for width, px in expected.items():
            self.assertEqual(self.sizes(MODERN_CSS, width), {".company-icon": (px, px, "")}, width)
        self.assertEqual(
            self.sizes(MODERN_CSS, 794, "print"), {".company-icon": (16.0, 16.0, "grayscale(100%)")}
        )

    def test_rem_follows_the_root_font_size_of_that_context(self):
        css = "html { font-size: 62.5% } " + MODERN_CSS
        self.assertEqual(self.sizes(css, 390), {".company-icon": (12.5, 12.5, "")})
        css = ":root { font-size: 20px } " + MODERN_CSS
        self.assertEqual(self.sizes(css, 390), {".company-icon": (25.0, 25.0, "")})

    def test_var_fallbacks_nesting_and_logical_properties(self):
        css = ".a-icon { inline-size: var(--missing, 18px); block-size: var(--b) } :root { --b: var(--c); --c: 24px }"
        self.assertEqual(self.sizes(css, 390), {".a-icon": (18.0, 24.0, "")})
        self.assertEqual(
            self.sizes(".i-icon { width: var(--nope) }", 390), {".i-icon": (None, None, "")}
        )

    def test_the_width_guard_resolves_tokens_and_rem(self):
        self.assertEqual(
            len(
                cssscan.width_problems(cssscan.parse(":root { --w: 800px } .p { width: var(--w) }"))
            ),
            1,
        )
        self.assertEqual(
            cssscan.width_problems(cssscan.parse(":root { --w: 300px } .p { width: var(--w) }")), []
        )
        self.assertEqual(
            len(
                cssscan.width_problems(
                    cssscan.parse("html { font-size: 125% } .p { width: 20rem }")
                )
            ),
            1,
        )


class PageCssTest(unittest.TestCase):
    def test_linked_files_apply_in_order_and_a_link_media_attribute_scopes_its_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "css").mkdir()
            (root / "index.html").write_text(
                '<link rel="stylesheet" href="css/a.css"><link rel="stylesheet" href="css/p.css" media="print"><style>.c{color:red}</style>',
                encoding="utf-8",
            )
            (root / "css" / "a.css").write_text(".x { width: 1px }", encoding="utf-8")
            (root / "css" / "p.css").write_text(".y { width: 2px }", encoding="utf-8")
            with mock.patch.object(refs, "PUBLIC", root):
                sheet = pagecss.page_sheet(root / "index.html")
        self.assertEqual(
            [(r.selector, r.media) for r in sheet.rules],
            [(".x", ()), (".y", ("print",)), (".c", ())],
        )
        self.assertIn("print", sheet.media_queries)

    def test_a_page_without_any_stylesheet_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "index.html").write_text("<p>no css</p>", encoding="utf-8")
            with (
                mock.patch.object(refs, "PUBLIC", root),
                self.assertRaisesRegex(AssertionError, "no stylesheet"),
            ):
                pagecss.page_sheet(root / "index.html")


class SitemapDateTest(unittest.TestCase):
    def test_lastmod_is_masked_and_validated(self):
        old, new = (
            "<url><lastmod>2026-05-27</lastmod></url>",
            "<url><lastmod> 2026-11-15 </lastmod></url>",
        )
        self.assertEqual(parity._lines(old, True), parity._lines(new, True))
        self.assertNotEqual(parity._lines(old), parity._lines(new))
        self.assertNotEqual(
            parity._lines(old, True), parity._lines("<url><loc>x</loc></url>", True)
        )
        for good in (
            "2026-11-15",
            "2026-11-15T10:00:00Z",
            "2026-11-15T10:00:00+02:00",
            "2026-11-15T10:00Z",
        ):
            self.assertRegex(good, parity.W3C_DATE)
        for bad in ("Nov 15", "2026-11-15 10:00", "15-11-2026"):
            self.assertNotRegex(bad, parity.W3C_DATE)


class HeadersParserTest(unittest.TestCase):
    GOOD = """
# comment
/*
  Strict-Transport-Security: max-age=31536000; includeSubDomains
  Content-Security-Policy: default-src 'self'; frame-ancestors 'none'
  X-Content-Type-Options: nosniff
  ! X-Frame-Options

https://:project.pages.dev/*
  X-Robots-Tag: noindex
"""

    def test_blocks_hosts_and_values(self):
        parsed = hdr.parse(self.GOOD)
        self.assertEqual(parsed.problems, [])
        first, second = parsed.rules
        self.assertEqual((first.pattern, first.host), ("/*", None))
        self.assertEqual(
            first.value("Strict-Transport-Security"), "max-age=31536000; includeSubDomains"
        )
        self.assertEqual(
            first.value("content-security-policy"), "default-src 'self'; frame-ancestors 'none'"
        )
        self.assertEqual(first.unset, ["X-Frame-Options"])
        self.assertEqual(
            (second.host, second.value("x-robots-tag")), (":project.pages.dev", "noindex")
        )

    def test_indentation_is_not_required_by_pages(self):
        (rule,) = hdr.parse("/*\nX-Frame-Options: DENY\n").rules
        self.assertEqual(rule.value("x-frame-options"), "DENY")

    def test_problems_pages_would_hit(self):
        cases = {
            "X-Frame-Options: DENY\n": "before any path",
            "/a\n": "no headers",
            "http://x.test/*\n  A: b\n": "https://",
            "https://x.test:8080/*\n  A: b\n": "ports",
            "/a\n  Name:\n": "no value",
            "/a\n  Bad Name: v\n": "bad header name",
            "/a\n  A: " + "x" * 2000 + "\n": "exceeds",
            "/a\n  A: b\n/a\n  C: d\n": "repeats",
            "/a\n  Link:<https://x.test>\n": "must be a /path",
        }
        for text, expected in cases.items():
            problems = hdr.parse(text).problems
            self.assertTrue(any(expected in p for p in problems), f"{text[:40]!r} -> {problems}")

    def test_rule_count_limit_and_duplicate_headers(self):
        many = "".join(f"/p{i}\n  A: b\n" for i in range(101))
        self.assertTrue(any("limit" in p for p in hdr.parse(many).problems))
        self.assertEqual(
            hdr.parse("/a\n  A: 1\n  a: 2\n").duplicates, ["/a: 'a' is set more than once"]
        )
        self.assertEqual(hdr.parse("/a\n  A: 1\n  a: 2\n").rules[0].value("A"), "1, 2")


class RedirectsParserTest(unittest.TestCase):
    def test_rules_comments_and_the_default_status(self):
        parsed = rdr.parse("# comment\n/a /b\n  /c /d 200 # why\n\n/e https://x.test/f 301\n")
        self.assertEqual(parsed.problems, [])
        self.assertEqual(
            [(r.source, r.target, r.status, r.line) for r in parsed.rules],
            [("/a", "/b", 302, 2), ("/c", "/d", 200, 3), ("/e", "https://x.test/f", 301, 5)],
        )

    def test_problems_pages_would_hit(self):
        cases = {
            "/a\n": "2 or 3 fields",
            "/a /b 302 /c\n": "2 or 3 fields",
            "/a /b 404\n": "status",
            "/a /b abc\n": "status",
            "https://x.test/a /b\n": "source",
            "/a b\n": "target",
            "/a https://x.test/b 200\n": "relative",
            "/a /" + "x" * 2000 + "\n": "exceeds",
        }
        for text, expected in cases.items():
            parsed = rdr.parse(text)
            self.assertTrue(
                any(expected in p for p in parsed.problems), f"{text[:40]!r} -> {parsed.problems}"
            )
            self.assertEqual(parsed.rules, [], f"{text[:40]!r} still made a rule")

    def test_a_duplicate_source_keeps_the_first_rule(self):
        parsed = rdr.parse("/a /b\n/a /c\n")
        self.assertEqual([(r.source, r.target) for r in parsed.rules], [("/a", "/b")])
        self.assertTrue(any("duplicate" in p for p in parsed.problems), parsed.problems)

    def test_rule_count_limits_count_every_rule_after_a_dynamic_one_as_dynamic(self):
        static = "".join(f"/p{i} /q\n" for i in range(2001))
        self.assertTrue(any("static" in p for p in rdr.parse(static).problems))
        dynamic = "/p/* /q\n" + "".join(f"/p{i} /q\n" for i in range(100))
        self.assertTrue(any("dynamic" in p for p in rdr.parse(dynamic).problems))
        self.assertEqual(rdr.parse("/p/:id /q\n/r /s\n").problems, [])

    def test_rules_that_loop_through_index_are_dropped(self):
        # Pages strips /index or .html with a redirect, so these would run again on their target.
        for text in ("/* /index.html 200\n", "/ /index.html 301\n", "/a/ /b/index 302\n"):
            with self.subTest(text):
                parsed = rdr.parse(text)
                self.assertEqual(parsed.rules, [])
                self.assertTrue(any("loops" in p for p in parsed.problems), parsed.problems)
        kept = "/a /index.html 301\n/* https://x.test/index.html 301\n/b/ /c/index.html?x 302\n"
        self.assertEqual(rdr.parse(kept).problems, [])

    def test_duplicates_compare_the_source_as_pages_normalizes_it(self):
        dupes = ("/404?x", "/./404", "/x/../404", "/404#f", "/%2e/404", "/404?")
        parsed = rdr.parse("/404 /a 200\n" + "".join(f"{d} /b\n" for d in dupes) + "/404/ /c\n")
        self.assertEqual([(r.source, r.line) for r in parsed.rules], [("/404", 1), ("/404/", 8)])
        self.assertEqual(len([p for p in parsed.problems if "duplicate" in p]), len(dupes))

    def test_an_https_target_needs_a_host(self):
        for target in ("https://", "https:///"):
            with self.subTest(target):
                parsed = rdr.parse(f"/a {target} 301\n")
                self.assertEqual(parsed.rules, [])
                self.assertTrue(any("target" in p for p in parsed.problems), parsed.problems)
        self.assertEqual(rdr.parse("/a https://x.test 301\n").rules[0].target, "https://x.test/")

    def test_line_length_counts_utf16_code_units_like_javascript(self):
        emoji = "\U0001f600"  # two UTF-16 code units, one Python character
        self.assertTrue(any("exceeds" in p for p in rdr.parse("/a /" + emoji * 999).problems))
        self.assertEqual(rdr.parse("/a /" + emoji * 998).problems, [])

    def test_javascript_spaces_and_number_parsing(self):
        parsed = rdr.parse("\ufeff/a\u00a0/b\u3000301.0\n/c /d \u0663\u0660\u0661\n/e /f 0x12d\n")
        self.assertEqual([(r.source, r.status) for r in parsed.rules], [("/a", 301), ("/e", 301)])
        self.assertEqual(len(parsed.problems), 1)  # Arabic-Indic digits are NaN to Number()

    def test_match_tries_exact_static_rules_then_dynamic_rules_in_order(self):
        shadowed = rdr.parse("/4* /x 301\n/404 /y 200\n")
        self.assertEqual(rdr.match(shadowed, "/404").source, "/4*")
        static_first = rdr.parse("/404 /y 200\n/4* /x 301\n")
        self.assertEqual(rdr.match(static_first, "/404").source, "/404")
        later = rdr.parse("/p/:id /q\n/404 /y 200\n/:page /z\n")
        self.assertTrue(later.rules[1].dynamic)  # below a dynamic rule, a plain path waits its turn
        self.assertEqual(rdr.match(later, "/404").source, "/404")
        self.assertEqual(rdr.match(later, "/p/7").source, "/p/:id")
        self.assertEqual(rdr.match(later, "/x").source, "/:page")
        self.assertIsNone(rdr.match(later, "/a/b"))  # a placeholder never spans a slash
        self.assertIsNone(rdr.match(rdr.parse("/*/* /q\n/:a/:a /r\n"), "/a/b"))  # JS rejects both


class CspTest(unittest.TestCase):
    def test_policies_and_fallback_chain(self):
        one, two = hdr.parse_csp(
            "default-src 'self'; img-src 'self' data:; script-src 'self' https://x.test, default-src 'none'"
        )
        self.assertEqual(hdr.effective(one, "script-src-elem"), ["'self'", "https://x.test"])
        self.assertEqual(hdr.effective(one, "font-src"), ["'self'"])
        self.assertEqual(hdr.effective(one, "style-src-attr"), ["'self'"])
        self.assertEqual(hdr.effective(two, "img-src"), ["'none'"])
        self.assertIsNone(hdr.effective({"img-src": ["'self'"]}, "script-src"))

    def test_source_matching(self):
        cases = [
            (["'self'"], None, True), (["'none'"], None, False), (["https:"], None, True),
            (["https://www.googletagmanager.com"], "https://www.googletagmanager.com/gtag/js?id=1", True),
            (["https://*.google-analytics.com"], "https://region1.google-analytics.com/g/collect", True),
            (["https://*.google-analytics.com"], "https://google-analytics.com/x", False),
            (["www.example.com"], "https://www.example.com/a", True), (["http://a.test"], "https://a.test/", True),
            (["https://a.test:8443"], "https://a.test/", False), (["https://a.test:*"], "https://a.test:99/", True),
            (["https://a.test/js/"], "https://a.test/js/x.js", True), (["https://a.test/js/x.js"], "https://a.test/js/y.js", False),
            (["data:"], "data:image/png;base64,AA", True), (["'self'"], "data:image/png;base64,AA", False),
            (["*"], "https://x.test/", True), (["*"], "data:image/png;base64,AA", False), (["https:"], "https://x.test/", True),
            (["'self'", "'sha256-abc'"], "https://x.test/", False), (None, "https://x.test/", True),
        ]  # fmt: skip
        for sources, url, expected in cases:
            self.assertEqual(hdr.allows(sources, url), expected, f"{sources} {url}")

    def test_inline_code_needs_a_hash_or_unsafe_inline(self):
        text = "console.log(1)"
        digest = hdr.hash_source(text)
        self.assertTrue(digest.startswith("'sha256-"))
        self.assertTrue(hdr.inline_allowed(["'self'", digest], text))
        self.assertFalse(hdr.inline_allowed(["'self'"], text))
        self.assertTrue(hdr.inline_allowed(["'unsafe-inline'"], text))
        self.assertFalse(
            hdr.inline_allowed(["'unsafe-inline'", hdr.hash_source("other")], text)
        )  # hash present: unsafe-inline ignored
        self.assertTrue(hdr.inline_allowed(["'unsafe-inline'"], "color:red", attribute=True))
        self.assertFalse(
            hdr.inline_allowed(
                ["'self'", hdr.hash_source("color:red")], "color:red", attribute=True
            )
        )
        self.assertTrue(
            hdr.inline_allowed(
                ["'self'", "'unsafe-hashes'", hdr.hash_source("color:red")],
                "color:red",
                attribute=True,
            )
        )

    def test_permissions_policy_denials(self):
        value = 'camera=(), microphone=(), geolocation=(self), fullscreen=(self "https://a.test"), payment=()'
        self.assertEqual(hdr.permissions_denied(value), {"camera", "microphone", "payment"})


class SvgInspectionTest(unittest.TestCase):
    def check(self, markup):
        return svgcheck.inspect_svg(markup.encode("utf-8")).problems

    def test_a_clean_icon_has_no_problems_and_exposes_its_viewbox(self):
        report = svgcheck.inspect_svg(f'{SVG_OPEN}<path d="M0 0h24v24H0z"/></svg>'.encode())
        self.assertEqual((report.problems, report.viewbox), ([], (0.0, 0.0, 24.0, 24.0)))

    def test_each_defect_is_named(self):
        path = '<path d="M0 0"/>'
        cases = {
            f'<svg viewBox="0 0 24 24">{path}</svg>': "namespace",
            f'<svg xmlns="http://www.w3.org/2000/svg">{path}</svg>': "viewBox",
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 0 0">{path}</svg>': "viewBox",
            f'{SVG_OPEN}<image href="#a"/>{path}</svg>': "<image>",
            f"{SVG_OPEN}<script>alert(1)</script>{path}</svg>": "<script>",
            f"{SVG_OPEN}<foreignObject>x</foreignObject>{path}</svg>": "foreignobject",
            f'{SVG_OPEN}<path d="M0 0" onload="x()"/></svg>': "event handler",
            f'{SVG_OPEN}<use href="https://x.test/a.svg#i"/>{path}</svg>': "same-document",
            f'{SVG_OPEN}<a href="javascript:alert(1)">{path}</a></svg>': "javascript:",
            f'{SVG_OPEN}<path d="M0 0" style="fill:url(data:image/png;base64,AAAA)"/></svg>': "raster",
            f"{SVG_OPEN}<style>.a{{fill:url(http://x.test/a)}}</style>{path}</svg>": "CSS url()",
            f'<!DOCTYPE svg [<!ENTITY a "b">]>{SVG_OPEN}{path}</svg>': "entities",
            f"{SVG_OPEN}</svg>": "blank",
            "<svg": "not well-formed",
        }
        for markup, expected in cases.items():
            self.assertTrue(
                any(expected in p for p in self.check(markup)),
                f"{markup[:60]} -> {self.check(markup)}",
            )

    def test_same_document_references_are_fine(self):
        self.assertEqual(
            self.check(
                f'{SVG_OPEN}<defs><path id="a" d="M0 0"/></defs><use href="#a" style="fill:url(#g)"/></svg>'
            ),
            [],
        )

    def test_viewbox_parsing(self):
        for value, expected in {
            "0 0 24 24": (0, 0, 24, 24),
            "0,0,24,24": (0, 0, 24, 24),
            " 0  0 24 24 ": (0, 0, 24, 24),
        }.items():
            self.assertEqual(svgcheck.parse_viewbox(value), expected, value)
        for value in ("0 0 24", "a b c d", "0 0 -1 5", "", None):
            self.assertIsNone(svgcheck.parse_viewbox(value), value)

    def test_png_dimensions(self):
        def png(w, h):
            return (
                svgcheck.PNG_MAGIC
                + (13).to_bytes(4, "big")
                + b"IHDR"
                + w.to_bytes(4, "big")
                + h.to_bytes(4, "big")
                + b"\x08\x06\x00\x00\x00"
            )

        self.assertEqual(svgcheck.png_size(png(96, 96)), (96, 96))
        self.assertEqual(svgcheck.png_size(png(32, 22)), (32, 22))
        self.assertIsNone(svgcheck.png_size(b"GIF89a" + b"\x00" * 30))
        self.assertIsNone(svgcheck.png_size(b""))


class HostsTest(unittest.TestCase):
    def test_wildcards_match_subdomains_only(self):
        allowed = ["static.cloudflareinsights.com", "*.google-analytics.com"]
        self.assertTrue(hosts.host_allowed("STATIC.cloudflareinsights.com", allowed))
        self.assertTrue(hosts.host_allowed("region1.google-analytics.com", allowed))
        self.assertTrue(hosts.host_allowed("a.b.google-analytics.com", allowed))
        self.assertFalse(hosts.host_allowed("google-analytics.com", allowed))
        self.assertFalse(hosts.host_allowed("evilgoogle-analytics.com", allowed))
        self.assertFalse(hosts.host_allowed("cloudflareinsights.com", allowed))

    def test_script_literals_find_hosts_but_not_comments(self):
        text = "var a='https://a.test/x'; var b=\"//cdn.test/y.js\"; // see docs.example.org for details"
        found = {(m.group("a") or m.group("b")) for m in hosts.SCRIPT_URL.finditer(text)}
        self.assertEqual(found, {"a.test", "cdn.test"})


class GoogleAnalyticsHelpersTest(unittest.TestCase):
    CANONICAL = "window.dataLayer = window.dataLayer || [];\nfunction gtag(){dataLayer.push(arguments);}\ngtag('js', new Date());\ngtag('config', 'G-ABCDE12345');"
    MINIFIED = 'window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}gtag("js",new Date());gtag("config","G-ABCDE12345");'

    def test_canonical_and_minified_snippets_match_every_pattern(self):
        for snippet in (self.CANONICAL, self.MINIFIED):
            self.assertEqual(ga.CONFIG_CALL.search(snippet).group("id"), "G-ABCDE12345")
            for pattern in (ga.GTAG_DEFINITION, ga.JS_CALL, ga.DATALAYER_INIT):
                self.assertIsNotNone(pattern.search(snippet), pattern.pattern)

    def test_broken_definitions_are_rejected(self):
        for broken in (
            "function gtag(){dataLayer.push([...arguments])}",
            "const gtag = (...args) => dataLayer.push(args);",
            "function gtag(){console.log(arguments)}",
        ):
            self.assertIsNone(ga.GTAG_DEFINITION.search(broken), broken)
        self.assertIsNotNone(
            ga.GTAG_DEFINITION.search(
                "window.gtag = function(){ window.dataLayer.push(arguments); }"
            )
        )

    def test_config_with_options_still_exposes_the_id(self):
        self.assertEqual(
            ga.CONFIG_CALL.search("gtag('config', 'G-ABCDE12345', {send_page_view: false})").group(
                "id"
            ),
            "G-ABCDE12345",
        )

    def test_other_analytics_ids_are_recognised(self):
        self.assertEqual(
            sorted(
                ga.ANY_ANALYTICS_ID.findall("UA-12345-1 GTM-ABC123 G-ABCDEF12 AW-12345 G-SHOCK")
            ),
            ["AW-12345", "G-ABCDEF12", "GTM-ABC123", "UA-12345-1"],
        )

    def check_fixture(self, content=None):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ga, "FIXTURES", Path(tmp)):
            if content is not None:
                (Path(tmp) / "tracker.json").write_text(content, encoding="utf-8")
            return ga.measurement_id()

    def test_measurement_id_loader(self):
        good = json.dumps({"provider": "google-analytics", "measurement_id": "G-3CH8BVY4VX"})
        self.assertEqual(self.check_fixture(good), "G-3CH8BVY4VX")
        with self.assertRaisesRegex(AssertionError, "measurement_id"):
            self.check_fixture(None)
        for content in (
            "not json",
            json.dumps({"provider": "plausible", "measurement_id": "G-3CH8BVY4VX"}),
            json.dumps({"provider": "google-analytics"}),
            json.dumps({"provider": "google-analytics", "measurement_id": "G-XXXXXXXXXX"}),
            json.dumps({"provider": "google-analytics", "measurement_id": "G-0000000000"}),
            json.dumps({"provider": "google-analytics", "measurement_id": "UA-12345-1"}),
            json.dumps({"provider": "google-analytics", "measurement_id": "g-3ch8bvy4vx"}),
        ):
            with self.assertRaises(AssertionError, msg=content):
                self.check_fixture(content)

    def test_the_committed_tracker_fixture_is_valid(self):
        self.assertRegex(ga.measurement_id(), ga.ID_FORMAT)


class PageHelperTest(unittest.TestCase):
    def test_viewport_parsing(self):
        self.assertEqual(
            responsive.viewport_settings("width=device-width, initial-scale=1.0"),
            {"width": "device-width", "initial-scale": "1.0"},
        )
        self.assertEqual(
            responsive.viewport_settings("width=device-width; Initial-Scale=1"),
            {"width": "device-width", "initial-scale": "1"},
        )
        self.assertEqual(responsive.viewport_settings(None), {})

    def test_word_diff_names_the_first_changes(self):
        lines = parity.word_diff("a b c d e", "a b X d")
        self.assertEqual(len(lines), 2)
        self.assertIn("original has 'c', port has 'X'", lines[0])

    def test_root_file_comparison_ignores_line_endings_and_trailing_space(self):
        self.assertEqual(parity._lines("a \r\nb\r\n\r\n"), parity._lines("a\nb"))

    def test_robots_comparison_masks_only_the_last_updated_date(self):
        old = "# Crawlers welcome. Last updated: 2026-05-27\nUser-agent: *\nAllow: /"
        new = old.replace("2026-05-27", "2026-11-16")
        self.assertEqual(parity.robots_lines(old), parity.robots_lines(new))
        changed = new.replace("Allow: /", "Disallow: /")
        self.assertNotEqual(parity.robots_lines(old), parity.robots_lines(changed))

    def test_head_signature_reads_json_ld_and_social_tags(self):
        html = (
            '<title> T </title><meta name="description" content="d"><link rel="canonical" href="https://a.test/">'
            '<meta property="og:title" content="o"><meta name="twitter:card" content="summary">'
            '<script type="application/ld+json">{"b": 1, "a": 2}</script>'
        )
        signature = parity.head_signature(htmlfacts.parse(html))
        self.assertEqual(signature["title"], "T")
        self.assertEqual(signature["open graph"], {"og:title": "o"})
        self.assertEqual(signature["twitter"], {"twitter:card": "summary"})
        self.assertEqual(signature["json-ld"], ['{"a": 2, "b": 1}'])

    def check_page(self, html):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.html"
            path.write_text(html, encoding="utf-8")
            return structure.basics(path)

    def test_structure_basics(self):
        good = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>T</title></head><body><p>x</p></body></html>'
        self.assertEqual(self.check_page(good), [])
        self.assertTrue(
            any("doctype" in p for p in self.check_page(good.replace("<!doctype html>", "")))
        )
        self.assertTrue(any("lang" in p for p in self.check_page(good.replace(' lang="en"', ""))))
        self.assertTrue(
            any("charset" in p for p in self.check_page(good.replace("utf-8", "latin1")))
        )
        self.assertTrue(
            any(
                "1024" in p
                for p in self.check_page(good.replace("<head>", "<head><!--" + "x" * 1100 + "-->"))
            )
        )
        self.assertTrue(
            any(
                "viewport" in p
                for p in self.check_page(
                    good.replace('<meta name="viewport" content="width=device-width">', "")
                )
            )
        )
        self.assertTrue(
            any(
                "title" in p
                for p in self.check_page(good.replace("<title>T</title>", "<title> </title>"))
            )
        )
        self.assertTrue(
            any("<div>" in p for p in self.check_page(good.replace("<p>x</p>", "<div>x")))
        )


if __name__ == "__main__":
    unittest.main()
