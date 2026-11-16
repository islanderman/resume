"""IndexNow: one public key file named after its content, and a ping step that cannot fail a deploy."""

import re
import unittest

from resume_kit.common import PUBLIC, ROOT, input_problem, read_text, rel

WORKFLOW = ROOT / ".github" / "workflows" / "prb.yml"
SMOKE_STEP = "Smoke test deployment"
PING_STEP = "IndexNow ping"
# The protocol allows 8-128 letters, digits and dashes; this site uses 32 lowercase hex characters.
PROTOCOL_KEY = re.compile(r"[0-9A-Za-z-]{8,128}")
SITE_KEY = re.compile(r"[0-9a-f]{32}")
DEPLOY_JOB = re.compile(r"^ {2}deploy:\s*$")
JOB_END = re.compile(r"^ {0,2}[^\s#]")
STEP_START = re.compile(r"^ {6}- ")
STEP_NAME = re.compile(r"^ {6}- name:\s*(.+?)\s*$")
CONTINUE_ON_ERROR = re.compile(r"(?m)^ {8}continue-on-error:\s*true\s*(?:#.*)?$")


def key_files():
    """Top-level public/*.txt files whose name could be an IndexNow key."""
    return sorted(p for p in PUBLIC.glob("*.txt") if PROTOCOL_KEY.fullmatch(p.stem))


def only_key_file():
    found = key_files()
    if len(found) != 1:
        raise input_problem(
            f"public/ must hold exactly one IndexNow key file <key>.txt, found: {[rel(p) for p in found] or 'none'}"
        )
    return found[0]


def deploy_steps():
    """[(name, text)] for every step of the deploy job, in file order; stdlib has no YAML parser."""
    lines = read_text(WORKFLOW, "the PRB workflow").splitlines()
    start = next((i for i, line in enumerate(lines) if DEPLOY_JOB.match(line)), None)
    if start is None:
        raise input_problem(f"{rel(WORKFLOW)} has no deploy job")
    steps = []
    for line in lines[start + 1 :]:
        if JOB_END.match(line):
            break
        if STEP_START.match(line):
            named = STEP_NAME.match(line)
            steps.append((named.group(1) if named else None, []))
        if steps:
            steps[-1][1].append(line)
    return [(name, "\n".join(body)) for name, body in steps]


def ping_step():
    found = [text for name, text in deploy_steps() if name == PING_STEP]
    if len(found) != 1:
        raise input_problem(f"the deploy job in {rel(WORKFLOW)} must hold one '{PING_STEP}' step, found {len(found)}")
    return found[0]


class KeyFileTest(unittest.TestCase):
    def test_exactly_one_key_file(self):
        only_key_file()

    def test_name_equals_content(self):
        path = only_key_file()
        content = read_text(path, "the IndexNow key file")
        self.assertEqual(content, path.stem, f"{rel(path)} must hold its own name and nothing else, no newline")

    def test_key_is_32_lowercase_hex(self):
        path = only_key_file()
        self.assertRegex(path.stem, r"^[0-9a-f]{32}$", f"{rel(path)} is not 32 lowercase hex characters")


class PingStepTest(unittest.TestCase):
    def test_runs_after_the_smoke_test(self):
        names = [name for name, _ in deploy_steps()]
        self.assertIn(SMOKE_STEP, names, f"the deploy job in {rel(WORKFLOW)} lost its '{SMOKE_STEP}' step")
        self.assertEqual(names.count(PING_STEP), 1, f"the deploy job must hold one '{PING_STEP}' step")
        self.assertGreater(
            names.index(PING_STEP), names.index(SMOKE_STEP), f"'{PING_STEP}' must come after '{SMOKE_STEP}'"
        )

    def test_a_failed_ping_cannot_fail_the_deploy(self):
        self.assertRegex(ping_step(), CONTINUE_ON_ERROR, f"'{PING_STEP}' needs continue-on-error: true")

    def test_step_references_no_secrets(self):
        step = ping_step()
        in_expression = re.search(r"\$\{\{[^}]*\bsecrets\b", step)
        self.assertFalse(in_expression or "secrets." in step, f"'{PING_STEP}' must not reference secrets")

    def test_step_adds_no_third_party_action(self):
        self.assertNotRegex(ping_step(), r"(?m)^\s*(?:- )?uses:", f"'{PING_STEP}' must use curl, not an action")

    def test_curl_has_a_timeout(self):
        self.assertRegex(ping_step(), r"--max-time\s+\d+", f"'{PING_STEP}' needs a curl --max-time")


if __name__ == "__main__":
    unittest.main()
