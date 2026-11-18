"""Parity of public/ with the mirrored original; edge-injected Cloudflare code removed at capture.
Wording follows the owner-approved copy edit of 2026-11-15 (fixtures/approved_copy.txt); links,
contact details, titles, companies, places, dates, metrics and technologies still match the
original. The SEO rewrite of 2026-11-16 replaced the head metadata, sitemap.xml and llms.txt on
purpose; tests/test_seo.py pins those now."""

import difflib
import json
import re
import unittest

from resume_kit import elements, htmlfacts, refs, trackers
from resume_kit.common import FIXTURES, INDEX, PUBLIC, fixture_text, read_text, rel, report

ORIGINAL = FIXTURES / "original.html"
SECTIONS = ("Professional Summary", "Work Experience", "Advisory Roles", "Education")
ROOT_FILES = ("robots.txt", "sitemap.xml", "llms.txt")
# robots.txt keeps its crawler rules byte for byte; the other two were rewritten for SEO.
PARITY_ROOT_FILES = ("robots.txt",)
MISSING_HINT = "parity fixture; copy the mirrored original page into tests/fixtures/"
# The copy changed on purpose, so text parity is against this fixture, not original.html. It holds
# one block per line; regenerate it in the same commit as an approved wording change, so its diff
# shows exactly which sentences changed.
APPROVED_COPY = "approved_copy.txt"
REGENERATE = (
    'cd tests && python3 -c "from resume_kit import htmlfacts; '
    "from resume_kit.common import INDEX; "
    'print(*htmlfacts.page(INDEX).visible_lines(), sep=chr(10))" > fixtures/approved_copy.txt'
)
# Facts are pinned to original.html: approved_copy.txt is regenerated from the page, so it cannot
# catch a changed fact. NAMES: the technologies, products, programs, employers and title the prose
# names, plus the QPS unit. A block keeps each as a set; the rewrite dropped duplicate tags.
NAMES = frozenset(
    "Go, Lua, Java, Bash, Python, PowerShell, C++, .NET Core, iOS, Symbian, QML, RVCT, CJK, mDNS, "
    "IPv6, Redis, Kafka, Snowflake, AWS, Kubernetes, Apache Calcite, Elasticsearch, Cassandra, "
    "MongoDB, Couchbase, Spring, Hibernate, Hive, Solr, LevelDB, Lucene, Mason, CI/CD, AI, Claude, "
    "Gemini, OneNote, iPhone, Nokia, Walmart.com, Visually Similar, MSI Cloud Engineering, "
    "Office Mobile, Office Mobile Shared Services, Mobile Advertising, QPS, Software Architect, "
    "Apple, Amazon, Microsoft, eBay, Yahoo!".split(", ")
)
# A figure is digits with a unit (30+, 10,000, 100M+, 10x, 200ms) or a magnitude word (millions).
FIGURE = re.compile(
    r"(?<![\w.,])\d+(?:[.,]\d+)*(?:ms|x|M)?\+?"
    r"|(?i:\b(?:hundreds|thousands|millions|billions)\b)"
)
# The SEO rewrite replaced these head entries on purpose, so head parity skips them; only the
# author and the canonical URL still match the original.
REWRITTEN = ("title", "description", "open graph", "twitter", "json-ld")
# The owner added a LinkedIn profile on 2026-11-16, as the last contact item, and a Blog link after
# it on 2026-11-18. Every other link and contact detail still matches the original.
ADDED_LINKS = frozenset({"https://www.linkedin.com/in/chenyang", "https://blog.chenyang.us/"})
ADDED_CONTACT_TEXT = "linkedin.com/in/chenyang Blog"
# Owner copy edits of 2026-11-18, as (original, approved) header facts: the internship names its
# Yahoo! team, as the 2007 job does; the AWS advisory council shows its place, as every other
# entry does.
HEADER_EDITS = (
    (
        "Technical Yahoo! Intern Yahoo! Inc.",
        "Technical Yahoo! Intern Yahoo! Search Technology Yahoo! Inc.",
    ),
    ("Amazon Web Services 2024 2025", "Amazon Web Services Seattle WA 2024 2025"),
)
MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
DATE = r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) )?\d{4}"
DATE_RANGE = re.compile(rf"({DATE})\s*[-–—]\s*({DATE}|Present)")
SPACED_EN_DASH_RANGE = re.compile(rf"^{DATE} – (?:{DATE}|Present)$")


