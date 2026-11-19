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


def not_found_problems(rules):
    """Why a request for /404 would not reach a 200 rewrite to a path that serves no file."""
    rule = rdr.match(rules, NOT_FOUND_PATH)
    if rule is None:
        return [f"no rule matches {NOT_FOUND_PATH}; pretty URLs serve 404.html with status 200"]
    if rule.source != NOT_FOUND_PATH:
        return [f"line {rule.line} '{rule.source}' matches {NOT_FOUND_PATH} first and shadows it"]
    problems = []
    if rule.status != 200:
        problems.append(f"status {rule.status} redirects; a 200 rewrite answers 404 in place")
    found, _ = refs.resolve(rule.target, PUBLIC)
    if found is not None:
        problems.append(f"target {rule.target} serves {rel(found)} with status 200")
    return problems


class RedirectsFileTest(unittest.TestCase):
    def test_file_parses_within_pages_limits(self):
        report(self, "_redirects lines Pages would reject or ignore", parsed().problems)

    def test_404_is_rewritten_to_a_path_that_serves_no_file(self):
        # Pretty URLs serve 404.html at /404 with status 200. A 200 rewrite to a path with no file
        # sends /404 through Pages' not-found handling: 404.html again, now with status 404.
        report(self, f"the {NOT_FOUND_PATH} rewrite", not_found_problems(parsed()))


class NotFoundRewriteSelfTest(unittest.TestCase):
    def test_an_earlier_dynamic_rule_that_shadows_the_rewrite_fails(self):
        problems = not_found_problems(rdr.parse("/4* /x 301\n/404 /__no-such-page 200\n"))
        self.assertTrue(any("shadows" in p for p in problems), problems)

    def test_the_rewrite_alone_passes_and_a_redirect_or_a_served_target_fails(self):
        self.assertEqual(not_found_problems(rdr.parse("/404 /__no-such-page 200\n")), [])
        self.assertEqual(len(not_found_problems(rdr.parse("/404 /__no-such-page 301\n"))), 1)
        self.assertEqual(len(not_found_problems(rdr.parse("/404 /404.html 200\n"))), 1)
        self.assertEqual(len(not_found_problems(rdr.parse("/a /b\n"))), 1)


if __name__ == "__main__":
    unittest.main()
