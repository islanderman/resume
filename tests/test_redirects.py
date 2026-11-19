"""Cloudflare Pages public/_redirects: rules Pages accepts, and /404 answering with status 404."""

import unittest

from resume_kit import redirects as rdr
from resume_kit import refs
from resume_kit.common import PUBLIC, REDIRECTS_FILE, read_text, rel, report

NOT_FOUND_PATH = "/404"


def parsed():
    return rdr.parse(
        read_text(REDIRECTS_FILE, "Cloudflare Pages reads redirects from public/_redirects")
    )


class RedirectsFileTest(unittest.TestCase):
    def test_file_parses_within_pages_limits(self):
        report(self, "_redirects lines Pages would reject or ignore", parsed().problems)

    def test_404_is_rewritten_to_a_path_that_serves_no_file(self):
        # Pretty URLs serve 404.html at /404 with status 200. A 200 rewrite to a path with no file
        # sends /404 through Pages' not-found handling: 404.html again, now with status 404.
        rules = [r for r in parsed().rules if r.source == NOT_FOUND_PATH]
        if len(rules) != 1:
            self.fail(f"{rel(REDIRECTS_FILE)} has {len(rules)} '{NOT_FOUND_PATH}' rules, want 1")
        rule = rules[0]
        problems = []
        if rule.status != 200:
            problems.append(f"status {rule.status} redirects; a 200 rewrite answers 404 in place")
        found, _ = refs.resolve(rule.target, PUBLIC)
        if found is not None:
            problems.append(f"target {rule.target} serves {rel(found)} with status 200")
        report(self, f"the {NOT_FOUND_PATH} rewrite", problems)


if __name__ == "__main__":
    unittest.main()
