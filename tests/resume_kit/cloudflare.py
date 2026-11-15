"""What Cloudflare's edge adds to HTML, and how to undo it before comparing pages."""

__unittest = True  # keeps helper frames out of unittest failure reports

import re
from urllib.parse import urlsplit

# The beacon is injected at the edge and stays there, so source is never required to carry it.
KEEP_CLOUDFLARE_WEB_ANALYTICS = False

BEACON_HOST = "static.cloudflareinsights.com"
EDGE_PATH = "/cdn-cgi/"
EMAIL_HREF = re.compile(r"(?:^|/)cdn-cgi/l/email-protection#([0-9a-fA-F]{4,})$")
ROCKET_TYPE = re.compile(r"^[0-9a-f]{8,}-(text/javascript|module)$", re.IGNORECASE)


def decode_cfemail(hex_text):
    """Email Obfuscation: the first byte is the XOR key for every following byte."""
    raw = bytes.fromhex(hex_text)
    if len(raw) < 2:
        raise ValueError(f"data-cfemail too short: {hex_text!r}")
    key = raw[0]
    plain = bytes(b ^ key for b in raw[1:])
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError:
        return plain.decode("latin-1")


def encode_cfemail(address, key=0x2A):
    """Inverse of decode_cfemail; the edge picks a fresh random key on every response."""
    return f"{key:02x}" + "".join(f"{b ^ key:02x}" for b in address.encode("utf-8"))


def decode_email_href(href):
    """Return 'mailto:<address>' for an obfuscated link href, else None."""
    match = EMAIL_HREF.search(href.strip())
    return "mailto:" + decode_cfemail(match.group(1)) if match else None


def classify_script(attrs, text):
    """'cloudflare-edge', 'cloudflare-web-analytics', or None for a site-owned script."""
    src = attrs.get("src", "")
    if EDGE_PATH in src or "__CF$cv$params" in text or EDGE_PATH in text:
        return "cloudflare-edge"
    parts = urlsplit(src)
    if parts.hostname == BEACON_HOST and parts.path.startswith("/beacon.min.js"):
        return "cloudflare-web-analytics"
    return None


def clean_script_attrs(attrs):
    """Undo Rocket Loader: restore the real type and drop its bookkeeping attributes."""
    out = {k: v for k, v in attrs.items() if k not in ("data-cf-settings", "data-cfasync")}
    match = ROCKET_TYPE.match(out.get("type", ""))
    if match:
        out["type"] = match.group(1)
    return out
