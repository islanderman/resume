"""Cloudflare Pages public/_headers: required security headers, effective values, and CSP fit."""

import re
import unittest

from resume_kit import headers as hdr
from resume_kit import htmlfacts, refs, cssscan
from resume_kit.common import HEADERS_FILE, public_files, read_text, rel, report

ONE_YEAR = 31_536_000
REQUIRED = (
    "strict-transport-security",
    "content-security-policy",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
)
# The live site denies these today (headers captured 2026-11-15); the port must not weaken them.
ORIGINAL_PERMISSION_DENIALS = {"camera", "microphone", "geolocation"}
REFERRER_TOKENS = {
    "no-referrer", "no-referrer-when-downgrade", "origin", "origin-when-cross-origin",
    "same-origin", "strict-origin", "strict-origin-when-cross-origin", "unsafe-url",
}  # fmt: skip
LEAKY_REFERRER = {"unsafe-url", "no-referrer-when-downgrade"}
SELF_ONLY_FONT_SOURCES = {"'self'", "'none'", "data:"}
# What the page needs at runtime beyond its own markup (Google's published CSP guidance for GA4,
# plus the Cloudflare Web Analytics beacon the edge injects).
ANALYTICS_RUNTIME = (
    ("script-src-elem", "https://www.googletagmanager.com/gtag/js", "Google Analytics loader"),
    ("connect-src", "https://www.google-analytics.com/g/collect", "GA4 hits"),
    ("connect-src", "https://region1.google-analytics.com/g/collect", "GA4 regional hits"),
    ("connect-src", "https://analytics.google.com/g/collect", "GA4 hits via analytics.google.com"),
    ("connect-src", "https://region1.analytics.google.com/g/collect", "GA4 regional hits"),
    ("connect-src", "https://www.googletagmanager.com/gtag/destination", "gtag destination fetch"),
    ("img-src", "https://www.google-analytics.com/g/collect", "GA4 image fallback"),
    ("img-src", "https://www.googletagmanager.com/a", "gtag image fallback"),
    (
        "script-src-elem",
        "https://static.cloudflareinsights.com/beacon.min.js",
        "edge-injected beacon",
    ),
    ("connect-src", "https://cloudflareinsights.com/cdn-cgi/rum", "edge-injected beacon reports"),
)
RESOURCE_DIRECTIVE = {
    "script": "script-src-elem", "img": "img-src", "source": "img-src", "image": "img-src",
    "input": "img-src", "iframe": "frame-src", "embed": "object-src", "object": "object-src",
    "audio": "media-src", "video": "media-src", "track": "media-src",
}  # fmt: skip
PRELOAD_AS = {
    "script": "script-src-elem",
    "style": "style-src-elem",
    "font": "font-src",
    "image": "img-src",
}


def parsed():
    return hdr.parse(read_text(HEADERS_FILE, "Cloudflare Pages reads headers from public/_headers"))


def global_rule():
    for rule in parsed().rules:
        if rule.pattern == "/*":
            return rule
    raise AssertionError(
        "public/_headers has no '/*' block; Pages applies security headers to every path through it"
    )


def policies():
    value = global_rule().value("content-security-policy")
    if not value:
        raise AssertionError("the '/*' block sets no Content-Security-Policy")
    return hdr.parse_csp(value)


