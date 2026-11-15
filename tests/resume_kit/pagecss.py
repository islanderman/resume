"""The stylesheet a page really applies: linked files in order, then inline <style> blocks."""

__unittest = True  # keeps helper frames out of unittest failure reports

from . import cssscan, htmlfacts, refs
from .common import INDEX, input_problem, read_text


def page_sheet(index=INDEX):
    """One merged Sheet; a <link media> wraps its file's rules so print-only CSS stays print-only."""
    facts = htmlfacts.page(index)
    rules, queries, linked = [], [], 0

    def add(text, media=""):
        nonlocal linked
        sheet = cssscan.parse(text)
        queries.extend(sheet.media_queries)
        if media:
            queries.append(media)
        for rule in sheet.rules:
            rules.append(
                cssscan.Rule(
                    (media,) + rule.media if media else rule.media, rule.selector, rule.decls
                )
            )

    for attrs in facts.links:
        href = attrs.get("href", "")
        if "stylesheet" in attrs.get("rel", "").lower().split() and refs.kind(href) == "local":
            path, why = refs.resolve(href, index.parent)
            if path is None:
                continue
            linked += 1
            add(read_text(path, "stylesheet"), attrs.get("media", "").strip())
    for style in facts.styles:
        linked += 1
        add(style.text, style.attrs.get("media", "").strip())
    if not linked:
        raise input_problem(
            "no stylesheet is linked from index.html (or the linked file is missing)"
        )
    return cssscan.Sheet(rules, queries)
