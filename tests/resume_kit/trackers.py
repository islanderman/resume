"""Third-party provider scripts: a normalized URL plus the IDs that identify the site to the provider."""

__unittest = True  # keeps helper frames out of unittest failure reports

import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from . import cloudflare as cf

VERSION_SUFFIX = re.compile(r"(?<=\.js)/v[0-9a-f]{20,}$")
BOOKKEEPING_ATTRS = {"data-cfasync", "data-cf-settings", "data-cf-beacon"}


@dataclass(frozen=True)
class Provider:
    url: str  # scheme://host/path with any pinned-version suffix and the query removed
    ids: frozenset


def _is_external(src):
    return urlsplit(src).scheme in ("http", "https") or src.startswith("//")


def normalize_url(src):
    parts = urlsplit("https:" + src if src.startswith("//") else src)
    path = VERSION_SUFFIX.sub("", parts.path)
    return f"{parts.scheme}://{parts.netloc.lower()}{path}"


def _ids(script, src):
    ids = {v for _, v in parse_qsl(urlsplit(src).query) if v}
    ids |= {
        v for k, v in script.attrs.items() if k.startswith("data-") and k not in BOOKKEEPING_ATTRS
    }
    try:
        token = json.loads(script.attrs.get("data-cf-beacon", "{}")).get("token")
    except (ValueError, AttributeError):
        token = None
    if token:
        ids.add(token)
    return ids


def provider_scripts(facts, keep_cwa=None):
    """External scripts that report to a third party; edge noise is dropped unless kept on purpose."""
    keep = cf.KEEP_CLOUDFLARE_WEB_ANALYTICS if keep_cwa is None else keep_cwa
    found = []
    for script in facts.scripts:
        src = script.attrs.get("src", "")
        if not src or not _is_external(src) or script.kind == "cloudflare-edge":
            continue
        if script.kind == "cloudflare-web-analytics" and not keep:
            continue
        found.append(Provider(normalize_url(src), frozenset(_ids(script, src))))
    return found
