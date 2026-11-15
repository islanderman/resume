"""External hosts: every host a page reaches is allow-listed, uses https, and fonts stay self-hosted."""

import unittest

from resume_kit import hosts, refs
from resume_kit.common import report


class AllowListFixtureTest(unittest.TestCase):
    """The allow-list itself: these pass before the port exists."""

    def test_allow_list_is_well_formed_and_seeded(self):
        allowed = hosts.load_allowed()
        problems = [
            f"'{h}' is not a hostname or '*.host' wildcard"
            for h in allowed
            if not hosts.HOST_PATTERN.match(h)
        ]
        for needed in (
            "static.cloudflareinsights.com",
            "cloudflareinsights.com",
            "www.googletagmanager.com",
        ):
            if not hosts.host_allowed(needed, allowed):
                problems.append(f"'{needed}' must be allowed (edge beacon / Google Analytics)")
        problems += [
            f"font host '{h}' is allowed; fonts are self-hosted"
            for h in hosts.FONT_CDNS
            if hosts.host_allowed(h, allowed)
        ]
        report(self, "allowed_hosts.json", problems)


class ExternalHostsTest(unittest.TestCase):
    def test_every_external_host_is_on_the_allow_list(self):
        allowed = hosts.load_allowed()
        seen = hosts.page_external_urls()
        problems = sorted(
            {
                f"{where}: {host} ({url[:80]})"
                for where, host, url in seen
                if not hosts.host_allowed(host, allowed)
            }
        )
        report(self, "hosts missing from tests/fixtures/allowed_hosts.json", problems)

    def test_external_resources_use_https(self):
        problems = sorted(
            {
                f"{where}: {url[:80]}"
                for where, _, url in hosts.page_external_urls()
                if url.lower().startswith("http://") or url.startswith("//")
            }
        )
        report(self, "insecure or scheme-less resource URLs", problems)

    def test_fonts_are_self_hosted(self):
        problems = [
            f"{where}: {url}"
            for where, url in hosts.page_font_urls()
            if refs.kind(url) == "external"
        ]
        for where, host, _ in hosts.page_external_urls():
            if hosts.host_allowed(host, list(hosts.FONT_CDNS)):
                problems.append(f"{where}: loads from font host {host}")
        report(self, "external font loads (font-src is 'self')", sorted(set(problems)))


if __name__ == "__main__":
    unittest.main()
