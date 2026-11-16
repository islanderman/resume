"""Icon policy: SVG with the shared 0 0 24 24 viewBox or a 96x96 PNG fallback; never .ico or icon fonts."""

import re
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from resume_kit import cssscan, htmlfacts, pagecss, refs, svgcheck
from resume_kit.common import (
    FIXTURES,
    ICON_DIR,
    INDEX,
    input_problem,
    public_files,
    read_text,
    rel,
    report,
)

SHARED_VIEWBOX = (0.0, 0.0, 24.0, 24.0)
PNG_FALLBACK_SIZE = (96, 96)
STANDARD_FAVICON_SIZES = {16, 32, 48, 96, 144, 180, 192, 256, 512}
FAVICON_LINK_RELS = {
    "icon",
    "shortcut",
    "apple-touch-icon",
    "apple-touch-icon-precomposed",
    "mask-icon",
}
RASTER_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".avif",
    ".bmp",
    ".ico",
    ".tif",
    ".tiff",
}
ICON_FONT_NAMES = re.compile(
    r"font[ -]?awesome|bootstrap-icons|material[ -]?(icons|symbols)|ionicons|glyphicons|icomoon|themify",
    re.I,
)
ICON_FONT_CLASS = re.compile(
    r"^(fa|fas|far|fab|fal|fad|fat|bi|glyphicon|material-icons|ion|mdi|icomoon)$"
    r"|^(fa|bi|glyphicon|mdi|ion|icon|material-symbols)-.+$"
)
PUA_CONTENT = re.compile(r"""content\s*:\s*["']\\[ef][0-9a-f]{3}["']""", re.I)
ICON_TAGS = {"img", "use", "image", "object", "embed"}


def is_favicon_fallback(name):
    """favicon.ico, apple-touch-icon*.png and favicon-NxN.png at a standard square size."""
    if name == "favicon.ico":
        return True
    if re.match(r"^apple-touch-icon(-precomposed)?(-\d+x\d+)?\.png$", name):
        return True
    match = re.match(r"^favicon-(\d+)x\1\.png$", name)
    return bool(match) and int(match.group(1)) in STANDARD_FAVICON_SIZES


def icon_files():
    if not ICON_DIR.is_dir():
        raise input_problem(f"{rel(ICON_DIR)} is missing (every company icon is converted into it)")
    return sorted(p for p in ICON_DIR.rglob("*") if p.is_file())


def original_images():
    return htmlfacts.page(FIXTURES / "original.html", edge=True).images


class IconFilesTest(unittest.TestCase):
    def test_every_original_icon_has_a_converted_file(self):
        originals = {img.get("src") for img in original_images()}
        files = icon_files()
        if len(files) < len(originals):
            self.fail(
                f"{len(files)} icon files in {rel(ICON_DIR)}, the original page uses {len(originals)} "
                f"distinct icons: {sorted(originals)}"
            )

    def test_icon_files_are_svg_or_96px_png_only(self):
        problems = []
        for path in icon_files():
            suffix = path.suffix.lower()
            if suffix == ".png":
                size = svgcheck.png_size(path.read_bytes())
                if size != PNG_FALLBACK_SIZE:
                    problems.append(
                        f"{rel(path)} is {size or 'not a PNG'}, fallbacks must be 96x96"
                    )
            elif suffix != ".svg":
                problems.append(f"{rel(path)} is not SVG or PNG (no .ico, .jpg, .gif, .webp)")
        report(self, "icon files that break the policy", problems)

    def test_svg_icons_are_valid_and_inert(self):
        problems = []
        for path in icon_files():
            if path.suffix.lower() == ".svg":
                problems += [
                    f"{rel(path)}: {p}" for p in svgcheck.inspect_svg(path.read_bytes()).problems
                ]
        report(self, "SVG icon defects", problems)

    def test_svg_viewboxes_are_identical_and_0_0_24_24(self):
        problems = []
        for path in icon_files():
            if path.suffix.lower() == ".svg":
                box = svgcheck.inspect_svg(path.read_bytes()).viewbox
                if box != SHARED_VIEWBOX:
                    problems.append(f"{rel(path)} viewBox is {box}, expected {SHARED_VIEWBOX}")
        report(self, "icons off the shared 24x24 grid", problems)

    def test_svg_root_size_attributes_are_square_and_consistent(self):
        sizes = {}
        for path in icon_files():
            if path.suffix.lower() == ".svg":
                width, height = svgcheck.inspect_svg(path.read_bytes()).size_attrs
                sizes[rel(path)] = (width, height)
        problems = [
            f"{p}: width={w} height={h} is not square" for p, (w, h) in sizes.items() if w != h
        ]
        if len(set(sizes.values())) > 1:
            problems.append(
                f"icons disagree on width/height attributes: {sorted(set(sizes.values()))}"
            )
        report(self, "SVG size attributes", problems)


