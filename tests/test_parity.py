"""Parity of public/ with the mirrored original; edge-injected Cloudflare code removed at capture."""

import difflib
import json
import re
import unittest

from resume_kit import htmlfacts, refs, trackers
from resume_kit.common import FIXTURES, INDEX, PUBLIC, fixture_text, read_text, rel, report

SECTIONS = ("Professional Summary", "Work Experience", "Advisory Roles", "Education")
ROOT_FILES = ("robots.txt", "sitemap.xml", "llms.txt")
MISSING_HINT = "parity fixture; copy the mirrored original page into tests/fixtures/"
# The one intended JSON-LD edit (key: (original, port)): the 16-48 px favicon.ico is too small for
# structured data, so "image" now names the 180 px apple-touch-icon.png.
JSON_LD_CHANGES = {
    "image": (
        "https://resume.chenyang.us/favicon.ico",
        "https://resume.chenyang.us/apple-touch-icon.png",
    )
}


def original(edge=True):
    return htmlfacts.page(FIXTURES / "original.html", edge=edge)


def word_diff(expected, actual, limit=6):
    exp, act = expected.split(), actual.split()
    lines = []
    for tag, a0, a1, b0, b1 in difflib.SequenceMatcher(
        None, exp, act, autojunk=False
    ).get_opcodes():
        if tag != "equal" and len(lines) < limit:
            context = " ".join(exp[max(0, a0 - 4) : a0])
            lines.append(
                f"after '{context}': original has '{' '.join(exp[a0:a1])[:90]}', port has '{' '.join(act[b0:b1])[:90]}'"
            )
    return lines


def json_ld(facts, changes=None):
    """Parsed JSON-LD blocks; `changes` maps key -> (old, new) and rewrites only an exact old value."""
    out = []
    for script in facts.scripts:
        if script.json_ld:
            try:
                data = json.loads(script.text)
            except ValueError as exc:
                out.append(f"INVALID JSON-LD: {exc}")
                continue
            for key, (old, new) in (changes or {}).items():
                if isinstance(data, dict) and data.get(key) == old:
                    data[key] = new
            out.append(data)
    return out


def head_signature(facts, ld_changes=None):
    ld = [d if isinstance(d, str) else json.dumps(d, sort_keys=True) for d in json_ld(facts, ld_changes)]
    return {
        "title": facts.title.strip(),
        "description": facts.meta("name", "description"),
        "author": facts.meta("name", "author"),
        "canonical": facts.link_href("canonical"),
        "open graph": {
            m["property"]: m.get("content")
            for m in facts.metas
            if m.get("property", "").startswith("og:")
        },
        "twitter": {
            m["name"]: m.get("content")
            for m in facts.metas
            if m.get("name", "").startswith("twitter:")
        },
        "json-ld": sorted(ld),
    }


class OriginalFixtureTest(unittest.TestCase):
    """The fixtures themselves: these pass before the port exists."""

    def test_original_fixture_is_complete(self):
        text = fixture_text("original.html", MISSING_HINT)
        facts = original()
        visible = facts.visible_text()
        problems = [f"visible text lacks section '{s}'" for s in SECTIONS if s not in visible]
        if "</html>" not in text.lower():
            problems.append("fixture looks truncated (no </html>)")
        if len(visible) < 3000:
            problems.append(f"visible text is only {len(visible)} chars")
        report(self, "original.html", problems)

    def test_fixtures_hold_no_cloudflare_edge_code(self):
        # Edge code is stripped when a fixture is captured; it would also trip secret scanners.
        for name in ("original.html", "original_rendered.html"):
            facts = htmlfacts.page(FIXTURES / name)
            report(self, f"{name} still carries edge-injected code", facts.all_artifacts())
            self.assertEqual([s.kind for s in facts.scripts if s.kind], [], name)

    def test_original_and_browser_rendered_fixtures_agree(self):
        # original_rendered.html is Chrome's post-JS DOM of the same page: a second opinion on the text.
        rendered = htmlfacts.page(FIXTURES / "original_rendered.html")
        self.assertEqual(rendered.visible_text(), original().visible_text())
        self.assertEqual(refs.external_hrefs(rendered), refs.external_hrefs(original()))

    def test_original_has_a_plain_mailto_and_no_placeholder(self):
        facts = original()
        self.assertIn("mailto:zhenyoung@gmail.com", refs.external_hrefs(facts))
        self.assertNotIn("[email protected]", facts.visible_text())

    def test_original_has_no_site_owned_tracker(self):
        # The only analytics on the live page was Cloudflare's edge beacon, never origin code.
        self.assertEqual(trackers.provider_scripts(original(), keep_cwa=True), [])

    def test_intended_json_ld_changes_name_the_original_values(self):
        # A stale entry would silently stop pinning that key, so each old value must be in the fixture.
        blocks = [b for b in json_ld(original()) if isinstance(b, dict)]
        problems = [
            f"JSON_LD_CHANGES['{key}'] expects {old!r}; the fixture has {[b.get(key) for b in blocks]}"
            for key, (old, _) in JSON_LD_CHANGES.items()
            if not any(b.get(key) == old for b in blocks)
        ]
        report(self, "JSON_LD_CHANGES out of step with original.html", problems)


