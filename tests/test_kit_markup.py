"""Self-tests for the markup helpers; they need no public/ and pass before the port exists."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from resume_kit import cloudflare as cf
from resume_kit import elements, htmlfacts, profiles, refs, trackers

ADDRESS = "a@b.co"


def edge_sample():
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Doc title</title>
<script type="application/ld+json">{{"email": "mailto:{ADDRESS}"}}</script></head>
<body><p>Mail <a href="/cdn-cgi/l/email-protection#{cf.encode_cfemail(ADDRESS, 0x2A)}" title="Email">\
<span class="__cf_email__" data-cfemail="{cf.encode_cfemail(ADDRESS, 0x51)}">[email&#160;protected]</span></a> now</p>
<script data-cfasync="false" src="/cdn-cgi/scripts/abc/cloudflare-static/email-decode.min.js"></script>
<script>(function(){{window.__CF$cv$params={{r:'x'}};}})();</script>
<script type="module" src="https://static.cloudflareinsights.com/beacon.min.js/vcd15cbe7772f49c399c6a5babf22c1241717689176015"
 integrity="sha512-abc" data-cf-beacon='{{"version":"2024.11.0","token":"fake-site-token","r":1}}' crossorigin="anonymous"></script>
</body></html>"""


class CloudflareDecodeTest(unittest.TestCase):
    def test_decode_matches_a_hand_computed_vector(self):
        # 0x2a is the key; each address byte is XORed with it.
        self.assertEqual(cf.decode_cfemail("2a4b6a48044945"), ADDRESS)

    def test_round_trip_with_any_key_and_non_ascii(self):
        for key in (0x00, 0x2A, 0xB3, 0xFF):
            for address in (ADDRESS, "jörg@example.com"):
                self.assertEqual(cf.decode_cfemail(cf.encode_cfemail(address, key)), address)

    def test_email_href_decodes_to_mailto_and_ignores_other_links(self):
        self.assertEqual(
            cf.decode_email_href("/cdn-cgi/l/email-protection#2a4b6a48044945"), f"mailto:{ADDRESS}"
        )
        self.assertIsNone(cf.decode_email_href("mailto:a@b.co"))
        self.assertIsNone(cf.decode_email_href("/about#2a4b6a48044945"))

    def test_script_classification(self):
        self.assertEqual(
            cf.classify_script({"src": "/cdn-cgi/scripts/x/rocket-loader.min.js"}, ""),
            "cloudflare-edge",
        )
        self.assertEqual(cf.classify_script({}, "window.__CF$cv$params={}"), "cloudflare-edge")
        beacon = "https://static.cloudflareinsights.com/beacon.min.js"
        self.assertEqual(cf.classify_script({"src": beacon}, ""), "cloudflare-web-analytics")
        self.assertEqual(
            cf.classify_script(
                {"src": beacon + "/vcd15cbe7772f49c399c6a5babf22c1241717689176015"}, ""
            ),
            "cloudflare-web-analytics",
        )
        self.assertIsNone(cf.classify_script({"src": "js/app.js"}, "console.log(1)"))

    def test_rocket_loader_rewrites_are_undone(self):
        attrs = {
            "type": "4d9b6ee6e9e1f2d9a8b4c5d3-text/javascript",
            "data-cf-settings": "4d9b6ee6e9e1f2d9a8b4c5d3-|49",
            "src": "a.js",
        }
        self.assertEqual(cf.clean_script_attrs(attrs), {"type": "text/javascript", "src": "a.js"})


