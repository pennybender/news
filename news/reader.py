"""Full text for the in-app reader view.

For each new story: use the feed's own full text if it has it, otherwise fetch the page and pull out the
article body (like Safari Reader). Paywalled sources are skipped. The result is cleaned to a small set of
safe HTML tags and saved as data/a/<id>.json, which the app loads only when you open the story.
"""
import re
from concurrent.futures import ThreadPoolExecutor

import httpx
import lxml.html
import nh3
from readability import Document

MIN_WORDS = 250          # below this a "full text" is really just a teaser
MAX_FETCHES = 60         # cap page fetches per run so a busy run stays quick

TAGS = {"p", "a", "em", "strong", "b", "i", "h2", "h3", "h4", "ul", "ol", "li", "blockquote", "figure",
        "figcaption", "img", "br", "hr", "pre", "code", "sup", "sub", "table", "thead", "tbody", "tr", "th", "td"}
ATTRS = {"a": {"href"}, "img": {"src", "alt"}}


def word_count(html):
    if not html:
        return 0
    return len(lxml.html.fromstring(f"<div>{html}</div>").text_content().split())


def clean(html, base_url):
    """Absolute links, safe tags only, no empty paragraphs, h1 demoted."""
    try:
        doc = lxml.html.fromstring(f"<div>{html}</div>")
        for img in doc.iter("img"):  # lazy-loaded images keep the real URL in data-src
            src = img.get("data-src") or img.get("data-lazy-src")
            if src:
                img.set("src", src)
        doc.make_links_absolute(base_url, resolve_base_href=False)
        for el in doc.iter("h1"):
            el.tag = "h2"
        html = lxml.html.tostring(doc, encoding="unicode")
    except Exception:
        pass
    html = nh3.clean(html, tags=TAGS, attributes=ATTRS, url_schemes={"http", "https"},
                     link_rel="noopener noreferrer")
    html = re.sub(r"<p>\s*(<br>\s*)*</p>", "", html)
    return html.strip()


def extract_page(url, client):
    resp = client.get(url)
    resp.raise_for_status()
    if "html" not in resp.headers.get("content-type", "html"):
        return ""
    return Document(resp.text).summary(html_partial=True)


def add_full_text(new_articles, contents, client_factory):
    """new_articles: story dicts (mutated: has_text, words). contents: id -> feed full-text HTML.
    Returns id -> cleaned HTML."""
    out, to_fetch = {}, []
    for a in new_articles:
        if a.get("paywalled"):
            continue
        feed_html = contents.get(a["id"], "")
        if word_count(feed_html) >= MIN_WORDS:
            out[a["id"]] = clean(feed_html, a["url"])
        else:
            to_fetch.append(a)

    def fetch(a):
        with client_factory() as c:
            try:
                return a["id"], clean(extract_page(a["url"], c), a["url"])
            except Exception:
                return a["id"], ""

    with ThreadPoolExecutor(max_workers=8) as pool:
        for aid, html in pool.map(fetch, to_fetch[:MAX_FETCHES]):
            if html:
                out[aid] = html

    by_id = {a["id"]: a for a in new_articles}
    for aid, html in list(out.items()):
        words = word_count(html)
        if words < MIN_WORDS:
            del out[aid]  # extraction found a stub, not an article
            continue
        by_id[aid]["has_text"] = True
        by_id[aid]["words"] = words
    return out