class ContentParityTest(unittest.TestCase):
    """public/index.html against the normalized original (404.html is not compared)."""

    def test_visible_text_equals_the_original(self):
        expected = original().visible_text()
        actual = htmlfacts.page(INDEX).visible_text()
        if expected != actual:
            report(
                self,
                f"visible text differs ({len(expected)} vs {len(actual)} chars)",
                word_diff(expected, actual),
            )

    def test_external_links_are_unchanged(self):
        expected, actual = (
            refs.external_hrefs(original()),
            refs.external_hrefs(htmlfacts.page(INDEX)),
        )
        problems = [f"missing from the port: {u}" for u in sorted(expected - actual)]
        problems += [f"new in the port: {u}" for u in sorted(actual - expected)]
        report(self, "https/mailto/tel links changed", problems)

    def test_original_trackers_are_preserved_unchanged(self):
        port = trackers.provider_scripts(htmlfacts.page(INDEX))
        problems = []
        for wanted in trackers.provider_scripts(original()):
            if not any(p.url == wanted.url and wanted.ids <= p.ids for p in port):
                problems.append(f"provider {wanted.url} with ids {sorted(wanted.ids)} is missing")
        report(self, "tracker scripts dropped or altered", problems)

    def test_head_metadata_is_preserved(self):
        expected = head_signature(original(), JSON_LD_CHANGES)
        actual = head_signature(htmlfacts.page(INDEX))
        problems = [
            f"{key}: original {expected[key]!r}, port {actual[key]!r}"
            for key in expected
            if expected[key] != actual[key]
        ]
        report(self, "SEO and sharing metadata changed", problems)

    def test_port_carries_no_cloudflare_edge_artifacts(self):
        # Pages does not run Email Obfuscation, so a pasted data-cfemail link would die there.
        report(
            self, "edge-injected markup copied into the port", htmlfacts.page(INDEX).all_artifacts()
        )


LASTMOD = re.compile(r"(<lastmod>)\s*([^<]*?)\s*(</lastmod>)")
W3C_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2}))?$")


def _lines(text, sitemap=False):
    """Line list with CRLF and trailing blanks ignored; a sitemap's <lastmod> value is masked."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").rstrip().split("\n")]
    return [LASTMOD.sub(r"\1DATE\3", line) for line in lines] if sitemap else lines


class RootFilesParityTest(unittest.TestCase):
    """robots.txt, sitemap.xml and llms.txt are origin-served today and must ship in public/."""

    def test_root_files_are_unchanged(self):
        # sitemap.xml may carry a new <lastmod> date; every other byte must match.
        problems = []
        for name in ROOT_FILES:
            expected = fixture_text(f"original_{name}", MISSING_HINT)
            actual = read_text(PUBLIC / name, f"the live site serves /{name}; the port must too")
            sitemap = name == "sitemap.xml"
            if _lines(expected, sitemap) != _lines(actual, sitemap):
                problems.append(f"{rel(PUBLIC / name)} differs from tests/fixtures/original_{name}")
            if sitemap:
                problems += [
                    f"<lastmod> '{d}' is not a W3C date"
                    for _, d, _ in LASTMOD.findall(actual)
                    if not W3C_DATE.match(d)
                ]
        report(self, "root files changed", problems)


if __name__ == "__main__":
    unittest.main()
