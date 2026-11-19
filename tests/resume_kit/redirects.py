"""Cloudflare Pages `_redirects` parser: a strict subset of the rules Pages enforces at deploy."""

__unittest = True  # keeps helper frames out of unittest failure reports

import re
from dataclasses import dataclass

MAX_LINE = 2000
MAX_STATIC = 2000
MAX_DYNAMIC = 100
STATUSES = frozenset({200, 301, 302, 303, 307, 308})
DEFAULT_STATUS = 302
DYNAMIC = re.compile(r"\*|:[A-Za-z]\w*")  # a splat or a :placeholder makes a rule dynamic
INLINE_COMMENT = re.compile(r"\s+#.*$")


@dataclass
class Rule:
    source: str
    target: str
    status: int
    line: int


@dataclass
class Parsed:
    rules: list
    problems: list  # each line Pages would reject or ignore


def parse(text):
    rules, problems, seen = [], [], set()
    static = dynamic = 0
    for number, raw in enumerate(text.split("\n"), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if len(line) > MAX_LINE:
            problems.append(f"line {number}: {len(line)} chars exceeds Pages' {MAX_LINE} limit")
            continue
        fields = INLINE_COMMENT.sub("", line).split()
        if len(fields) not in (2, 3):
            problems.append(f"line {number}: want 2 or 3 fields, got {len(fields)}")
            continue
        source, target = fields[0], fields[1]
        if not source.startswith("/"):
            problems.append(f"line {number}: source '{source}' must be a relative /path")
            continue
        # Pages counts every rule after the first dynamic one as dynamic too.
        if dynamic or DYNAMIC.search(source):
            dynamic += 1
            if dynamic > MAX_DYNAMIC:
                problems.append(f"line {number}: over Pages' {MAX_DYNAMIC} dynamic rules")
                break
        else:
            static += 1
            if static > MAX_STATIC:
                problems.append(f"line {number}: over Pages' {MAX_STATIC} static rules")
                continue
        if not target.startswith(("/", "https://")):
            problems.append(f"line {number}: target '{target}' must be a /path or an https:// URL")
            continue
        status_text = fields[2] if len(fields) == 3 else str(DEFAULT_STATUS)
        status = int(status_text) if status_text.isascii() and status_text.isdigit() else None
        if status not in STATUSES:
            problems.append(f"line {number}: status '{status_text}' is not in {sorted(STATUSES)}")
            continue
        if source in seen:
            problems.append(f"line {number}: duplicate rule for '{source}'; Pages keeps the first")
            continue
        seen.add(source)
        if status == 200 and not target.startswith("/"):
            problems.append(f"line {number}: a 200 rewrite needs a relative target, got '{target}'")
            continue
        rules.append(Rule(source, target, status, number))
    return Parsed(rules, problems)
