"""Search-engine ownership tags. Bing re-checks its tag, so removing it un-verifies the site."""

import unittest
from html.parser import HTMLParser
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "public" / "index.html"
BING = ("msvalidate.01", "9D75B58D9AC0EF87C3D89261112BC012")


class _HeadMeta(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.metas = []

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.in_head = True
        elif tag == "meta" and self.in_head:
            self.metas.append(dict(attrs))

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False


def head_metas():
    parser = _HeadMeta()
    parser.feed(INDEX.read_text(encoding="utf-8"))
    return parser.metas


class VerificationMetaTest(unittest.TestCase):
    def test_bing_tag_appears_once_in_head_with_the_owner_code(self):
        name, code = BING
        tags = [m for m in head_metas() if m.get("name") == name]
        self.assertEqual(len(tags), 1, f"want exactly one <meta name={name!r}> in <head>")
        self.assertEqual(tags[0].get("content"), code)


if __name__ == "__main__":
    unittest.main()
