"""Profile links: the masthead contact links plus every rel="me" <a> or <link>, as Person.sameAs
and the owner's LinkedIn-only rule read them."""

__unittest = True  # keeps helper frames out of unittest failure reports

from urllib.parse import urlsplit

from . import elements, htmlfacts, refs
from .common import INDEX


def canonical(index=INDEX):
    """The canonical URL that index.html declares, or ''."""
    return htmlfacts.page(index).link_href("canonical") or ""


def has_rel(attrs, token):
    """True when the rel attribute holds `token`; rel tokens ignore ASCII case."""
    return token in attrs.get("rel", "").lower().split()


def _is_profile(tag, attrs, parents):
    in_contact = any("contact" in elements.classes(a) for _, a in parents)
    return (tag == "a" and in_contact) or (tag in ("a", "link") and has_rel(attrs, "me"))


def profile_links(path=INDEX):
    """Elements for links in the masthead contact block plus every rel="me" <a> or <link>."""
    return elements.pick_in(path, _is_profile)


def external_profiles(path=INDEX):
    """Normalized off-site http(s) profile links on `path`: what Person.sameAs must list."""
    own = urlsplit(canonical()).hostname
    found = set()
    for element in profile_links(path):
        href = element.attrs.get("href", "").strip()
        if refs.kind(href) == "external" and refs.host_of(href) != own:
            found.add(refs.norm_link("https:" + href if href.startswith("//") else href))
    return found
