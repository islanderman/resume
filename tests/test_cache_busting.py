"""Cache busting: files in public/css, js, img and fonts are cached for a year, so every URL to one
carries ?v=<first 8 hex of its sha256>; a changed file without a new ?v= fails here, not stale. A
font preload must name its @font-face URL exactly, or the browser fetches the font twice."""

import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

from resume_kit import cssscan, htmlfacts, pagecss, refs
from resume_kit import headers as hdr
from resume_kit.common import HEADERS_FILE, INDEX, PUBLIC, public_files, read_text, rel, report

IMMUTABLE = "public, max-age=31536000, immutable"
FOLDERS = ("css", "js", "img", "fonts")
VERSION_LEN = 8
SITE = "https://resume.chenyang.us/"


def version_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:VERSION_LEN]


def in_immutable_folder(path):
    parts = Path(path).resolve().relative_to(PUBLIC.resolve()).parts
    return len(parts) > 1 and parts[0] in FOLDERS


def served_url(path):
    """The URL a file in public/ is served at: the base its relative references resolve against."""
    return urljoin(SITE, Path(path).resolve().relative_to(PUBLIC.resolve()).as_posix())


def stylesheet_references():
    """(where, url, file) for every local url() in public/ stylesheets that resolves to a file."""
    found = []
    for sheet in public_files(".css"):
        for url in cssscan.urls(read_text(sheet, "stylesheet")):
            if refs.kind(url) == "local":
                target, _ = refs.resolve(url, sheet.parent)
                if target is not None:
                    found.append((f"{rel(sheet)} url()", url, target))
    return found


def references():
    """(where, url, file) for every local HTML or CSS URL in public/ that resolves to a file."""
    found = []
    for page in public_files(".html", ".htm"):
        for item in refs.html_refs(htmlfacts.page(page)):
            if item.role in ("resource", "navigation") and refs.kind(item.value) == "local":
                target, _ = refs.resolve(item.value, page.parent)
                if target is not None:
                    found.append((f"{rel(page)} {item.where}", item.value, target))
    return found + stylesheet_references()


def site_local(value):
    """Root-relative form of a site URL in metadata ('/img/a.png?v=1'), else None."""
    text = value.strip()
    parts = urlsplit(text)
    if refs.kind(text) == "external" and parts.hostname == urlsplit(SITE).hostname:
        return parts.path + (f"?{parts.query}" if parts.query else "")
    return text if refs.kind(text) == "local" and text.startswith("/") else None


def json_strings(value):
    """Every string leaf of parsed JSON."""
    if isinstance(value, dict):
        return [s for v in value.values() for s in json_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in json_strings(v)]
    return [value] if isinstance(value, str) else []


def metadata_references():
    """(where, url, file) for every <meta content> and JSON-LD URL in public/ pages naming a file.
    Crawlers and link previews cache these too, so a stale one keeps the old card or image alive."""
    found = []
    for page in public_files(".html", ".htm"):
        facts = htmlfacts.page(page)
        values = [
            (f"<meta {m.get('property') or m.get('name')}>", m["content"])
            for m in facts.metas
            if m.get("content")
        ]
        for script in facts.scripts:
            if script.json_ld:
                try:
                    data = json.loads(script.text)
                except ValueError:
                    continue  # tests/test_seo.py reports JSON-LD that does not parse
                values += [("JSON-LD", v) for v in json_strings(data)]
        for where, value in values:
            local = site_local(value)
            target = refs.resolve(local, page.parent)[0] if local else None
            if target is not None:
                found.append((f"{rel(page)} {where}", value, target))
    return found


def version_problems(found):
    """One problem per (where, url, file) whose ?v= is missing or is not the file's hash prefix."""
    problems = []
    for where, url, target in found:
        want = version_of(target)
        got = parse_qs(urlsplit(url).query).get("v")
        if got is None:
            problems.append(f"{where} '{url}' has no ?v=; append ?v={want}")
        elif got != [want]:
            problems.append(f"{where} '{url}': {rel(target)} now hashes to {want}; use ?v={want}")
    return problems


def font_faces():
    """{absolute URL: stylesheet} for every local url() inside an @font-face block in public/."""
    faces = {}
    for sheet in public_files(".css"):
        for body in cssscan.font_face_bodies(read_text(sheet, "stylesheet")):
            for url in cssscan.urls(body):
                if refs.kind(url) == "local":
                    faces[urljoin(served_url(sheet), url)] = rel(sheet)
    return faces


def font_preloads():
    """(page, attrs, absolute URL) for every <link rel="preload" as="font"> in public/ pages."""
    found = []
    for page in public_files(".html", ".htm"):
        for attrs in htmlfacts.page(page).links:
            rels = set(attrs.get("rel", "").lower().split())
            if "preload" in rels and attrs.get("as", "").strip().lower() == "font":
                href = attrs.get("href", "").strip()
                found.append((rel(page), attrs, urljoin(served_url(page), href)))
    return found