class HeadersFileTest(unittest.TestCase):
    def test_file_parses_within_pages_limits(self):
        report(self, "_headers lines Pages would reject or ignore", parsed().problems)

    def test_global_block_sets_every_required_header(self):
        rule = global_rule()
        problems = [
            f"'{name}' is not set in the '/*' block"
            for name in REQUIRED
            if rule.value(name) is None
        ]
        sniff = rule.value("x-content-type-options")
        if sniff is not None and sniff.strip().lower() != "nosniff":
            problems.append(f"x-content-type-options is '{sniff}', expected 'nosniff'")
        report(self, "missing security headers", problems)

    def test_framing_is_denied(self):
        rule = global_rule()
        ancestors = [
            p.get("frame-ancestors")
            for p in hdr.parse_csp(rule.value("content-security-policy") or "")
        ]
        denied_by_csp = any(
            a is not None and [s.lower() for s in a] == ["'none'"] for a in ancestors
        )
        denied_by_xfo = (rule.value("x-frame-options") or "").strip().upper() == "DENY"
        if not (denied_by_csp or denied_by_xfo):
            self.fail(
                "neither CSP frame-ancestors 'none' nor X-Frame-Options: DENY is set (live site: SAMEORIGIN)"
            )

    def test_hsts_max_age_is_at_least_one_year(self):
        value = global_rule().value("strict-transport-security") or ""
        match = re.search(r"max-age\s*=\s*(\d+)", value, re.I)
        if not match or int(match.group(1)) < ONE_YEAR:
            self.fail(
                f"HSTS is '{value}'; max-age must be >= {ONE_YEAR} (the live site sends max-age=0, i.e. off)"
            )

    def test_csp_has_no_unsafe_script_sources(self):
        problems = []
        for policy in policies():
            sources = hdr.effective(policy, "script-src")
            if sources is None:
                problems.append("no script-src or default-src, so scripts are unrestricted")
            for token in (t.lower() for t in sources or []):
                if token in ("'unsafe-inline'", "*", "https:", "http:", "data:"):
                    problems.append(f"script sources allow {token}")
            if any("'unsafe-eval'" in [s.lower() for s in v] for v in policy.values()):
                problems.append("a directive allows 'unsafe-eval'")
            objects = hdr.effective(policy, "object-src")
            if objects is None or [s.lower() for s in objects] != ["'none'"]:
                problems.append("object-src must be 'none'")
            if "base-uri" not in policy:
                problems.append("base-uri is not set (use 'self' or 'none')")
        report(self, "CSP weaknesses", sorted(set(problems)))

    def test_fonts_are_self_hosted(self):
        problems = []
        for policy in policies():
            sources = hdr.effective(policy, "font-src")
            if sources is None:
                problems.append("font-src is unrestricted; set font-src 'self'")
            elif not {s.lower() for s in sources} <= SELF_ONLY_FONT_SOURCES:
                problems.append(f"font-src allows {sources}; fonts must be self-hosted ('self')")
        report(self, "font policy", problems)

    def test_permissions_policy_keeps_the_original_denials(self):
        denied = hdr.permissions_denied(global_rule().value("permissions-policy") or "")
        missing = sorted(ORIGINAL_PERMISSION_DENIALS - denied)
        if missing:
            self.fail(
                f"Permissions-Policy no longer denies {missing} (write camera=(), microphone=(), geolocation=())"
            )

    def test_referrer_policy_is_a_known_non_leaky_value(self):
        value = global_rule().value("referrer-policy") or ""
        tokens = [t.strip().lower() for t in value.split(",") if t.strip()]
        problems = [f"unknown token '{t}'" for t in tokens if t not in REFERRER_TOKENS]
        problems += [f"'{t}' leaks full URLs cross-origin" for t in tokens if t in LEAKY_REFERRER]
        if not tokens:
            problems.append("Referrer-Policy is empty")
        report(self, f"Referrer-Policy '{value}'", problems)

    def test_pages_dev_hosts_are_noindex(self):
        rules = [r for r in parsed().rules if r.host and r.host.endswith(".pages.dev")]
        if not rules:
            self.fail("no block for the *.pages.dev host, e.g. 'https://:project.pages.dev/*'")
        bad = [r.pattern for r in rules if "noindex" not in (r.value("x-robots-tag") or "").lower()]
        report(self, "pages.dev blocks without X-Robots-Tag: noindex", bad)

    def test_production_is_never_noindexed(self):
        problems = []
        for rule in parsed().rules:
            production = rule.pattern.startswith("/") or (
                rule.host and not rule.host.endswith(".pages.dev")
            )
            tag = (rule.value("x-robots-tag") or "").lower()
            if production and re.search(r"\b(noindex|none)\b", tag):
                problems.append(
                    f"'{rule.pattern}' sets X-Robots-Tag: {tag}, removing the real site from search"
                )
        report(self, "production would be de-indexed", problems)

    def test_no_header_is_set_twice_in_one_block(self):
        report(self, "duplicate headers (Pages joins their values with ', ')", parsed().duplicates)