def original(edge=True):
    return htmlfacts.page(ORIGINAL, edge=edge)


def word_diff(expected, actual, limit=6, labels=("original", "port")):
    exp, act = expected.split(), actual.split()
    lines = []
    for tag, a0, a1, b0, b1 in difflib.SequenceMatcher(
        None, exp, act, autojunk=False
    ).get_opcodes():
        if tag != "equal" and len(lines) < limit:
            context = " ".join(exp[max(0, a0 - 4) : a0])
            lines.append(
                f"after '{context}': {labels[0]} has '{' '.join(exp[a0:a1])[:90]}', "
                f"{labels[1]} has '{' '.join(act[b0:b1])[:90]}'"
            )
    return lines


def approved_copy():
    """The fixture's lines joined the way visible_text() joins blocks."""
    text = fixture_text(APPROVED_COPY, f"approved copy; generate it with: {REGENERATE}")
    return " ".join(text.split())


def json_ld(facts, changes=None, drop=()):
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
            for key in drop:
                if isinstance(data, dict):
                    data.pop(key, None)
            out.append(data)
    return out


def head_signature(facts, ld_changes=None, skip=()):
    """Head metadata to compare; `skip` drops a key from the tags and the JSON-LD alike."""
    ld = [
        d if isinstance(d, str) else json.dumps(d, sort_keys=True)
        for d in json_ld(facts, ld_changes, skip)
    ]
    signature = {
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
    for key in skip:
        signature.pop(key, None)
    return signature


def with_class(name):
    return lambda tag, attrs, parents: name in elements.classes(attrs)


def texts(path, predicate):
    return [e.text for e in elements.pick_in(path, predicate)]


def jobs(path):
    """Visible text of every .job block (jobs, the advisory role, degrees) in page order."""
    return texts(path, with_class("job"))


def job_header(text):
    """A job's title, company, place and dates: its text up to the end of its first date range."""
    match = DATE_RANGE.search(text)
    return text[: match.end()] if match else text


def header_facts(text):
    """Header words only: the dash, comma and parenthesis separators changed, no fact did."""
    text = re.sub(r"\s[-–—]\s|[(),]", " ", text)
    return " ".join(re.sub(r"(?<=\d)-(?=\d)", " ", text).split())


def approved_facts(facts):
    """An original job's header facts with the owner's HEADER_EDITS applied."""
    for old, new in HEADER_EDITS:
        facts = facts.replace(old, new)
    return facts


def date_ranges(path):
    """(start, end) of each job's first date range, whatever dash separates them."""
    return [m.groups() if m else None for m in (DATE_RANGE.search(j) for j in jobs(path))]


def figures(text):
    """Metrics `text` states, as a set: digits with a unit, and magnitude words in lower case."""
    return {f if f[0].isdigit() else f.lower() for f in FIGURE.findall(text)}


def named(text, names=NAMES):
    """The `names` that `text` mentions, each as a whole, case-sensitive word."""
    return {n for n in names if re.search(rf"(?<![\w.+]){re.escape(n)}(?![\w+])", text)}


def masthead(path):
    """The name and the title: the first two blocks of visible text."""
    return htmlfacts.page(path).visible_lines()[:2]


def prose_blocks(path):
    """(label, text) for the professional summary, then for every .job block, in page order."""
    lines = htmlfacts.page(path).visible_lines()
    heading = "Professional Summary"
    summary_text = lines[lines.index(heading) + 1] if heading in lines[:-1] else ""
    blocks = [(heading.lower(), summary_text)]
    return blocks + [(f"job {i} ({job_header(t)})", t) for i, t in enumerate(jobs(path), 1)]


def machine_date(text):
    """The <time datetime> value a visible date needs: 'May 2019' -> '2019-05', '2024' -> '2024'."""
    month, _, year = text.rpartition(" ")
    return f"{year}-{MONTHS[month]:02d}" if month in MONTHS else year


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

    def test_approved_copy_fixture_is_complete(self):
        visible = approved_copy()
        problems = [f"lacks section '{s}'" for s in SECTIONS if s not in visible]
        if len(visible) < 3000:
            problems.append(f"holds only {len(visible)} chars")
        report(self, f"tests/fixtures/{APPROVED_COPY}", problems)

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

    def test_curated_names_are_all_named_in_the_original(self):
        # A name the original never uses pins nothing, so a typo in NAMES would pass unnoticed.
        seen = set().union(*(named(text) for _, text in prose_blocks(ORIGINAL)))
        problems = [f"'{n}' is named in no summary or job block" for n in sorted(NAMES - seen)]
        report(self, "NAMES out of step with original.html", problems)


class ContentParityTest(unittest.TestCase):
    """public/index.html against the approved copy and the normalized original (not 404.html)."""

    def test_visible_text_equals_the_approved_copy(self):
        expected = approved_copy()
        actual = htmlfacts.page(INDEX).visible_text()
        if expected != actual:
            report(
                self,
                f"visible text differs from tests/fixtures/{APPROVED_COPY} ({len(expected)} vs "
                f"{len(actual)} chars); if the new wording is approved, run: {REGENERATE}",
                word_diff(expected, actual, labels=("approved copy", "port")),
            )

    def test_prose_keeps_every_metric_and_technology(self):
        # The masthead must match the original; each summary and job block must keep its figures
        # and names, so a changed fact fails here even after approved_copy.txt is regenerated.
        problems = []
        if masthead(ORIGINAL) != masthead(INDEX):
            problems.append(f"masthead: original {masthead(ORIGINAL)}, port {masthead(INDEX)}")
        old, new = prose_blocks(ORIGINAL), prose_blocks(INDEX)
        if len(old) != len(new):
            problems.append(f"{len(new)} prose blocks (summary and jobs), original has {len(old)}")
        for (label, before), (_, after) in zip(old, new):
            if not after:
                problems.append(f"{label}: the port has no such block")
                continue
            lost = figures(before) - figures(after)
            if lost:
                problems.append(
                    f"{label}: figures lost {sorted(lost)}; the port has {sorted(figures(after))}"
                )
            lost = named(before) - named(after)
            if lost:
                problems.append(f"{label}: names lost {sorted(lost)}")
        report(self, "metrics, technologies or masthead changed", problems)

    def test_external_links_are_the_original_plus_the_added_ones(self):
        expected, actual = (
            refs.external_hrefs(original()) | {refs.norm_link(u) for u in ADDED_LINKS},
            refs.external_hrefs(htmlfacts.page(INDEX)),
        )
        problems = [f"missing from the port: {u}" for u in sorted(expected - actual)]
        problems += [f"new in the port: {u}" for u in sorted(actual - expected)]
        report(self, "https/mailto/tel links changed", problems)

    def test_contact_details_are_the_original_plus_the_added_ones(self):
        # Separators are generated by CSS now, so only the details themselves are compared.
        expected = [
            " ".join(t.replace("|", " ").split()) + f" {ADDED_CONTACT_TEXT}"
            for t in texts(ORIGINAL, with_class("contact"))
        ]
        actual = texts(INDEX, with_class("contact"))
        if expected != actual:
            self.fail(f"contact block: expected {expected}, port {actual}")

    def test_job_headers_keep_titles_companies_places_and_dates(self):
        original_facts = [header_facts(job_header(j)) for j in jobs(ORIGINAL)]
        expected = [approved_facts(f) for f in original_facts]
        actual = [header_facts(job_header(j)) for j in jobs(INDEX)]
        # An owner edit must hit exactly one original header, or it pins nothing.
        problems = [
            f"owner edit {old!r} matches {n} original headers, expected 1"
            for old, _ in HEADER_EDITS
            if (n := sum(old in f for f in original_facts)) != 1
        ]
        if len(expected) != len(actual):
            problems.append(f"{len(actual)} jobs, original has {len(expected)}")
        problems += [
            f"job {i}: original '{e}', port '{a}'"
            for i, (e, a) in enumerate(zip(expected, actual), 1)
            if e != a
        ]
        report(self, "job headers changed", problems)

    def test_company_names_are_unchanged(self):
        headers = [job_header(j) for j in jobs(ORIGINAL)]
        names = texts(INDEX, with_class("org"))
        problems = []
        if len(names) != len(headers):
            problems.append(f"{len(names)} .org names for {len(headers)} original jobs")
        for i, (name, header) in enumerate(zip(names, headers), 1):
            # Bounded on both sides, so a trimmed name ("Apple Inc") does not pass as a substring.
            if not re.search(rf"(?<![\w@]){re.escape(name)}(?=[\s,]|$)", header):
                problems.append(f"job {i}: '{name}' is not a company in '{header}'")
        report(self, "company names changed", problems)

    def test_date_ranges_are_unchanged(self):
        expected, actual = date_ranges(ORIGINAL), date_ranges(INDEX)
        if expected != actual:
            self.fail(f"date ranges: original {expected}, port {actual}")

    def test_original_trackers_are_preserved_unchanged(self):
        port = trackers.provider_scripts(htmlfacts.page(INDEX))
        problems = []
        for wanted in trackers.provider_scripts(original()):
            if not any(p.url == wanted.url and wanted.ids <= p.ids for p in port):
                problems.append(f"provider {wanted.url} with ids {sorted(wanted.ids)} is missing")
        report(self, "tracker scripts dropped or altered", problems)

    def test_head_metadata_is_preserved(self):
        expected = head_signature(original(), skip=REWRITTEN)
        actual = head_signature(htmlfacts.page(INDEX), skip=REWRITTEN)
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


class DateMarkupTest(unittest.TestCase):
    """Every range is '<date> – <date or Present>' with an en dash, each date in a <time>."""

    def test_date_ranges_use_spaced_en_dashes_and_time_elements(self):
        ranges = texts(INDEX, with_class("dates"))
        times = elements.pick_in(INDEX, lambda tag, attrs, parents: tag == "time")
        problems = [] if ranges else ["no .dates element"]
        if len(ranges) != len(jobs(INDEX)):
            problems.append(f"{len(ranges)} .dates for {len(jobs(INDEX))} jobs")
        problems += [
            f"'{r}' is not two dates joined by ' – ' (U+2013 between spaces)"
            for r in ranges
            if not SPACED_EN_DASH_RANGE.match(r)
        ]
        written = [d for r in ranges for d in re.findall(DATE, r)]
        if [t.text for t in times] != written:
            problems.append(f"<time> texts {[t.text for t in times]} differ from dates {written}")
        problems += [
            f"<time datetime={t.attrs.get('datetime')!r}>{t.text}</time>: "
            f"expected {machine_date(t.text)!r}"
            for t in times
            if t.attrs.get("datetime") != machine_date(t.text)
        ]
        report(self, "date markup", problems)


LASTMOD = re.compile(r"(<lastmod>)\s*([^<]*?)\s*(</lastmod>)")
UPDATED = re.compile(r"^(#.*Last updated:\s*)\S+")
W3C_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2}))?$")


