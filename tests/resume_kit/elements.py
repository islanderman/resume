"""Visible text of the elements a predicate picks, so parity checks survive a markup change."""

__unittest = True  # keeps helper frames out of unittest failure reports

import unicodedata
from collections import namedtuple
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

from .common import read_text
from .htmlfacts import BLOCK, HIDDEN, VOID

Element = namedtuple("Element", "tag attrs text")


def classes(attrs):
    return attrs.get("class", "").split()


class _Picker(HTMLParser):
    def __init__(self, pick):
        super().__init__(convert_charrefs=True)
        self.pick = pick
        self.found = []  # [tag, attrs, chunks]
        self.stack = []  # (tag, attrs, index into found or None)

    def handle_starttag(self, tag, attrs_list):
        attrs = {name: "" if value is None else value for name, value in attrs_list}
        parents = [(t, a) for t, a, _ in self.stack]
        hit = None
        if self.pick(tag, attrs, parents):
            hit = len(self.found)
            self.found.append((tag, attrs, []))
        if tag in BLOCK:
            self._add(" ")
        if tag not in VOID:
            self.stack.append((tag, attrs, hit))

    def handle_endtag(self, tag):
        if tag in BLOCK:
            self._add(" ")
        # Unwind to the matching start tag; implicitly closed elements (p, li) close with it.
        for depth in range(len(self.stack) - 1, -1, -1):
            if self.stack[depth][0] == tag:
                del self.stack[depth:]
                break

    def handle_data(self, data):
        if not any(t in HIDDEN for t, _, _ in self.stack):
            self._add(data)

    def _add(self, text):
        for _, _, hit in self.stack:
            if hit is not None:
                self.found[hit][2].append(text)


def pick(html, predicate):
    """Each element for which predicate(tag, attrs, parents) holds, in page order, with its text."""
    parser = _Picker(predicate)
    parser.feed(html)
    parser.close()
    return [
        Element(tag, attrs, " ".join(unicodedata.normalize("NFC", "".join(chunks)).split()))
        for tag, attrs, chunks in parser.found
    ]


@lru_cache(maxsize=None)
def _cached_html(path, mtime_ns, size):
    return read_text(path, "page under test")


def pick_in(path, predicate):
    """pick() over a file; the read is cached per (path, mtime, size)."""
    path = Path(path)
    if not path.is_file():
        read_text(path, "page under test")  # raises the standard missing-file AssertionError
    stat = path.stat()
    return pick(_cached_html(str(path), stat.st_mtime_ns, stat.st_size), predicate)