def _html_pages():
    return [(p, htmlfacts.page(p)) for p in public_files(".html", ".htm")]


def _demands():
    """(directive, url or None for same-origin, where) the deployed pages need from the CSP."""
    out = []
    for path, facts in _html_pages():
        for ref in facts.refs:
            directive = RESOURCE_DIRECTIVE.get(ref.tag)
            if ref.tag == "link":
                rels = set(ref.attrs.get("rel", "").lower().split())
                if "stylesheet" in rels:
                    directive = "style-src-elem"
                elif rels & {
                    "icon",
                    "shortcut",
                    "apple-touch-icon",
                    "apple-touch-icon-precomposed",
                    "mask-icon",
                }:
                    directive = "img-src"
                elif rels & {"preload", "modulepreload"}:
                    directive = PRELOAD_AS.get(ref.attrs.get("as", "").lower())
                elif "manifest" in rels:
                    directive = "manifest-src"
            if directive is None:
                continue
            values = refs.split_srcset(ref.value) if ref.attr == "srcset" else [ref.value]
            out += [(directive, v, f"{rel(path)} <{ref.tag} {ref.attr}>") for v in values]
    for path in public_files(".css"):
        text = read_text(path, "stylesheet")
        fonts = {u for body in cssscan.font_face_bodies(text) for u in cssscan.urls(body)}
        for url in cssscan.urls(text):
            out.append(("font-src" if url in fonts else "img-src", url, rel(path)))
    result = []
    for directive, value, where in out:
        state = refs.kind(value)
        if state == "local":
            result.append((directive, None, where, value))
        elif state == "external":
            result.append(
                (directive, "https:" + value if value.startswith("//") else value, where, value)
            )
        elif state == "special" and value.lower().startswith("data:"):
            result.append((directive, value, where, value[:30]))
    return result


class CspCompatibilityTest(unittest.TestCase):
    def test_csp_allows_every_resource_the_pages_load(self):
        problems = []
        for policy in policies():
            for directive, url, where, shown in _demands():
                if not hdr.allows(hdr.effective(policy, directive), url):
                    problems.append(f"{where}: {directive} blocks '{shown}'")
        report(self, "the CSP would block page resources", sorted(set(problems)))

    def test_csp_covers_inline_scripts_and_styles(self):
        problems = []
        for policy in policies():
            for path, facts in _html_pages():
                for script in facts.scripts:
                    if script.executable and not script.attrs.get("src") and script.text.strip():
                        if not hdr.inline_allowed(
                            hdr.effective(policy, "script-src-elem"), script.text
                        ):
                            problems.append(
                                f"{rel(path)}: inline <script> is blocked (hash {hdr.hash_source(script.text)})"
                            )
                for style in facts.styles:
                    if not hdr.inline_allowed(hdr.effective(policy, "style-src-elem"), style.text):
                        problems.append(
                            f"{rel(path)}: inline <style> is blocked (hash {hdr.hash_source(style.text)})"
                        )
                for tag, value in facts.style_attrs:
                    if not hdr.inline_allowed(
                        hdr.effective(policy, "style-src-attr"), value, attribute=True
                    ):
                        problems.append(f"{rel(path)}: style='' on <{tag}> is blocked")
        report(self, "inline code the CSP would block", sorted(set(problems)))

    def test_csp_lets_analytics_run(self):
        problems = []
        for policy in policies():
            for directive, url, what in ANALYTICS_RUNTIME:
                if not hdr.allows(hdr.effective(policy, directive), url):
                    problems.append(f"{directive} blocks {url} ({what})")
        report(self, "CSP gaps that silently break analytics", sorted(set(problems)))


if __name__ == "__main__":
    unittest.main()