class IconReferencesTest(unittest.TestCase):
    def test_images_reference_only_svg_or_png_files_inside_the_icon_directory(self):
        facts = htmlfacts.page(INDEX)
        problems = []
        for ref in facts.refs:
            if ref.tag not in ICON_TAGS and not (ref.tag == "source" and ref.attr == "srcset"):
                continue
            values = refs.split_srcset(ref.value) if ref.attr == "srcset" else [ref.value]
            for value in values:
                state = refs.kind(value)
                suffix = Path(urlsplit(value).path).suffix.lower()
                if state == "fragment":
                    continue  # <use href="#id"> points at an inline symbol
                if state != "local":
                    problems.append(f"<{ref.tag} {ref.attr}> '{value[:60]}' is not a local file")
                elif suffix not in (".svg", ".png"):
                    problems.append(
                        f"<{ref.tag} {ref.attr}> '{value}' is {suffix or 'untyped'}, not svg/png"
                    )
                else:
                    found, _ = refs.resolve(value, INDEX.parent)
                    if found is not None and ICON_DIR.resolve() not in found.resolve().parents:
                        problems.append(f"'{value}' is not under {rel(ICON_DIR)}")
        report(self, "icon references that break the policy", problems)

    def test_favicon_links_use_only_standard_fallbacks(self):
        problems = []
        for attrs in htmlfacts.page(INDEX).links:
            if set(attrs.get("rel", "").lower().split()) & FAVICON_LINK_RELS:
                name = Path(urlsplit(attrs.get("href", "")).path).name
                if not (name.lower().endswith(".svg") or is_favicon_fallback(name)):
                    problems.append(f"<link rel='{attrs.get('rel')}' href='{attrs.get('href')}'>")
        report(self, "favicon links outside the allowed fallbacks", problems)

    def test_css_never_references_ico_or_loose_raster_images(self):
        problems = []
        for path in public_files(".css"):
            problems += _raster_urls(rel(path), read_text(path, "stylesheet"), path.parent)
        for style in htmlfacts.page(INDEX).styles:
            problems += _raster_urls("<style>", style.text, INDEX.parent)
        report(self, "CSS raster references outside the icon directory", problems)

    def test_no_icon_fonts(self):
        facts = htmlfacts.page(INDEX)
        problems = [
            f"class '{c}' is an icon-font class"
            for c in sorted(facts.class_tokens)
            if ICON_FONT_CLASS.match(c)
        ]
        problems += [
            f"<link href='{a.get('href')}'> loads an icon font"
            for a in facts.links
            if ICON_FONT_NAMES.search(a.get("href", ""))
        ]
        texts = [(rel(p), read_text(p, "stylesheet")) for p in public_files(".css")]
        texts += [("<style>", s.text) for s in facts.styles]
        for where, text in texts:
            if ICON_FONT_NAMES.search(text) or PUA_CONTENT.search(text):
                problems.append(f"{where} references an icon font or private-use glyphs")
        report(self, "icon fonts", problems)

    def test_every_original_icon_slot_is_kept(self):
        facts = htmlfacts.page(INDEX)
        slots = len(facts.images) + sum(
            1 for r in facts.refs if r.tag in ("use", "object", "embed")
        )
        slots += facts.svg_inline
        expected = len(original_images())
        if slots < expected:
            self.fail(
                f"page has {slots} icon slots (<img>, <use>, <object>, <embed>, inline <svg>); original has {expected}"
            )

    def test_img_elements_are_never_stretched(self):
        problems = []
        for attrs in htmlfacts.page(INDEX).images:
            w, h = attrs.get("width", ""), attrs.get("height", "")
            if w.isdigit() and h.isdigit() and w != h:
                problems.append(
                    f"<img src='{attrs.get('src')}' width={w} height={h}> is not square"
                )
        report(self, "stretched icons", problems)


def _raster_urls(where, text, base):
    problems = []
    for value in cssscan.urls(text):
        suffix = Path(urlsplit(value).path).suffix.lower()
        if suffix not in RASTER_SUFFIXES or refs.kind(value) == "special":
            continue
        found, _ = refs.resolve(value, base) if refs.kind(value) == "local" else (None, None)
        inside = found is not None and ICON_DIR.resolve() in found.resolve().parents
        if not (suffix == ".png" and inside):
            problems.append(f"{where}: url({value})")
    return problems


class IconSizingTest(unittest.TestCase):
    """Icon CSS policy: 20px below 600px, 24px from 600px, 16px grayscale in print; always square."""

    # The readability spec moved the step from 721px to the 600px tablet breakpoint on purpose.
    SCREEN_POLICY = {320: 20, 390: 20, 599: 20, 600: 24, 720: 24, 768: 24, 1024: 24, 1440: 24}
    PRINT_WIDTH = 794  # A4 at 96dpi; the desktop rules still apply, so print must override them

    @staticmethod
    def _sizes(sheet, width, media):
        # Rules whose selector mentions "icon"; var(), :root tokens, rem and inline-size/block-size resolve.
        return cssscan.resolved_sizes(
            sheet, width, media, lambda selector: "icon" in selector.lower()
        )

    def test_icon_css_follows_the_size_policy_and_never_stretches(self):
        sheet = pagecss.page_sheet()
        contexts = [(w, "screen", want) for w, want in self.SCREEN_POLICY.items()]
        contexts.append((self.PRINT_WIDTH, "print", 16))
        problems, missed = [], {}
        if not any(self._sizes(sheet, 390, "screen").values()):
            problems.append("no CSS rule with 'icon' in its selector sizes the icons")
        for width, media, want in contexts:
            met = False
            for selector, (w, h, flt) in self._sizes(sheet, width, media).items():
                if w is not None and h is not None and w != h:
                    problems.append(f"{selector} is {w}x{h} at {width}px/{media} (stretched)")
                sizes = {v for v in (w, h) if v is not None}
                if sizes == {float(want)} and (media == "screen" or "grayscale" in flt):
                    met = True
            if not met:
                missed.setdefault((want, media), []).append(width)
        for (want, media), widths in missed.items():
            extra = " with filter: grayscale()" if media == "print" else ""
            problems.append(
                f"no icon rule yields {want}px square{extra} for {media} widths {widths}"
            )
        report(self, "icon sizing", problems)


if __name__ == "__main__":
    unittest.main()
