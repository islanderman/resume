"""Icon file inspection: SVG safety and viewBox, PNG dimensions."""

__unittest = True  # keeps helper frames out of unittest failure reports

import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

SVG_NS = "http://www.w3.org/2000/svg"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
RASTER_DATA_URI = re.compile(r"data:image/(?:png|jpe?g|gif|webp|avif|bmp)", re.I)
BANNED_ELEMENTS = {"script", "image", "foreignobject", "iframe", "embed", "object"}
SHAPES = {"path", "circle", "rect", "ellipse", "line", "polyline", "polygon", "text", "use"}


@dataclass
class IconReport:
    viewbox: object = None  # (min_x, min_y, width, height) or None
    size_attrs: tuple = (None, None)
    problems: list = field(default_factory=list)


def _local(name):
    return name.rsplit("}", 1)[-1].lower()


def parse_viewbox(value):
    """Four floats from a viewBox attribute, or None when absent, malformed or empty."""
    if value is None:
        return None
    try:
        numbers = tuple(float(n) for n in re.split(r"[\s,]+", value.strip()))
    except ValueError:
        return None
    return numbers if len(numbers) == 4 and numbers[2] > 0 and numbers[3] > 0 else None


def inspect_svg(data):
    """Check SVG bytes: well-formed, svg-namespaced root, drawable, viewBox, no active or raster content."""
    report = IconReport()
    text = data.decode("utf-8", errors="replace")
    # Stdlib ElementTree is the only parser allowed here, so entities are refused before parsing.
    if "<!ENTITY" in text or re.search(r"<!DOCTYPE[^>]*\[", text, re.I):
        report.problems.append("declares DTD entities (XXE / entity-expansion risk)")
        return report
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        report.problems.append(f"not well-formed XML: {exc}")
        return report
    if root.tag != f"{{{SVG_NS}}}svg":
        report.problems.append(f"root is <{root.tag}>, expected <svg> in the {SVG_NS} namespace")
    report.viewbox = parse_viewbox(root.get("viewBox"))
    report.size_attrs = (root.get("width"), root.get("height"))
    if report.viewbox is None:
        report.problems.append(f"viewBox is missing or invalid ({root.get('viewBox')!r})")
    drawable = False
    for el in root.iter():
        name = _local(el.tag)
        drawable = drawable or name in SHAPES
        if name in BANNED_ELEMENTS:
            report.problems.append(f"contains <{name}> (no raster, script or embedded documents)")
        values = list(el.attrib.items()) + [("#text", (el.text or ""))]
        for attr, value in values:
            attr_name = _local(attr)
            if attr_name.startswith("on"):
                report.problems.append(f"event handler attribute {attr_name}=")
            if "javascript:" in value.lower():
                report.problems.append(f"javascript: URL in {attr_name}")
            if RASTER_DATA_URI.search(value):
                report.problems.append(f"embedded raster data URI in {attr_name}")
            if attr_name == "href" and not value.startswith("#"):
                report.problems.append(f"href '{value[:60]}' is not a same-document fragment")
            if (attr_name in ("style", "#text")) and re.search(r"url\(\s*['\"]?(?!#)", value, re.I):
                report.problems.append("CSS url() that is not a same-document fragment")
            if attr_name == "#text" and "@import" in value.lower():
                report.problems.append("CSS @import")
    if not drawable:
        report.problems.append(
            "has no drawable element (path, circle, rect, ...): the icon would be blank"
        )
    return report


def png_size(data):
    """(width, height) from a PNG's IHDR chunk, or None when it is not a PNG."""
    if len(data) < 24 or data[:8] != PNG_MAGIC or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def read_icon(path):
    return Path(path).read_bytes()