def _lines(text, sitemap=False):
    """Line list with CRLF and trailing blanks ignored; a sitemap's <lastmod> value is masked."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").rstrip().split("\n")]
    return [LASTMOD.sub(r"\1DATE\3", line) for line in lines] if sitemap else lines


def robots_lines(text):
    """_lines() with the date of robots.txt's 'Last updated:' comment masked."""
    return [UPDATED.sub(r"\1DATE", line) for line in _lines(text)]


class RootFilesParityTest(unittest.TestCase):
    """robots.txt, sitemap.xml and llms.txt are origin-served today and must ship in public/."""

    def test_root_files_ship(self):
        problems = [
            f"{rel(PUBLIC / name)} is missing or empty; the live site serves /{name}"
            for name in ROOT_FILES
            if not (PUBLIC / name).is_file() or not (PUBLIC / name).read_bytes().strip()
        ]
        report(self, "root files", problems)

    def test_robots_rules_are_unchanged(self):
        # Only the 'Last updated:' date may change; every crawler rule must match the original.
        problems = []
        for name in PARITY_ROOT_FILES:
            expected = fixture_text(f"original_{name}", MISSING_HINT)
            actual = read_text(PUBLIC / name, f"the live site serves /{name}; the port must too")
            if robots_lines(expected) != robots_lines(actual):
                problems.append(f"{rel(PUBLIC / name)} differs from tests/fixtures/original_{name}")
        report(self, "root files changed", problems)


if __name__ == "__main__":
    unittest.main()
