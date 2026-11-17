"""Google Analytics 4: the loader and gtag('config') use the owner's ID, with no inline script."""

import re
import unittest
from urllib.parse import parse_qs, urlsplit

from resume_kit import htmlfacts, refs
from resume_kit.common import FIXTURES, INDEX, input_problem, read_json, read_text, rel, report

LOADER_HOST, LOADER_PATH = "www.googletagmanager.com", "/gtag/js"
ID_FORMAT = re.compile(r"^G-[A-Z0-9]{8,12}$")
CONFIG_CALL = re.compile(r"""gtag\s*\(\s*(['"])config\1\s*,\s*(['"])(?P<id>[^'"]+)\2""")
JS_CALL = re.compile(r"""gtag\s*\(\s*(['"])js\1\s*,\s*new\s+Date\s*\(\s*\)\s*\)""")
GTAG_DEFINITION = re.compile(
    r"(?:function\s+gtag|(?:window\.)?gtag\s*=\s*function)\s*\(\s*\)\s*\{\s*"
    r"(?:window\.)?dataLayer\s*\.\s*push\s*\(\s*arguments\s*\)\s*;?\s*\}"
)
DATALAYER_INIT = re.compile(r"(?:window\.)?dataLayer\s*=")
ANY_ANALYTICS_ID = re.compile(r"\b(?:G-[A-Z0-9]{6,}|UA-\d+-\d+|GTM-[A-Z0-9]+|AW-\d+)\b")


def measurement_id():
    """The owner's GA4 ID from tests/fixtures/tracker.json; a missing or bad file fails loudly."""
    path = FIXTURES / "tracker.json"
    if not path.is_file():
        raise input_problem(
            "tests/fixtures/tracker.json is missing: the owner's GA4 'measurement_id' (G-XXXXXXXXXX) "
            'has not been supplied. Create {"provider": "google-analytics", "measurement_id": "G-..."}'
        )
    data = read_json(path, "GA4 settings")
    if not isinstance(data, dict) or data.get("provider") != "google-analytics":
        raise input_problem('tests/fixtures/tracker.json must have "provider": "google-analytics"')
    value = data.get("measurement_id")
    if not isinstance(value, str) or not ID_FORMAT.match(value) or len(set(value[2:])) < 3:
        raise input_problem(
            f"tests/fixtures/tracker.json 'measurement_id' {value!r} is not a real GA4 ID (G-XXXXXXXXXX)"
        )
    return value


def loaders(facts):
    found = []
    for script in facts.scripts:
        src = script.attrs.get("src", "")
        parts = urlsplit("https:" + src if src.startswith("//") else src)
        if parts.hostname == LOADER_HOST and parts.path == LOADER_PATH:
            found.append((script, parts))
    return found


def init_scripts(facts):
    """(where, text, attrs) for inline executable scripts and for same-origin scripts the page loads."""
    out = [
        ("inline <script>", s.text, s.attrs)
        for s in facts.scripts
        if s.executable and not s.attrs.get("src")
    ]
    for script in facts.scripts:
        src = script.attrs.get("src", "")
        if src and refs.kind(src) == "local":
            path, why = refs.resolve(src, INDEX.parent)
            if path is None:
                out.append((f"{src} (unresolved: {why})", "", script.attrs))
            else:
                out.append((rel(path), read_text(path, "script the page loads"), script.attrs))
    return out


class TrackerFixtureTest(unittest.TestCase):
    def test_fixture_supplies_a_real_measurement_id(self):
        self.assertRegex(measurement_id(), ID_FORMAT)


class GoogleAnalyticsTest(unittest.TestCase):
    def test_index_loads_the_gtag_loader_for_the_measurement_id(self):
        wanted = measurement_id()
        found = loaders(htmlfacts.page(INDEX))
        if not found:
            self.fail(f"index.html does not load https://{LOADER_HOST}{LOADER_PATH}?id={wanted}")
        problems = []
        for script, parts in found:
            if parts.scheme != "https":
                problems.append(f"loader '{script.attrs['src']}' is not https")
            if parse_qs(parts.query).get("id") != [wanted]:
                problems.append(
                    f"loader id is {parse_qs(parts.query).get('id')}, expected ['{wanted}']"
                )
            if "async" not in script.attrs and "defer" not in script.attrs:
                problems.append("loader blocks rendering; add async")
            if script.attrs.get("fetchpriority", "").strip().lower() != "low":
                problems.append('loader competes with the page for bandwidth; add fetchpriority="low"')
        report(self, "gtag loader", problems)

    def test_gtag_config_is_called_with_the_measurement_id(self):
        wanted = measurement_id()
        calls = {}
        for where, text, attrs in init_scripts(htmlfacts.page(INDEX)):
            for match in CONFIG_CALL.finditer(text):
                calls.setdefault(match.group("id"), []).append((where, attrs))
        if wanted not in calls:
            self.fail(
                f"no gtag('config', '{wanted}') in index.html or a same-origin script it loads; found {sorted(calls)}"
            )
        problems = [
            f"gtag('config', '{other}') uses a different ID" for other in calls if other != wanted
        ]
        for where, attrs in calls[wanted]:
            external = where != "inline <script>"
            if external and not ({"defer", "async"} & set(attrs) or attrs.get("type") == "module"):
                problems.append(f"{where} loads without defer, which blocks rendering")
        report(self, "gtag config", problems)

    def test_gtag_bootstrap_matches_googles_snippet(self):
        wanted = measurement_id()
        problems = []
        holders = [
            (w, t)
            for w, t, _ in init_scripts(htmlfacts.page(INDEX))
            if any(m.group("id") == wanted for m in CONFIG_CALL.finditer(t))
        ]
        if not holders:
            self.fail(f"no script contains gtag('config', '{wanted}')")
        for where, text in holders:
            if not DATALAYER_INIT.search(text):
                problems.append(
                    f"{where}: dataLayer is never initialised (window.dataLayer = window.dataLayer || [])"
                )
            if not GTAG_DEFINITION.search(text):
                problems.append(
                    f"{where}: needs function gtag(){{dataLayer.push(arguments);}} (an Arguments object, not an array)"
                )
            js, config = JS_CALL.search(text), CONFIG_CALL.search(text)
            if not js:
                problems.append(f"{where}: gtag('js', new Date()) is missing")
            elif config and js.start() > config.start():
                problems.append(f"{where}: gtag('js', ...) must come before gtag('config', ...)")
        report(self, "gtag bootstrap", problems)

    def test_no_other_analytics_ids_appear(self):
        wanted = measurement_id()
        texts = [read_text(INDEX, "page under test")] + [
            t for _, t, _ in init_scripts(htmlfacts.page(INDEX))
        ]
        stray = sorted({m for text in texts for m in ANY_ANALYTICS_ID.findall(text) if m != wanted})
        report(self, f"IDs other than {wanted}", stray)


if __name__ == "__main__":
    unittest.main()
