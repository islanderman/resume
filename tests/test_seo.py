"""Search and sharing metadata: head tags, social card, JSON-LD, manifest and root files. Every
JSON-LD fact must be visible on the page, and every URL that names the page must be the canonical
one, so search engines and link previews never disagree with what a reader sees."""

import json
import re
import subprocess
import unittest
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from resume_kit import elements, htmlfacts, refs, svgcheck
from resume_kit import headers as hdr
from resume_kit.common import (
    HEADERS_FILE,
    INDEX,
    PUBLIC,
    ROOT,
    public_files,
    read_json,
    read_text,
    rel,
    report,
)

NOT_FOUND = PUBLIC / "404.html"
SITEMAP = PUBLIC / "sitemap.xml"
ROBOTS = PUBLIC / "robots.txt"
LLMS = PUBLIC / "llms.txt"
MANIFEST_HREF = "/site.webmanifest"
TITLE_MAX = 60
DESCRIPTION_RANGE = (120, 160)
# Bing Webmaster Tools flags any page whose title or meta description falls outside these lengths.
BING_TITLE_RANGE = (10, 60)
BING_DESCRIPTION_RANGE = (25, 160)
ROBOTS_DIRECTIVES = (
    "index",
    "follow",
    "max-image-preview:large",
    "max-snippet:-1",
    "max-video-preview:-1",
)
CARD_SIZE = (1200, 630)
CARD_MAX_BYTES = 100_000
OG_PREFIXES = ("og:", "profile:")
OG_EXPECTED = {
    "og:type": "profile",
    "og:locale": "en_US",
    "og:image:type": "image/png",
    "og:image:width": str(CARD_SIZE[0]),
    "og:image:height": str(CARD_SIZE[1]),
}
OG_REQUIRED = (
    "og:type", "og:site_name", "og:locale", "og:title", "og:description", "og:url", "og:image",
    "og:image:type", "og:image:width", "og:image:height", "og:image:alt", "profile:first_name",
    "profile:last_name",
)  # fmt: skip
TWITTER_REQUIRED = (
    "twitter:card",
    "twitter:title",
    "twitter:description",
    "twitter:image",
    "twitter:image:alt",
)
X_HOSTS = ("x.com", "twitter.com")
SECTION_IDS = ("summary", "experience", "advisory", "education")
SITEMAP_NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "image": "http://www.google.com/schemas/sitemap-image/1.1",
}
W3C_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ROBOTS_UPDATED = re.compile(r"^#.*Last updated:\s*(\S+)", re.M)
# Identifiers, URLs, dates and vocabulary terms, not facts a reader could check against the page.
NOT_FACTS = frozenset(
    "@context @type @id url sameAs image contentUrl inLanguage dateModified datePublished "
    "encodingFormat credentialCategory knowsLanguage email telephone".split()
)
PHONE = re.compile(r"\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
# The owner forbids any GitHub link: repositories, gists, Pages sites and raw files alike.
GITHUB = re.compile(r"github\.com|github\.io|githubusercontent\.com", re.I)
# Owner-authored facts the page never shows, carried over from the original JSON-LD
# (tests/fixtures/original.html) on the owner's word. Only these two skip the visibility rule.
OWNER_FACTS = frozenset(
    {("Person", "alternateName", "Chen Yang"), ("Person", "knowsLanguage", "zh")}
)
# keywords: Google ignores the tag and Bing gives it no ranking weight, so it only adds bytes.
BANNED_META_NAMES = re.compile(r"^(dc|dcterms)\.|^revisit-after$|^msapplication-|^keywords$", re.I)


def facts(path=INDEX):
    return htmlfacts.page(path)


def canonical():
    return facts().link_href("canonical") or ""


def tag_values(page, key, wanted):
    """Every content value of <meta key=wanted>, in page order."""
    return [m.get("content", "") for m in page.metas if m.get(key, "").lower() == wanted]


def meta_one(key, wanted):
    values = tag_values(facts(), key, wanted)
    return values[0] if values else None


def h1_text():
    found = elements.pick_in(INDEX, lambda tag, attrs, parents: tag == "h1")
    return found[0].text if found else ""


def visible():
    return " ".join(facts().visible_text().casefold().split())


def norm(text):
    return " ".join(str(text).casefold().split())


def shown(value, text):
    """True when `value` is in the normalized `text` as whole words, ignoring case and spacing."""
    return re.search(rf"(?<!\w){re.escape(norm(value))}(?!\w)", text) is not None


def json_ld_blocks(page):
    out = []
    for script in page.scripts:
        if script.json_ld:
            try:
                out.append(json.loads(script.text))
            except ValueError as exc:
                raise AssertionError(f"JSON-LD does not parse: {exc}") from exc
    return out


def graph():
    """The one JSON-LD block's @graph, as {node @id: node}; fails on any other shape."""
    blocks = json_ld_blocks(facts())
    if len(blocks) != 1:
        raise AssertionError(f"{len(blocks)} JSON-LD blocks, expected exactly one @graph")
    block = blocks[0]
    if not isinstance(block, dict) or block.get("@context") != "https://schema.org":
        raise AssertionError("the JSON-LD block needs @context 'https://schema.org'")
    nodes = block.get("@graph")
    if not isinstance(nodes, list) or not all(isinstance(n, dict) for n in nodes):
        raise AssertionError("the JSON-LD block has no @graph list of objects")
    return {n.get("@id"): n for n in nodes}


def node(kind):
    """The top-level node at <canonical>#<kind>."""
    found = graph().get(canonical() + "#" + kind)
    if found is None:
        raise AssertionError(f"@graph has no node with @id {canonical()}#{kind}")
    return found


def walk(value, path=""):
    """(path, key, value, parent) for every key below `value`, depth first."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield path, key, child, value
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from walk(child, f"{path}[{i}]")


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def resolve_ref(value):
    """A node dict for an inline node or an {"@id": ...} reference into the graph, else None."""
    if isinstance(value, dict) and set(value) == {"@id"}:
        return graph().get(value["@id"])
    return value if isinstance(value, dict) else None


def site_file(url):
    """The public/ file an absolute URL on the canonical host names, or (None, reason)."""
    parts = urlsplit(url or "")
    if parts.scheme != "https" or parts.hostname != urlsplit(canonical()).hostname:
        return None, f"'{url}' is not an absolute https URL on {urlsplit(canonical()).hostname}"
    return refs.resolve(parts.path, PUBLIC)


def profile_links(path=INDEX):
    """Elements for links in the masthead contact block plus every rel="me" link."""
    return elements.pick_in(
        path,
        lambda tag, attrs, parents: tag == "a"
        and (
            "me" in attrs.get("rel", "").lower().split()
            or any("contact" in elements.classes(a) for _, a in parents)
        ),
    )


def is_own_page(href):
    return refs.norm_link(href) == refs.norm_link(canonical())


def external_profiles(path=INDEX):
    """Normalized off-site http(s) profile links: what Person.sameAs must list."""
    host = urlsplit(canonical()).hostname
    return {
        refs.norm_link(e.attrs.get("href", ""))
        for e in profile_links(path)
        if refs.kind(e.attrs.get("href", "")) == "external"
        and refs.host_of(e.attrs.get("href", "")) != host
    }


def sitemap_tree():
    text = read_text(SITEMAP, "search engines read the sitemap")
    # Stdlib ElementTree is the only parser here, so entity declarations are refused before parsing.
    if re.search(r"<!(DOCTYPE|ENTITY)", text, re.I):
        raise AssertionError(f"{rel(SITEMAP)} declares a DTD or entities; a sitemap needs neither")
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        raise AssertionError(f"{rel(SITEMAP)} is not well-formed XML: {exc}") from exc


def sitemap_urls():
    return sitemap_tree().findall("sm:url", SITEMAP_NS)


def sitemap_lastmod():
    found = [u.findtext("sm:lastmod", "", SITEMAP_NS).strip() for u in sitemap_urls()]
    return found[0] if len(found) == 1 else None


def latest_today():
    """Today in the zone furthest ahead (UTC+14): a later date is in the future everywhere."""
    return (datetime.now(timezone.utc) + timedelta(hours=14)).date()


def newest_author_date(path):
    """Author date (the author's zone) of the newest commit touching `path`, or (None, why)."""
    try:
        shallow = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if shallow.returncode != 0:
            return None, "not a git checkout"
        if shallow.stdout.strip() == "true":
            return None, "the git history is shallow"
        # %as, not the committer date: a rebase rewrites the committer date but keeps the author's.
        log = subprocess.run(
            ["git", "log", "-1", "--format=%as", "--", rel(path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"git is not usable: {exc}"
    stamp = log.stdout.strip()
    if log.returncode != 0 or not stamp:
        return None, f"no commit touches {rel(path)} yet"
    return date.fromisoformat(stamp), None


def manifest():
    links = [a for a in facts().links if "manifest" in a.get("rel", "").lower().split()]
    if len(links) != 1 or links[0].get("href") != MANIFEST_HREF:
        raise AssertionError(f'index.html needs one <link rel="manifest" href="{MANIFEST_HREF}">')
    path, why = refs.resolve(MANIFEST_HREF, PUBLIC)
    if path is None:
        raise AssertionError(f"{MANIFEST_HREF} does not resolve: {why}")
    data = read_json(path, "web app manifest")
    if not isinstance(data, dict):
        raise AssertionError(f"{rel(path)} must hold a JSON object")
    return data


class HeadTagsTest(unittest.TestCase):
    def test_title_is_short_and_names_the_person(self):
        title = facts().title.strip()
        problems = []
        if len(title) > TITLE_MAX:
            problems.append(f"{len(title)} characters, at most {TITLE_MAX}: {title!r}")
        if not h1_text() or h1_text() not in title:
            problems.append(f"{title!r} does not contain the h1 name {h1_text()!r}")
        report(self, "<title>", problems)

    def test_description_fits_the_snippet(self):
        values = tag_values(facts(), "name", "description")
        low, high = DESCRIPTION_RANGE
        problems = [] if len(values) == 1 else [f"{len(values)} description tags, expected 1"]
        for value in values:
            if not low <= len(value) <= high:
                problems.append(f"{len(value)} characters, expected {low}-{high}: {value!r}")
        report(self, '<meta name="description">', problems)

    def test_every_page_has_one_title_and_description_bing_accepts(self):
        problems = []
        for path in public_files(".html", ".htm"):
            page = facts(path)
            titles = elements.pick_in(
                path,
                lambda tag, attrs, parents: tag == "title" and all(t != "svg" for t, _ in parents),
            )
            if len(titles) != 1:
                problems.append(f"{rel(path)}: {len(titles)} <title> elements, expected 1")
            descriptions = tag_values(page, "name", "description")
            if len(descriptions) != 1:
                problems.append(f"{rel(path)}: {len(descriptions)} description tags, expected 1")
            sized = [("<title>", " ".join(page.title.split()), BING_TITLE_RANGE)] if titles else []
            sized += [("description", d, BING_DESCRIPTION_RANGE) for d in descriptions]
            for what, value, (low, high) in sized:
                if not low <= len(value) <= high:
                    problems.append(
                        f"{rel(path)}: {what} has {len(value)} characters, expected {low}-{high}"
                    )
        report(self, "titles and descriptions outside Bing's ranges", problems)

    def test_robots_meta_allows_full_snippets_and_large_previews(self):
        values = tag_values(facts(), "name", "robots")
        problems = [] if len(values) == 1 else [f"{len(values)} robots tags, expected 1"]
        for value in values:
            tokens = [t.strip().lower() for t in value.split(",") if t.strip()]
            if sorted(tokens) != sorted(ROBOTS_DIRECTIVES):
                problems.append(f"content is {value!r}, expected {', '.join(ROBOTS_DIRECTIVES)!r}")
        report(self, '<meta name="robots">', problems)

    def test_404_is_noindex(self):
        values = tag_values(facts(NOT_FOUND), "name", "robots")
        if not any("noindex" in v.lower().replace(" ", "").split(",") for v in values):
            self.fail(f'{rel(NOT_FOUND)} needs <meta name="robots" content="noindex">')

    def test_canonical_is_the_one_url_everywhere(self):
        url = canonical()
        ok = url.startswith("https://") and url.endswith("/")
        problems = [] if ok else [f"canonical {url!r} is not an absolute https URL ending in /"]
        named = {"og:url": meta_one("property", "og:url")}
        for kind in ("website", "profilepage", "person"):
            named[f"JSON-LD #{kind} url"] = node(kind).get("url")
        locs = [u.findtext("sm:loc", "", SITEMAP_NS).strip() for u in sitemap_urls()]
        named["sitemap <loc>"] = locs[0] if len(locs) == 1 else locs
        problems += [f"{k} is {v!r}, canonical is {url!r}" for k, v in named.items() if v != url]
        report(self, "URLs that disagree with the canonical", problems)

    def test_banned_tags_stay_out(self):
        page = facts()
        problems = [
            f"<meta name={m['name']!r}>"
            for m in page.metas
            if BANNED_META_NAMES.search(m.get("name", ""))
        ]
        problems += [
            f"<meta property={m['property']!r}>"
            for m in page.metas
            if m.get("property", "").lower() == "og:updated_time"
        ]
        for attrs in page.links:
            rels = set(attrs.get("rel", "").lower().split())
            href = attrs.get("href", "")
            if "alternate" in rels and "hreflang" in attrs:
                problems.append(f"hreflang link {href!r}: the site has one language")
            if "amphtml" in rels:
                problems.append(f"AMP link {href!r}")
            if rels & {"preconnect", "dns-prefetch"} and "googletagmanager" in href:
                problems.append(f"{attrs.get('rel')} to {href!r} competes with the critical path")
        for script in page.scripts:
            src, body = script.attrs.get("src", ""), script.text
            if src and refs.kind(src) == "local":
                path, _ = refs.resolve(src, INDEX.parent)
                body = read_text(path, "script the page loads") if path else ""
            if "serviceWorker" in body:
                problems.append(f"script {src or 'inline'} registers a service worker")
        report(self, "tags the SEO plan rules out", problems)


class SocialTagsTest(unittest.TestCase):
    def test_each_tag_uses_its_attribute_kind_once(self):
        problems, seen = [], {}
        for attrs in facts().metas:
            name, prop = attrs.get("name", "").lower(), attrs.get("property", "").lower()
            if name.startswith(OG_PREFIXES):
                problems.append(f'<meta name="{name}"> must use property=')
            if prop.startswith("twitter:"):
                problems.append(f'<meta property="{prop}"> must use name=')
            for key in (name, prop):
                if key.startswith(OG_PREFIXES + ("twitter:",)):
                    seen[key] = seen.get(key, 0) + 1
        problems += [f"{key} appears {count} times" for key, count in seen.items() if count > 1]
        report(self, "Open Graph and Twitter attribute kinds", problems)

    def test_open_graph_set_is_complete(self):
        page = facts()
        got = {k: meta_one("property", k) for k in OG_REQUIRED}
        problems = [f"{k} is missing or empty" for k, v in got.items() if not (v or "").strip()]
        problems += [
            f"{k} is {got[k]!r}, expected {v!r}" for k, v in OG_EXPECTED.items() if got[k] != v
        ]
        person = node("person")
        first, last = got["profile:first_name"], got["profile:last_name"]
        if f"{first} {last}" != h1_text():
            problems.append(f"profile names {first!r} {last!r} do not spell the h1 {h1_text()!r}")
        if (person.get("givenName"), person.get("familyName")) != (first, last):
            problems.append("profile:first_name/last_name differ from Person givenName/familyName")
        if got["og:site_name"] != node("website").get("name"):
            problems.append("og:site_name differs from the WebSite node's name")
        if page.lang and not got["og:locale"].lower().startswith(page.lang.lower()):
            problems.append(f"og:locale {got['og:locale']!r} is not <html lang={page.lang}>")
        report(self, "Open Graph", problems)

    def test_twitter_set_is_complete_and_matches_open_graph(self):
        got = {k: meta_one("name", k) for k in TWITTER_REQUIRED}
        problems = [f"{k} is missing or empty" for k, v in got.items() if not (v or "").strip()]
        if got["twitter:card"] != "summary_large_image":
            problems.append(f"twitter:card is {got['twitter:card']!r}, not summary_large_image")
        if got["twitter:image"] != meta_one("property", "og:image"):
            problems.append("twitter:image differs from og:image")
        if got["twitter:image:alt"] != meta_one("property", "og:image:alt"):
            problems.append("twitter:image:alt differs from og:image:alt")
        links_x = any(refs.host_of(a.get("href", "")) in X_HOSTS for a in facts().anchors)
        for key in ("twitter:site", "twitter:creator"):
            if meta_one("name", key) is not None and not links_x:
                problems.append(f"{key} is set, but the page links no X account")
        report(self, "Twitter card", problems)

    def test_card_image_is_a_small_1200x630_png_on_the_site(self):
        url = meta_one("property", "og:image") or ""
        path, why = site_file(url)
        if path is None:
            self.fail(f"og:image {url!r}: {why}")
        data = path.read_bytes()
        problems = []
        size = svgcheck.png_size(data)
        if size != CARD_SIZE:
            problems.append(f"{rel(path)} is {size or 'not a PNG'}, not {CARD_SIZE}")
        if len(data) > CARD_MAX_BYTES:
            problems.append(f"{rel(path)} is {len(data):,} bytes, over {CARD_MAX_BYTES:,}")
        if not rel(path).startswith("public/img/og/"):
            problems.append(f"{rel(path)} is not under public/img/og/")
        report(self, "social card image", problems)


class StructuredDataTest(unittest.TestCase):
    def test_graph_ids_are_unique_and_every_reference_resolves(self):
        blocks = json_ld_blocks(facts())
        ids, refs_seen, problems = [], [], []
        for _, key, value, parent in walk(blocks):
            if key == "@id" and isinstance(value, str):
                (refs_seen if set(parent) == {"@id"} else ids).append(value)
        twice = sorted({i for i in ids if ids.count(i) > 1})
        problems += [f"@id {i!r} is defined twice" for i in twice]
        problems += [f"reference {r!r} names no node" for r in refs_seen if r not in ids]
        base = canonical() + "#"
        problems += [f"@id {i!r} is not under {base!r}" for i in ids if not i.startswith(base)]
        report(self, "JSON-LD @id graph", problems)

    def test_profile_page_ties_the_site_person_and_card_together(self):
        page, site = node("profilepage"), node("website")
        problems = []
        types = {"website": "WebSite", "profilepage": "ProfilePage", "person": "Person"}
        problems += [
            f"#{k} is a {node(k).get('@type')!r}, not a {t}"
            for k, t in types.items()
            if node(k).get("@type") != t
        ]
        links = {"isPartOf": "website", "mainEntity": "person"}
        for key, target in links.items():
            if page.get(key) != {"@id": canonical() + "#" + target}:
                problems.append(f"ProfilePage {key} {page.get(key)!r} is not a #{target} reference")
        image = resolve_ref(page.get("primaryImageOfPage"))
        card = meta_one("property", "og:image")
        if not image or image.get("@type") != "ImageObject":
            problems.append("ProfilePage primaryImageOfPage is not an ImageObject")
        else:
            for key in ("url", "contentUrl"):
                if image.get(key) != card:
                    problems.append(f"primaryImageOfPage {key} {image.get(key)!r} is not og:image")
            if (image.get("width"), image.get("height")) != CARD_SIZE:
                problems.append(f"primaryImageOfPage is {image.get('width')}x{image.get('height')}")
        lang = facts().lang
        for name, item in (("ProfilePage", page), ("WebSite", site)):
            if item.get("inLanguage") != lang:
                problems.append(f"{name} inLanguage {item.get('inLanguage')!r} is not {lang!r}")
        if page.get("dateModified") != sitemap_lastmod():
            problems.append(f"dateModified {page.get('dateModified')!r} is not the sitemap lastmod")
        if page.get("name") is not None and page["name"] != facts().title.strip():
            problems.append(f"ProfilePage name {page['name']!r} is not the <title>")
        report(self, "ProfilePage", problems)

    def test_person_carries_identity_work_and_education(self):
        person = node("person")
        required = ("name", "givenName", "familyName", "jobTitle", "description", "url", "image")
        problems = [f"Person has no {key}" for key in required if not person.get(key)]
        if person.get("name") != h1_text():
            problems.append(f"Person name {person.get('name')!r} is not the h1 {h1_text()!r}")
        image = resolve_ref(person.get("image"))
        image_url = image.get("contentUrl") if isinstance(image, dict) else person.get("image")
        if site_file(image_url or "")[0] is None:
            problems.append(f"Person image {image_url!r} is not a file on the site")
        employer = resolve_ref(person.get("worksFor")) or {}
        if not any("wikipedia.org/wiki/" in s for s in as_list(employer.get("sameAs"))):
            problems.append("worksFor needs a Wikipedia sameAs")
        schools = [resolve_ref(s) or {} for s in as_list(person.get("alumniOf"))]
        if not schools:
            problems.append("Person has no alumniOf")
        for school in schools:
            same = as_list(school.get("sameAs"))
            if not any("wikipedia.org/wiki/" in s for s in same) or not any(
                "wikipedia" not in s for s in same
            ):
                problems.append(f"{school.get('name')!r} needs official and Wikipedia sameAs")
        if not resolve_ref(person.get("hasOccupation")):
            problems.append("Person has no hasOccupation")
        for key in ("knowsAbout", "knowsLanguage"):
            if not as_list(person.get(key)):
                problems.append(f"Person has no {key}")
        report(self, "Person", problems)

    def test_each_degree_on_the_page_is_a_credential(self):
        degrees = elements.pick_in(
            INDEX,
            lambda tag, attrs, parents: tag == "article"
            and any(a.get("aria-labelledby") == "education" for _, a in parents),
        )
        creds = [resolve_ref(c) or {} for c in as_list(node("person").get("hasCredential"))]
        problems = [] if degrees else ["the page shows no degree under #education"]
        if len(creds) != len(degrees):
            problems.append(f"{len(creds)} hasCredential entries for {len(degrees)} degrees shown")
        for cred in creds:
            name = cred.get("name", "")
            if not any(norm(name) and norm(name) in norm(d.text) for d in degrees):
                problems.append(f"credential {name!r} matches no degree on the page")
        report(self, "hasCredential", problems)

    def test_same_as_lists_exactly_the_profile_links(self):
        same = {refs.norm_link(s) for s in as_list(node("person").get("sameAs"))}
        wanted = external_profiles()
        problems = [f"sameAs lists {u}, which the page never links" for u in sorted(same - wanted)]
        problems += [f"page links profile {u}, missing from sameAs" for u in sorted(wanted - same)]
        report(self, "Person sameAs", problems)

    def test_every_json_ld_fact_is_visible_on_the_page(self):
        text = visible()
        problems = []
        for path, key, value, parent in walk(json_ld_blocks(facts())):
            if key in NOT_FACTS or (key == "name" and parent.get("@type") == "ProfilePage"):
                continue
            for item in as_list(value):
                if not isinstance(item, str):
                    continue
                owned = (str(parent.get("@type")), key, item) in OWNER_FACTS
                if not owned and not shown(item, text):
                    problems.append(f"{path}.{key} {item!r}")
        person = node("person")
        lang = (facts().lang or "").split("-")[0].lower()
        for tag in as_list(person.get("knowsLanguage")):
            owned = ("Person", "knowsLanguage", str(tag)) in OWNER_FACTS
            if str(tag).split("-")[0].lower() != lang and not owned:
                problems.append(f"knowsLanguage {tag!r}: the page states only its own language")
        if person.get("email"):
            address = person["email"].removeprefix("mailto:")
            linked = f"mailto:{address}" in refs.external_hrefs(facts())
            if address.casefold() not in text or not linked:
                problems.append(f"email {person['email']!r} is not shown and linked on the page")
        if person.get("telephone"):
            phones = {re.sub(r"\D", "", p) for p in PHONE.findall(facts().visible_text())}
            digits = re.sub(r"\D", "", person["telephone"])
            if not any(n and digits.endswith(n) for n in phones):
                problems.append(f"telephone {person['telephone']!r} is not shown on the page")
        report(self, "JSON-LD facts that a reader cannot see", problems)


class ManifestTest(unittest.TestCase):
    def test_manifest_is_complete_and_matches_the_page(self):
        data = manifest()
        problems = [
            f"{key} is missing or empty"
            for key in ("name", "short_name", "description", "background_color")
            if not str(data.get(key, "")).strip()
        ]
        expected = {"start_url": "/", "scope": "/", "display": "browser", "lang": facts().lang}
        problems += [
            f"{k} is {data.get(k)!r}, expected {v!r}"
            for k, v in expected.items()
            if data.get(k) != v
        ]
        theme = (meta_one("name", "theme-color") or "").lower()
        if str(data.get("theme_color", "")).lower() != theme:
            problems.append(f"theme_color {data.get('theme_color')!r} is not theme-color {theme!r}")
        if len(str(data.get("short_name", ""))) > 12:
            problems.append(f"short_name {data.get('short_name')!r} is over 12 characters")
        if data.get("description") != meta_one("name", "description"):
            problems.append("description differs from the page's meta description")
        report(self, MANIFEST_HREF, problems)

    def test_manifest_icons_exist_at_their_declared_sizes(self):
        icons = manifest().get("icons")
        problems = [] if isinstance(icons, list) and icons else ["icons is missing or empty"]
        kinds = set()
        for icon in icons if isinstance(icons, list) else []:
            src, sizes, kind = icon.get("src", ""), icon.get("sizes", ""), icon.get("type", "")
            path, why = refs.resolve(src, PUBLIC)
            if path is None:
                problems.append(f"icon {src!r}: {why}")
                continue
            kinds.add(kind)
            if kind == "image/svg+xml" and sizes != "any":
                problems.append(f"SVG icon {src!r} has sizes {sizes!r}, expected 'any'")
            if kind == "image/png":
                size = svgcheck.png_size(path.read_bytes())
                if not size or sizes != f"{size[0]}x{size[1]}":
                    problems.append(f"PNG icon {src!r} declares {sizes!r}, the file is {size}")
        problems += [f"no {k} icon" for k in ("image/svg+xml", "image/png") if k not in kinds]
        report(self, "manifest icons", problems)

    def test_manifest_is_served_with_its_media_type(self):
        text = read_text(HEADERS_FILE, "Cloudflare Pages reads headers from public/_headers")
        rules = [r for r in hdr.parse(text).rules if r.pattern == MANIFEST_HREF]
        value = rules[0].value("content-type") if rules else None
        if value != "application/manifest+json":
            self.fail(f"_headers types {MANIFEST_HREF} as {value!r}, not application/manifest+json")


class RootFilesTest(unittest.TestCase):
    def test_sitemap_lastmod_is_a_real_date_no_older_than_the_page(self):
        stamp = sitemap_lastmod()
        if not stamp or not W3C_DAY.match(stamp):
            self.fail(f"{rel(SITEMAP)} needs one <url> with a YYYY-MM-DD <lastmod>, has {stamp!r}")
        day = date.fromisoformat(stamp)
        if day > latest_today():
            self.fail(f"<lastmod> {stamp} is in the future")
        newest, why = newest_author_date(INDEX)
        if newest is None:
            self.skipTest(f"cannot compare <lastmod> with the page's history: {why}")
        if day < newest:
            self.fail(f"<lastmod> {stamp} is older than the last change to {rel(INDEX)} ({newest})")

    def test_sitemap_lists_the_card_image(self):
        urls = sitemap_urls()
        images = [
            i.findtext("image:loc", "", SITEMAP_NS)
            for u in urls
            for i in u.findall("image:image", SITEMAP_NS)
        ]
        if images != [meta_one("property", "og:image")]:
            self.fail(f"sitemap image:loc values are {images}, expected only og:image")

    def test_robots_points_at_the_sitemap_and_has_a_real_date(self):
        text = read_text(ROBOTS, "crawlers read robots.txt")
        lines = [
            line.split(":", 1)[1].strip()
            for line in text.splitlines()
            if line.lower().startswith("sitemap:")
        ]
        problems = []
        if lines != [canonical() + "sitemap.xml"]:
            problems.append(f"Sitemap lines are {lines}, expected [{canonical()}sitemap.xml]")
        match = ROBOTS_UPDATED.search(text)
        if not match or not W3C_DAY.match(match.group(1)):
            problems.append("the 'Last updated:' comment has no YYYY-MM-DD date")
        elif date.fromisoformat(match.group(1)) > latest_today():
            problems.append(f"'Last updated: {match.group(1)}' is in the future")
        report(self, rel(ROBOTS), problems)


class LinksAndMarkupTest(unittest.TestCase):
    def test_profile_links_carry_rel_me(self):
        links = profile_links()
        has_me = any("me" in e.attrs.get("rel", "").lower().split() for e in links)
        problems = [] if has_me else ["no link carries rel=me"]
        for e in links:
            href = e.attrs.get("href", "")
            if not is_own_page(href) and "me" not in e.attrs.get("rel", "").lower().split():
                problems.append(f"profile link {href!r} has no rel=me")
        report(self, "rel=me", problems)

    def test_new_tab_links_keep_noopener(self):
        bad = [
            a.get("href")
            for a in facts().anchors
            if a.get("target", "").lower() == "_blank"
            and "noopener" not in a.get("rel", "").lower().split()
        ]
        report(self, 'target="_blank" links without rel="noopener"', bad)

    def test_main_sections_have_stable_jump_link_ids(self):
        labelled = {
            e.attrs.get("aria-labelledby")
            for e in elements.pick_in(INDEX, lambda tag, attrs, parents: tag == "section")
        }
        problems = [f"#{i} is missing" for i in SECTION_IDS if i not in facts().ids]
        problems += [f"#{i} labels no <section>" for i in SECTION_IDS if i not in labelled]
        report(self, "section ids", problems)

    def test_images_have_alt_size_async_decoding_and_eager_loading(self):
        problems = []
        for attrs in facts().images:
            src = attrs.get("src", "")
            if "alt" not in attrs:
                problems.append(f"{src}: no alt attribute")
            if not (attrs.get("width", "").isdigit() and attrs.get("height", "").isdigit()):
                problems.append(f"{src}: no integer width and height")
            if attrs.get("decoding") != "async":
                problems.append(f"{src}: decoding is {attrs.get('decoding')!r}, expected 'async'")
            # Each logo is under 7 KB, and a lazy one can be missing from a full-page capture.
            if attrs.get("loading") == "lazy":
                problems.append(f"{src}: loading='lazy'; the logos load eagerly")
        report(self, "images", problems)

    def test_no_new_render_blocking_resources(self):
        page = facts()
        sheets = [
            urlsplit(a.get("href", "")).path
            for a in page.links
            if "stylesheet" in a.get("rel", "").lower().split()
        ]
        expected = ["css/resume.css"]
        problems = [] if sheets == expected else [f"stylesheets are {sheets}, expected {expected}"]
        problems += [
            f"<script src={s.attrs['src']!r}> blocks the parser (add async or defer)"
            for s in page.scripts
            if s.attrs.get("src") and "async" not in s.attrs and "defer" not in s.attrs
        ]
        report(self, "render-blocking resources", problems)

    def test_no_github_link_in_the_pages_json_ld_or_llms_txt(self):
        sources = []
        for path in public_files(".html", ".htm"):
            sources.append((rel(path), read_text(path, "page the site serves")))
            blocks = json_ld_blocks(facts(path))
            sources += [(f"{rel(path)} JSON-LD", json.dumps(b)) for b in blocks]
        sources.append((rel(LLMS), read_text(LLMS, "llms.txt describes the site to AI crawlers")))
        problems = [
            f"{where}: {m.group(0)}" for where, text in sources for m in GITHUB.finditer(text)
        ]
        report(self, "GitHub links the owner forbids", problems)


class GithubPatternSelfTest(unittest.TestCase):
    def test_pattern_matches_every_github_host_and_nothing_else(self):
        for url in (
            "https://github.com/u",
            "https://GIST.github.com/u",
            "https://u.github.io/",
            "https://raw.githubusercontent.com/u/r/f",
        ):
            with self.subTest(url):
                self.assertRegex(url, GITHUB)
        self.assertNotRegex("https://www.linkedin.com/in/chenyang", GITHUB)


if __name__ == "__main__":
    unittest.main()