class EdgeNormalizationTest(unittest.TestCase):
    def test_edge_mode_restores_address_text_and_mailto(self):
        facts = htmlfacts.parse(edge_sample(), edge=True)
        self.assertIn(f"Mail {ADDRESS} now", facts.visible_text())
        self.assertEqual(refs.external_hrefs(facts), {f"mailto:{ADDRESS}"})

    def test_edge_mode_for_an_anchor_that_carries_data_cfemail(self):
        html = f'<a class="__cf_email__" href="/cdn-cgi/l/email-protection" data-cfemail="{cf.encode_cfemail(ADDRESS, 0x07)}">[email&#160;protected]</a>'
        facts = htmlfacts.parse(html, edge=True)
        self.assertEqual(facts.visible_text(), ADDRESS)
        self.assertEqual(refs.external_hrefs(facts), {f"mailto:{ADDRESS}"})

    def test_raw_mode_reports_every_edge_artifact(self):
        facts = htmlfacts.parse(edge_sample(), edge=False)
        found = " | ".join(facts.all_artifacts())
        for needle in ("email obfuscation", "/cdn-cgi/", "__CF$cv$params", "[email protected]"):
            self.assertIn(needle, found)

    def test_rocket_loader_is_an_artifact_in_raw_mode_and_cleaned_in_edge_mode(self):
        html = '<script type="4d9b6ee6e9e1f2d9a8b4c5d3-text/javascript" src="app.js" data-cf-settings="x-|49"></script>'
        self.assertTrue(any("Rocket Loader" in a for a in htmlfacts.parse(html).artifacts))
        cleaned = htmlfacts.parse(html, edge=True).scripts[0]
        self.assertEqual(cleaned.attrs, {"type": "text/javascript", "src": "app.js"})
        self.assertTrue(cleaned.executable)

    def test_beacon_is_edge_noise_by_default_and_a_tracker_when_kept(self):
        facts = htmlfacts.parse(edge_sample(), edge=True)
        self.assertEqual(trackers.provider_scripts(facts, keep_cwa=False), [])
        (kept,) = trackers.provider_scripts(facts, keep_cwa=True)
        self.assertEqual(kept.url, "https://static.cloudflareinsights.com/beacon.min.js")
        self.assertEqual(kept.ids, frozenset({"fake-site-token"}))

    def test_manual_and_injected_beacon_forms_normalize_to_one_provider(self):
        manual = '<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon=\'{"token": "fake-site-token"}\'></script>'
        injected = htmlfacts.parse(edge_sample(), edge=True)
        self.assertEqual(
            trackers.provider_scripts(htmlfacts.parse(manual), keep_cwa=True),
            trackers.provider_scripts(injected, keep_cwa=True),
        )

    def test_default_flag_keeps_the_beacon_out_of_the_inventory(self):
        self.assertFalse(cf.KEEP_CLOUDFLARE_WEB_ANALYTICS)

    def test_other_providers_are_trackers_with_query_ids(self):
        html = '<script async src="https://www.googletagmanager.com/gtag/js?id=G-ABCDE12345"></script><script src="js/own.js"></script>'
        (provider,) = trackers.provider_scripts(htmlfacts.parse(html))
        self.assertEqual(provider.url, "https://www.googletagmanager.com/gtag/js")
        self.assertEqual(provider.ids, frozenset({"G-ABCDE12345"}))


class VisibleTextTest(unittest.TestCase):
    def text(self, body):
        return htmlfacts.parse(
            f"<html><head><title>T</title><style>.x{{}}</style></head><body>{body}</body></html>"
        ).visible_text()

    def test_scripts_styles_title_noscript_and_comments_are_not_visible(self):
        body = "A<script>var x=1</script><style>p{}</style><noscript>N</noscript><template>T</template><!-- c -->B"
        self.assertEqual(self.text(body), "AB")

    def test_block_boundaries_separate_words_and_inline_boundaries_do_not(self):
        self.assertEqual(self.text("<p>a</p><p>b</p>"), "a b")
        self.assertEqual(self.text("<b>Jer</b>ry"), "Jerry")
        self.assertEqual(self.text("a<br>b"), "a b")

    def test_entities_nbsp_and_unicode_normalization(self):
        self.assertEqual(self.text("a&nbsp;&nbsp;b &mdash; c&#160;d"), "a b — c d")
        self.assertEqual(self.text("é"), "é")

    def test_inline_svg_titles_stay_out_of_the_text_and_the_document_title(self):
        facts = htmlfacts.parse(
            "<title>Doc</title><body><svg><title>Icon</title><path d='M0 0'/></svg>x</body>"
        )
        self.assertEqual(facts.visible_text(), "x")
        self.assertEqual(facts.title, "Doc")

    def test_visible_lines_split_at_blocks_and_join_back_to_the_visible_text(self):
        facts = htmlfacts.parse("<body><h3>A <span>b</span></h3>\n<p>c\n d<br>e</p></body>")
        self.assertEqual(facts.visible_lines(), ["A b", "c d", "e"])
        self.assertEqual(" ".join(facts.visible_lines()), facts.visible_text())

    def test_an_unclosed_head_does_not_swallow_the_body(self):
        self.assertEqual(
            htmlfacts.parse("<head><title>T</title><body><p>hi</p>").visible_text(), "hi"
        )
        self.assertEqual(
            htmlfacts.parse("<head><title>T</title><div>hi</div>").visible_text(), "hi"
        )