def preload_problems(preloads, faces):
    """Font preloads an @font-face fetch cannot reuse; the browser then downloads the font again."""
    problems = []
    for where, attrs, url in preloads:
        if url not in faces:
            problems.append(
                f"{where} preloads {url}, which no @font-face src resolves to byte for byte "
                f"(they name {sorted(faces) or 'nothing'})"
            )
        if attrs.get("crossorigin") is None or attrs["crossorigin"].strip().lower() not in (
            "",
            "anonymous",
        ):
            problems.append(f"{where}: fonts load in CORS mode, so the preload needs crossorigin")
        if attrs.get("type", "").strip().lower() != "font/woff2":
            problems.append(f"{where}: preload type {attrs.get('type')!r} is not 'font/woff2'")
    return problems


def header_rules():
    text = read_text(HEADERS_FILE, "Cloudflare Pages reads headers from public/_headers")
    return [r for r in hdr.parse(text).rules if r.host is None]


def pages_match(pattern, path):
    """True when a Pages _headers pattern matches `path`: '*' spans, ':name' is one segment."""
    parts = re.split(r"(\*|:[A-Za-z]\w*)", pattern)
    rx = "".join(
        ".*" if t == "*" else "[^/]+" if t.startswith(":") else re.escape(t) for t in parts
    )
    return re.fullmatch(rx, path) is not None


def stylesheet_path(page=INDEX):
    """Root-absolute path and query of the one stylesheet `page` loads, as a browser resolves it."""
    hrefs = [
        a.get("href", "").strip()
        for a in htmlfacts.page(page).links
        if "stylesheet" in a.get("rel", "").lower().split()
    ]
    if len(hrefs) != 1:
        raise AssertionError(f"{rel(page)} loads {len(hrefs)} stylesheets, expected 1")
    parts = urlsplit(urljoin(served_url(page), hrefs[0]))
    return parts.path + (f"?{parts.query}" if parts.query else "")


class CacheBustingTest(unittest.TestCase):
    def test_every_url_into_an_immutable_folder_carries_its_file_hash(self):
        found = [f for f in references() if in_immutable_folder(f[2])]
        if not found:
            self.fail("no page references a file in public/css, js, img or fonts")
        report(self, "missing or stale ?v= cache busters", version_problems(found))

    def test_every_metadata_url_into_an_immutable_folder_carries_its_file_hash(self):
        found = [f for f in metadata_references() if in_immutable_folder(f[2])]
        if not found:
            self.fail("no <meta> or JSON-LD URL names a file in public/img; og:image belongs there")
        report(self, "social and structured-data URLs without a fresh ?v=", version_problems(found))

    def test_every_stylesheet_url_carries_its_file_hash(self):
        # Any folder, not just the immutable ones: a url() is fetched by the cached stylesheet, so a
        # stale one keeps serving the old file for as long as that stylesheet stays cached.
        problems = version_problems(stylesheet_references())
        report(self, "stylesheet url() without a fresh ?v=", problems)

    def test_immutable_folders_are_cached_for_a_year(self):
        rules = {r.pattern: r for r in header_rules()}
        problems = []
        for folder in FOLDERS:
            rule = rules.get(f"/{folder}/*")
            value = rule.value("cache-control") if rule else None
            if value != IMMUTABLE:
                problems.append(f"'/{folder}/*' Cache-Control is {value!r}, expected {IMMUTABLE!r}")
        report(self, "_headers caching for versioned folders", problems)

    def test_pages_and_root_files_keep_revalidating(self):
        # Unversioned URLs (HTML, robots.txt, favicon.ico) must keep Pages' max-age=0 default.
        allowed = {f"/{folder}/*" for folder in FOLDERS}
        problems = [
            f"'{r.pattern}' sets Cache-Control: {r.value('cache-control')}"
            for r in header_rules()
            if r.value("cache-control") is not None and r.pattern not in allowed
        ]
        report(self, "Cache-Control set outside the versioned folders", problems)


class EarlyHintsTest(unittest.TestCase):
    # Pages sends the root's Link header as a 103 before the page; a stale URL preloads a dead file.
    # /index.html only redirects to /, so a Link there rides the redirect: one rule, one value.
    ROOT_PATHS = ("/", "/index.html")

    def test_home_page_hints_preload_the_stylesheet_url_the_page_loads(self):
        sheet = stylesheet_path()
        want = [("/", f"<{sheet}>; rel=preload; as=style")]
        links = [
            (r.pattern, value)
            for r in header_rules()
            if any(pages_match(r.pattern, path) for path in self.ROOT_PATHS)
            for value in r.headers.get("link", [])
        ]
        problems = [] if links == want else [f"root Link headers are {links}, expected {want}"]
        target, why = refs.resolve(sheet, PUBLIC)
        if target is None:
            problems.append(f"{sheet}: {why}")
        else:
            problems += version_problems([("_headers Link", sheet, target)])
        report(self, "Early Hints in public/_headers", problems)


