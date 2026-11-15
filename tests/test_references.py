"""Every local reference in public/ HTML and CSS resolves to a served file (case-exact)."""

import unittest

from resume_kit import htmlfacts, refs
from resume_kit.common import INDEX, OLD_ORIGIN_HOST, public_files, read_text, rel, report


def html_pages():
    htmlfacts.page(INDEX)  # a missing index.html fails every reference test with one clear message
    return [(p, htmlfacts.page(p)) for p in public_files(".html", ".htm")]


def css_files():
    return [(p, read_text(p, "stylesheet")) for p in public_files(".css")]


class LocalReferencesTest(unittest.TestCase):
    def test_html_references_resolve_to_files(self):
        problems = []
        for path, facts in html_pages():
            for item in refs.html_refs(facts):
                state = refs.kind(item.value)
                if state == "empty" and item.role == "resource":
                    problems.append(f"{rel(path)}: {item.where} is empty (re-requests the page)")
                elif state == "local" and item.role in ("resource", "navigation"):
                    found, why = refs.resolve(item.value, path.parent)
                    if found is None:
                        problems.append(f"{rel(path)}: {item.where} '{item.value}' -> {why}")
        report(self, "unresolved HTML references", problems)

    def test_css_url_references_resolve_to_files(self):
        html_pages()  # no page means no meaningful stylesheet check
        problems = []
        for path, text in css_files():
            for item in refs.css_refs(text, rel(path)):
                if refs.kind(item.value) == "local":
                    found, why = refs.resolve(item.value, path.parent)
                    if found is None:
                        problems.append(f"{rel(path)}: url({item.value}) -> {why}")
        report(self, "unresolved CSS url() references", problems)

    def test_fragment_links_point_at_existing_ids(self):
        problems = []
        for path, facts in html_pages():
            for attrs in facts.anchors:
                href = attrs.get("href", "").strip()
                frag = href[1:]
                if href.startswith("#") and frag not in ("", "top") and frag not in facts.ids:
                    problems.append(f"{rel(path)}: <a href='{href}'> has no element with that id")
        report(self, "dead in-page links", problems)

    def test_assets_never_use_absolute_urls_on_the_old_origin(self):
        problems = []
        for path, facts in html_pages():
            for item in refs.html_refs(facts):
                if (
                    item.role in ("resource", "origin-hint")
                    and refs.host_of(item.value) == OLD_ORIGIN_HOST
                ):
                    problems.append(f"{rel(path)}: {item.where} '{item.value}'")
        for path, text in css_files():
            for item in refs.css_refs(text, rel(path)):
                if refs.host_of(item.value) == OLD_ORIGIN_HOST:
                    problems.append(f"{rel(path)}: url({item.value})")
        report(self, f"assets pinned to {OLD_ORIGIN_HOST} (use relative paths)", problems)


if __name__ == "__main__":
    unittest.main()