class MarkupFactsTest(unittest.TestCase):
    def test_balance_errors(self):
        self.assertEqual(htmlfacts.parse("<div><p>a<p>b</div>").balance_errors, [])
        self.assertEqual(htmlfacts.parse("<ul><li>a<li>b</ul>").balance_errors, [])
        self.assertTrue(
            any(
                "never closed" in e
                for e in htmlfacts.parse("<div><span>x</div>").balance_errors
                + htmlfacts.parse("<div>").balance_errors
            )
        )
        self.assertTrue(any("stray" in e for e in htmlfacts.parse("<p>x</p></div>").balance_errors))

    def test_head_facts(self):
        html = '<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="Viewport" content="width=device-width"><title>Hi &amp; bye</title>'
        facts = htmlfacts.parse(html)
        self.assertEqual(
            (facts.doctype.lower(), facts.lang, facts.title), ("doctype html", "fr", "Hi & bye")
        )
        self.assertEqual(facts.meta("name", "viewport"), "width=device-width")

    def test_ids_classes_and_inline_style_collection(self):
        facts = htmlfacts.parse('<h1 id="top" class="a b" style="color:red"><a name="x"></a></h1>')
        self.assertEqual(facts.ids, {"top", "x"})
        self.assertEqual(facts.class_tokens, {"a", "b"})
        self.assertEqual(facts.style_attrs, [("h1", "color:red")])


class ElementPickTest(unittest.TestCase):
    HTML = (
        '<section aria-labelledby="s"><h2 id="s">S</h2><p>one <b>two</b><br>three</p></section>'
        '<p class="meta x"><span class="place">P</span> <span class="dates">D</span></p>'
        "<p>no<script>hidden()</script> script</p>"
    )

    def test_text_is_nested_block_separated_and_never_hidden(self):
        found = elements.pick(self.HTML, lambda tag, attrs, parents: tag == "p")
        self.assertEqual([e.text for e in found], ["one two three", "P D", "no script"])

    def test_classes_and_parents_select_elements(self):
        meta = elements.pick(self.HTML, lambda t, a, p: "meta" in elements.classes(a))
        self.assertEqual([(e.tag, e.text) for e in meta], [("p", "P D")])
        under = elements.pick(
            self.HTML, lambda t, a, p: bool(p) and p[-1][1].get("aria-labelledby") == "s"
        )
        self.assertEqual([e.tag for e in under], ["h2", "p"])


class ProfileLinksTest(unittest.TestCase):
    def test_contact_links_and_every_rel_me_link_count_in_any_case(self):
        html = (
            '<link rel="ME" href="https://social.example/@j"><link rel="stylesheet" href="/a.css">'
            '<address class="contact"><ul><li><a href="https://resume.chenyang.us/">site</a></li>'
            '<li><a href="https://www.linkedin.com/in/x">in</a></li></ul></address>'
            '<a rel="Me nofollow" href="//blog.example/">blog</a><a href="https://other.example/">x</a>'
        )
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text(html, encoding="utf-8")
            found = profiles.external_profiles(page)
        self.assertEqual(
            found,
            {"https://social.example/@j", "https://www.linkedin.com/in/x", "https://blog.example/"},
        )