def apple_system_first():
    """True when --font-sans names the Apple system font first: Apple devices skip the web font."""
    scope = cssscan.root_scope(cssscan.effective(pagecss.page_sheet(), 1440))
    first = scope.get("--font-sans", ("", False))[0].split(",")[0].strip().strip("'\"").lower()
    return first in ("-apple-system", "blinkmacsystemfont")


class FontPreloadTest(unittest.TestCase):
    def test_font_preloads_fetch_exactly_the_font_face_urls(self):
        report(self, "font preloads", preload_problems(font_preloads(), font_faces()))

    def test_web_font_is_preloaded_only_when_every_device_renders_it(self):
        # With -apple-system first, Apple devices never fetch the web font; a preload, or an Early
        # Hint built from one, would make them download it anyway.
        preloads, problems = font_preloads(), []
        if apple_system_first():
            problems = [
                f"{where} preloads {url}, which Apple devices never render"
                for where, _, url in preloads
            ]
        elif font_faces() and not any(where == rel(INDEX) for where, _, _ in preloads):
            problems = [f"{rel(INDEX)} preloads no font, so its request waits for the CSS"]
        report(self, "font preload policy", problems)


class PagesMatchSelfTest(unittest.TestCase):
    def test_splats_placeholders_and_exact_paths(self):
        cases = [
            ("/*", "/", True), ("/*", "/index.html", True), ("/", "/", True),
            ("/", "/index.html", False), ("/css/*", "/", False), ("/css/*", "/css/a.css", True),
            ("/:page/x", "/a/x", True), ("/:page/x", "/a/b/x", False), ("/a.b", "/aXb", False),
        ]  # fmt: skip
        for pattern, path, want in cases:
            with self.subTest(pattern=pattern, path=path):
                self.assertEqual(pages_match(pattern, path), want)


class VersionProblemsSelfTest(unittest.TestCase):
    def test_missing_and_stale_versions_are_reported_and_a_match_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset = Path(tmp) / "a.css"
            asset.write_bytes(b"a{color:red}")
            good = version_of(asset)
            stale = "0" * VERSION_LEN if good != "0" * VERSION_LEN else "1" * VERSION_LEN
            problems = version_problems(
                [
                    ("ok", f"a.css?v={good}", asset),
                    ("missing", "a.css", asset),
                    ("stale", f"a.css?v={stale}", asset),
                ]
            )
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(problems[0].startswith("missing") and f"?v={good}" in problems[0])
        self.assertTrue(problems[1].startswith("stale") and f"?v={good}" in problems[1])


class SiteLocalSelfTest(unittest.TestCase):
    def test_only_site_urls_and_root_paths_count_as_files(self):
        cases = [
            (SITE + "img/og/a.png?v=1", "/img/og/a.png?v=1"),
            ("https://RESUME.chenyang.us/x.png", "/x.png"),
            ("/img/a.png", "/img/a.png"),
            ("https://example.com/img/a.png", None),
            ("Jerry Yang", None),
            ("profile", None),
            ("#ffffff", None),
            ("mailto:a@b.co", None),
        ]
        for value, want in cases:
            with self.subTest(value):
                self.assertEqual(site_local(value), want)

    def test_json_strings_reach_every_nested_leaf(self):
        data = {"a": "1", "b": [{"c": "2"}, 3, None, ["4"]], "d": {"e": True}}
        self.assertEqual(json_strings(data), ["1", "2", "4"])


class PreloadProblemsSelfTest(unittest.TestCase):
    FACE = "https://resume.chenyang.us/fonts/f.woff2?v=12345678"
    GOOD = {"rel": "preload", "as": "font", "type": "font/woff2", "crossorigin": ""}

    def test_only_the_exact_url_with_crossorigin_and_the_woff2_type_passes(self):
        no_cors = {k: v for k, v in self.GOOD.items() if k != "crossorigin"}
        cases = [
            ("exact", self.GOOD, self.FACE, 0),
            ("credentialed", dict(self.GOOD, crossorigin="use-credentials"), self.FACE, 1),
            ("other version", self.GOOD, self.FACE.replace("12345678", "87654321"), 1),
            ("unversioned", self.GOOD, self.FACE.split("?")[0], 1),
            ("no crossorigin", no_cors, self.FACE, 1),
            ("other type", dict(self.GOOD, type="font/woff"), self.FACE, 1),
        ]
        for name, attrs, url, count in cases:
            with self.subTest(name):
                problems = preload_problems([(name, attrs, url)], {self.FACE: "css/x.css"})
                self.assertEqual(len(problems), count, problems)

    def test_a_relative_url_in_css_and_a_root_absolute_href_resolve_alike(self):
        css, page = served_url(PUBLIC / "css" / "x.css"), served_url(PUBLIC / "index.html")
        self.assertEqual(css, SITE + "css/x.css")
        self.assertEqual(urljoin(css, "../fonts/f.woff2?v=1"), urljoin(page, "/fonts/f.woff2?v=1"))


if __name__ == "__main__":
    unittest.main()
