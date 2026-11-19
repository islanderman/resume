"""Paths, strict loaders, and the shared problem-report assertion."""

__unittest = True  # keeps helper frames out of unittest failure reports

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "public"
FIXTURES = ROOT / "tests" / "fixtures"
INDEX = PUBLIC / "index.html"
HEADERS_FILE = PUBLIC / "_headers"
REDIRECTS_FILE = PUBLIC / "_redirects"
ICON_DIR = PUBLIC / "img" / "icons"
OLD_ORIGIN_HOST = "resume.chenyang.us"


def input_problem(message):
    """AssertionError for an absent or unreadable input: unittest reports FAIL, never ERROR or SKIP."""
    return AssertionError(message)


def rel(path):
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def read_text(path, what):
    path = Path(path)
    if not path.is_file():
        raise input_problem(f"{rel(path)} is missing ({what})")
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise input_problem(f"{rel(path)} is not valid UTF-8: {exc}") from exc


def read_json(path, what):
    text = read_text(path, what)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise input_problem(f"{rel(path)} is not valid JSON: {exc}") from exc


def fixture_text(name, what="fixture"):
    return read_text(FIXTURES / name, what)


def public_files(*suffixes):
    """Every file under public/, optionally filtered by lowercase suffix; [] if public/ is absent."""
    if not PUBLIC.is_dir():
        return []
    wanted = {s.lower() for s in suffixes}
    return sorted(
        p for p in PUBLIC.rglob("*") if p.is_file() and (not wanted or p.suffix.lower() in wanted)
    )


def report(case, header, problems):
    """Fail `case` once, listing every problem; silent on an empty list."""
    if problems:
        body = "\n  - ".join(str(p) for p in problems)
        case.fail(f"{header} ({len(problems)}):\n  - {body}")