class ReferenceKindTest(unittest.TestCase):
    def test_kind_table(self):
        cases = {
            "": "empty", "#a": "fragment", "img/a.svg": "local", "/a/b": "local", "../a": "local",
            "https://x.test/a": "external", "HTTP://x.test": "external", "//cdn.test/a.js": "external",
            "mailto:a@b.co": "other-scheme", "tel:+1": "other-scheme",
            "data:image/png;base64,AAAA": "special", "javascript:void(0)": "special",
        }  # fmt: skip
        for value, expected in cases.items():
            self.assertEqual(refs.kind(value), expected, value)

    def test_host_of(self):
        self.assertEqual(refs.host_of("https://Resume.Chenyang.us/x"), "resume.chenyang.us")
        self.assertEqual(refs.host_of("//cdn.test/a.js"), "cdn.test")
        self.assertIsNone(refs.host_of("img/a.svg"))
        self.assertIsNone(refs.host_of("mailto:a@b.co"))

    def test_srcset_candidates(self):
        self.assertEqual(refs.split_srcset("a.svg 1x, b.svg 2x"), ["a.svg", "b.svg"])
        self.assertEqual(refs.split_srcset("a.svg, b.svg"), ["a.svg", "b.svg"])
        self.assertEqual(
            refs.split_srcset("a.svg,b.svg"), ["a.svg,b.svg"]
        )  # no space: one URL, per the HTML spec
        self.assertEqual(refs.split_srcset("  a.png 100w ,\n b.png 200w "), ["a.png", "b.png"])
        self.assertEqual(refs.split_srcset(""), [])

    def test_link_normalization_treats_an_empty_path_as_root(self):
        self.assertEqual(
            refs.norm_link("https://Resume.Chenyang.US"),
            refs.norm_link("https://resume.chenyang.us/"),
        )
        self.assertNotEqual(refs.norm_link("https://a.test/x"), refs.norm_link("https://a.test/y"))

    def test_roles(self):
        def role(tag, attrs):
            return refs.role(htmlfacts.Ref(tag, "href", "x", attrs))

        self.assertEqual(role("a", {}), "navigation")
        self.assertEqual(role("link", {"rel": "stylesheet"}), "resource")
        self.assertEqual(role("link", {"rel": "shortcut icon"}), "resource")
        self.assertEqual(role("link", {"rel": "canonical"}), "metadata")
        self.assertEqual(role("link", {"rel": "preconnect"}), "origin-hint")
        self.assertEqual(role("img", {}), "resource")


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        for name in (
            "index.html",
            "about.html",
            "_headers",
            "img/icons/apple.svg",
            "docs/index.html",
            "css/site.css",
        ):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
        patcher = mock.patch.object(refs, "PUBLIC", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ok(self, value, base="."):
        found, why = refs.resolve(value, self.root / base)
        self.assertIsNotNone(found, f"{value}: {why}")
        return found.relative_to(self.root).as_posix()

    def bad(self, value, base=".", expect=""):
        found, why = refs.resolve(value, self.root / base)
        self.assertIsNone(found, value)
        self.assertIn(expect, why)

    def test_resolves_root_relative_and_relative_paths(self):
        self.assertEqual(self.ok("img/icons/apple.svg"), "img/icons/apple.svg")
        self.assertEqual(self.ok("/img/icons/apple.svg", "docs"), "img/icons/apple.svg")
        self.assertEqual(self.ok("../img/icons/apple.svg", "docs"), "img/icons/apple.svg")
        self.assertEqual(self.ok("img/icons/apple.svg?v=2#frag"), "img/icons/apple.svg")

    def test_directories_resolve_to_their_index_and_pretty_urls_to_html(self):
        self.assertEqual(self.ok("/"), "index.html")
        self.assertEqual(self.ok("docs/"), "docs/index.html")
        self.assertEqual(self.ok("docs"), "docs/index.html")
        self.assertEqual(self.ok("/about"), "about.html")

    def test_misses_are_reported(self):
        self.bad("img/icons/orange.svg", expect="no such file")
        self.bad("../../etc/passwd", "docs", expect="escapes")
        self.bad("css", expect="no such file")

    def test_case_mismatch_is_a_failure_even_on_a_case_insensitive_disk(self):
        self.bad("img/icons/Apple.svg", expect="case mismatch")
        self.bad("IMG/icons/apple.svg", expect="case mismatch")

    def test_pages_control_files_are_not_served(self):
        self.bad("/_headers", expect="control file")


if __name__ == "__main__":
    unittest.main()
