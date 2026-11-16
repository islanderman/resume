"""Cache busting: files in public/css, js and img are cached for a year, so every URL to one carries
?v=<first 8 hex of its sha256>; a changed file without a new ?v= fails here instead of going stale."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from resume_kit import cssscan, htmlfacts, refs
from resume_kit import headers as hdr
from resume_kit.common import HEADERS_FILE, PUBLIC, public_files, read_text, rel, report

IMMUTABLE = "public, max-age=31536000, immutable"
FOLDERS = ("css", "js", "img")
VERSION_LEN = 8


def version_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:VERSION_LEN]


def in_immutable_folder(path):
    parts = Path(path).resolve().relative_to(PUBLIC.resolve()).parts
    return len(parts) > 1 and parts[0] in FOLDERS


def references():
    """(where, url, file) for every local HTML or CSS URL in public/ that resolves to a file."""
    found = []
    for page in public_files(".html", ".htm"):
        for item in refs.html_refs(htmlfacts.page(page)):
            if item.role in ("resource", "navigation") and refs.kind(item.value) == "local":
                target, _ = refs.resolve(item.value, page.parent)
                if target is not None:
                    found.append((f"{rel(page)} {item.where}", item.value, target))
    for sheet in public_files(".css"):
        for url in cssscan.urls(read_text(sheet, "stylesheet")):
            if refs.kind(url) == "local":
                target, _ = refs.resolve(url, sheet.parent)
                if target is not None:
                    found.append((f"{rel(sheet)} url()", url, target))
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


def header_rules():
    text = read_text(HEADERS_FILE, "Cloudflare Pages reads headers from public/_headers")
    return [r for r in hdr.parse(text).rules if r.host is None]


class CacheBustingTest(unittest.TestCase):
    def test_every_url_into_an_immutable_folder_carries_its_file_hash(self):
        found = [f for f in references() if in_immutable_folder(f[2])]
        if not found:
            self.fail("no page references a file in public/css, public/js or public/img")
        report(self, "missing or stale ?v= cache busters", version_problems(found))

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


if __name__ == "__main__":
    unittest.main()
