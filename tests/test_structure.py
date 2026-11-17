"""Structure of the deployed pages: index.html and 404.html carry the basics and stay CSP-friendly."""

import re
import unittest

from resume_kit import elements, htmlfacts, refs, trackers
from resume_kit.common import INDEX, PUBLIC, read_text, rel, report

NOT_FOUND = PUBLIC / "404.html"
LANG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
TRACKER_HOSTS = ("googletagmanager.com", "google-analytics.com", "cloudflareinsights.com")
# The render-critical prefix of every <head>; the stylesheet must not wait behind metadata.
HEAD_START = ["charset", "viewport", "title", "stylesheet"]


def basics(path):
    """Problems with doctype, lang, charset, viewport, title and tag balance for one page."""
    text = read_text(path, "deployed page")
    facts = htmlfacts.page(path)
    problems = []
    if text.startswith("\ufeff"):
        problems.append("starts with a byte-order mark")
    if (facts.doctype or "").lower() != "doctype html":
        problems.append(
            f"doctype is {facts.doctype!r}, expected <!doctype html> (quirks mode otherwise)"
        )
    if not LANG.match(facts.lang or ""):
        problems.append(f"<html lang> is {facts.lang!r}, expected a language tag such as 'en'")
    charsets = [m["charset"].lower() for m in facts.metas if "charset" in m]
    if charsets != ["utf-8"]:
        problems.append(f"<meta charset> values are {charsets}, expected exactly ['utf-8']")
    head = path.read_bytes()[:1024]
    if not re.search(rb"<meta[^>]+charset", head, re.I):
        problems.append("<meta charset> is not within the first 1024 bytes")
    if not (facts.meta("name", "viewport") or "").strip():
        problems.append('<meta name="viewport"> is missing or empty')
    if not facts.title.strip():
        problems.append("<title> is missing or empty")
    problems += [f"markup: {e}" for e in facts.balance_errors]
    return problems


def head_children(path):
    """Each element directly inside <head>, in page order, named by its role where it has one."""
    names = []
    picked = elements.pick_in(
        path, lambda tag, attrs, parents: bool(parents) and parents[-1][0] == "head"
    )
    for e in picked:
        if e.tag == "meta" and "charset" in e.attrs:
            names.append("charset")
        elif e.tag == "meta" and e.attrs.get("name", "").lower() == "viewport":
            names.append("viewport")
        elif e.tag == "link" and "stylesheet" in e.attrs.get("rel", "").lower().split():
            names.append("stylesheet")
        else:
            names.append(e.tag)
    return names


def inline_script_problems(path):
    facts = htmlfacts.page(path)
    return [
        f"inline <script> ({len(s.text)} chars) without src; only application/ld+json is allowed"
        for s in facts.scripts
        if not s.attrs.get("src") and not s.json_ld
    ]


class IndexStructureTest(unittest.TestCase):
    def test_index_exists_and_has_the_head_basics(self):
        report(self, f"{rel(INDEX)} structure", basics(INDEX))

    def test_index_has_no_inline_scripts_except_json_ld(self):
        htmlfacts.page(INDEX)
        report(
            self,
            "inline scripts would need 'unsafe-inline' in the CSP",
            inline_script_problems(INDEX),
        )


class NotFoundPageTest(unittest.TestCase):
    def test_404_exists_and_has_the_head_basics(self):
        report(self, f"{rel(NOT_FOUND)} structure", basics(NOT_FOUND))

    def test_404_links_home_with_a_root_absolute_href(self):
        facts = htmlfacts.page(NOT_FOUND)
        hrefs = [a.get("href", "").strip() for a in facts.anchors]
        home = ("/", "https://resume.chenyang.us/", "https://resume.chenyang.us")
        if not any(h in home for h in hrefs):
            self.fail(f"no <a href='/'> found; anchors point at {hrefs}")

    def test_404_local_references_are_root_absolute(self):
        # Pages serves this file at any missing path, so a relative URL breaks two levels down.
        facts = htmlfacts.page(NOT_FOUND)
        bad = [
            f"{i.where} '{i.value}'"
            for i in refs.html_refs(facts)
            if refs.kind(i.value) == "local" and not i.value.strip().startswith("/")
        ]
        report(self, "relative URLs in 404.html break at depth", bad)

    def test_404_resolves_every_local_reference(self):
        facts = htmlfacts.page(NOT_FOUND)
        bad = []
        for item in refs.html_refs(facts):
            if refs.kind(item.value) == "local":
                found, why = refs.resolve(item.value, NOT_FOUND.parent)
                if found is None:
                    bad.append(f"{item.where} '{item.value}': {why}")
        report(self, "404.html references that do not resolve", bad)

    def test_404_loads_no_tracker_scripts(self):
        facts = htmlfacts.page(NOT_FOUND)
        bad = [
            f"loads provider script {p.url}"
            for p in trackers.provider_scripts(facts, keep_cwa=True)
        ]
        for script in facts.scripts:
            src = script.attrs.get("src", "")
            body = script.text
            if src and refs.kind(src) == "local":
                found, _ = refs.resolve(src, NOT_FOUND.parent)
                body = found.read_text(encoding="utf-8", errors="replace") if found else ""
            if re.search(r"gtag\s*\(|dataLayer|googletagmanager|cloudflareinsights", body + src):
                bad.append(f"script '{src or 'inline'}' carries tracker code")
        report(self, "404.html must not track visitors", bad)

    def test_404_has_no_inline_scripts(self):
        report(self, "404.html inline scripts", inline_script_problems(NOT_FOUND))


class HeadOrderTest(unittest.TestCase):
    def test_head_loads_the_stylesheet_right_after_charset_viewport_and_title(self):
        # SEO metadata, JSON-LD and analytics follow; the preload scanner meets the CSS first.
        problems = []
        for path in (INDEX, NOT_FOUND):
            start = head_children(path)[: len(HEAD_START)]
            if start != HEAD_START:
                problems.append(f"{rel(path)} <head> starts {start}, expected {HEAD_START}")
        report(self, "render-critical head order", problems)

    def test_pages_preconnect_to_no_third_party_host(self):
        # A preconnect to an analytics host would compete with the stylesheet for the network.
        problems = [
            f"{rel(path)}: <link rel={a.get('rel')!r} href={a.get('href')!r}>"
            for path in (INDEX, NOT_FOUND)
            for a in htmlfacts.page(path).links
            if {"preconnect", "dns-prefetch"} & set(a.get("rel", "").lower().split())
            and refs.kind(a.get("href", "")) == "external"
        ]
        report(self, "third-party preconnects", problems)


class ColorSchemeTest(unittest.TestCase):
    def test_pages_opt_out_of_forced_dark_modes(self):
        # The design is light-only; "only" stops Android WebView and Chrome auto-dark from recoloring
        # the page and its brand logos, which a bare "light" would still allow.
        problems = []
        for path in (INDEX, NOT_FOUND):
            value = (htmlfacts.page(path).meta("name", "color-scheme") or "").split()
            if sorted(value) != ["light", "only"]:
                problems.append(f"{rel(path)}: color-scheme is {value}, expected 'only light'")
        report(self, "forced dark mode opt-out", problems)


if __name__ == "__main__":
    unittest.main()
