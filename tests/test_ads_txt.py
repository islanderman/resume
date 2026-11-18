"""AdSense site verification: public/ads.txt is Google's one DIRECT record and nothing else.
chenyang.us and www.chenyang.us 301 /ads.txt to this host, a same-root-domain redirect the IAB
ads.txt spec allows, so the crawler reads this file."""

import unittest

from resume_kit.common import PUBLIC, read_text, rel

ADS_TXT = PUBLIC / "ads.txt"
# Fields: ad system, publisher account, relationship, Google's TAG ID.
RECORD = "google.com, pub-5781177425067414, DIRECT, f08c47fec0942fa0"


def ads_text():
    return read_text(ADS_TXT, "AdSense reads /ads.txt")


def records(text):
    """Non-blank lines once '#' comments are cut, the way the ads.txt spec reads them."""
    cut = (line.split("#", 1)[0].strip() for line in text.splitlines())
    return [line for line in cut if line]


class AdsTxtTest(unittest.TestCase):
    def test_exists_at_the_site_root(self):
        ads_text()

    def test_is_the_record_and_one_newline_exactly(self):
        self.assertEqual(
            ads_text(), RECORD + "\n", f"{rel(ADS_TXT)} must be the record plus one LF, no more"
        )

    def test_is_ascii(self):
        self.assertTrue(ads_text().isascii(), f"{rel(ADS_TXT)} holds a non-ASCII character (BOM?)")

    def test_holds_no_other_record(self):
        self.assertEqual(records(ads_text()), [RECORD], f"{rel(ADS_TXT)} must hold only that record")


if __name__ == "__main__":
    unittest.main()
