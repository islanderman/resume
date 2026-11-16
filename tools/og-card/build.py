"""Render the social card: headless Chrome screenshots card.html; a lossless optimizer shrinks it.

Run `make og-card` (CI never does). Pick the browser with CHROME=/path/to/chrome; otherwise the
first Chromium build found on PATH, in /Applications or in Playwright's cache is used. The
optimizer is the first of oxipng, zopflipng, pngcrush or ImageMagick that is installed.
"""

import glob
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TEMPLATE = HERE / "card.html"
OUT = ROOT / "public" / "img" / "og" / "jerry-yang.png"
SIZE = (1200, 630)
MAX_BYTES = 100_000
CHROMES = (
    "chrome-headless-shell",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/"
    "chrome-headless-shell",
    "~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/"
    "chrome-headless-shell",
)


def find_chrome():
    if os.environ.get("CHROME"):
        return os.environ["CHROME"]
    for candidate in CHROMES:
        if "/" not in candidate:
            found = shutil.which(candidate)
        else:
            found = next(iter(sorted(glob.glob(os.path.expanduser(candidate)), reverse=True)), None)
        if found and os.access(found, os.X_OK):
            return found
    sys.exit("no Chromium build found; run with CHROME=/path/to/chrome")


def png_size(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def render(chrome, out):
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run(
            [
                chrome,
                "--headless",
                "--disable-gpu",
                "--hide-scrollbars",
                "--no-first-run",
                f"--user-data-dir={profile}",
                f"--window-size={SIZE[0]},{SIZE[1]}",
                "--force-device-scale-factor=1",
                # The page and its font are file:// URLs; Chrome needs this to load a font there.
                "--allow-file-access-from-files",
                # Virtual time runs until the font and the monogram have loaded, then shoots.
                "--virtual-time-budget=10000",
                f"--screenshot={out}",
                TEMPLATE.as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )


def optimize(src, work):
    """(smallest lossless encoding of src, tool name); src itself when no tool makes it smaller."""
    dst = work / "optimized.png"
    tools = (
        ("oxipng", [["oxipng", "-o", "max", "--strip", "all", "-q", "--out", dst, src]]),
        ("zopflipng", [["zopflipng", "-y", "--iterations=15", "--filters=01234mepb", src, dst]]),
        ("pngcrush", [["pngcrush", "-q", "-brute", "-rem", "alla", src, dst]]),
        # ImageMagick has no exhaustive search, so try a few filter and zlib strategy pairs.
        (
            "magick",
            [
                [
                    "magick", src, "-strip", "-define", "png:compression-level=9",
                    "-define", f"png:compression-filter={f}",
                    "-define", f"png:compression-strategy={z}", dst,
                ]
                for f in (0, 1, 5, 6)
                for z in (0, 1)
            ],
        ),
    )  # fmt: skip
    for name, commands in tools:
        if not shutil.which(name):
            continue
        best = src
        for i, cmd in enumerate(commands):
            subprocess.run([str(c) for c in cmd], check=True, capture_output=True, timeout=600)
            if name == "magick":
                same_pixels(src, dst)
            if dst.stat().st_size < best.stat().st_size:
                best = dst.rename(work / f"best-{i}.png")
        return best, name if best != src else f"{name} (no smaller; kept the render)"
    return src, "none installed (oxipng gives the smallest file)"


def same_pixels(a, b):
    """ImageMagick re-encodes every pixel, so prove that none changed."""
    result = subprocess.run(
        ["magick", "compare", "-metric", "AE", str(a), str(b), "null:"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.stderr.split()[:1] != ["0"]:
        sys.exit(f"the optimized card differs from the render: {result.stderr.strip()}")


def main():
    chrome = find_chrome()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        raw = work / "raw.png"
        render(chrome, raw)
        size = png_size(raw.read_bytes())
        if size != SIZE:
            sys.exit(f"{chrome} rendered {size}, not {SIZE}")
        best, tool = optimize(raw, work)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(best, OUT)
    data = OUT.read_bytes()
    version = hashlib.sha256(data).hexdigest()[:8]
    print(f"{OUT.relative_to(ROOT)}: {SIZE[0]}x{SIZE[1]}, {len(data):,} bytes, optimizer {tool}")
    print(f"Use ?v={version} in every URL to the card (index.html, sitemap.xml).")
    if len(data) > MAX_BYTES:
        sys.exit(f"the card is over {MAX_BYTES:,} bytes; simplify card.html")


if __name__ == "__main__":
    main()
