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

FEED_MIN_WORDS = 60      # a feed's full text this long counts (short blog posts are fine)
PAGE_MIN_WORDS = 120     # an extracted page shorter than this is probably not the article
MAX_FETCHES = 60         # cap page fetches per run so a busy run stays quick
TEASER = re.compile(r"(\[?(…|\.\.\.)\]?|read more|continue reading|keep reading|the post .* appeared first)\W*$", re.I)

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
        for img in list(doc.iter("img")):  # drop email tracking pixels and spacers
            if any((img.get(k) or "").strip() in {"0", "1", "2", "1px", "0px"} for k in ("width", "height")):
                img.drop_tree()
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


def _is_teaser(html):
    text = lxml.html.fromstring(f"<div>{html}</div>").text_content().strip() if html else ""
    return not text or bool(TEASER.search(text[-120:]))


def add_full_text(candidates, contents, client_factory):
    """candidates: story dicts still lacking text (mutated: has_text, words, text_tried).
    contents: id -> HTML the feed supplied this run. Returns (id -> cleaned HTML, per-source stats)."""
    out, to_fetch, stats = {}, [], {}

    def note(a, outcome):
        st = stats.setdefault(a["source"], {"feed": 0, "page": 0, "short": 0, "failed": 0, "skipped": 0})
        st[outcome] += 1

    for a in candidates:
        if a.get("paywalled"):
            continue
        feed_html = contents.get(a["id"], "")
        if word_count(feed_html) >= FEED_MIN_WORDS and not _is_teaser(feed_html):
            out[a["id"]] = clean(feed_html, a["url"])
            note(a, "feed")
        else:
            to_fetch.append(a)

    def fetch(a):
        with client_factory() as c:
            try:
                return a, clean(extract_page(a["url"], c), a["url"]), None
            except Exception as e:
                return a, "", type(e).__name__

    for a in to_fetch[MAX_FETCHES:]:
        note(a, "skipped")  # tried again next run
    with ThreadPoolExecutor(max_workers=8) as pool:
        for a, html, err in pool.map(fetch, to_fetch[:MAX_FETCHES]):
            a["text_tried"] = True
            if err or not html:
                note(a, "failed")
            elif word_count(html) < PAGE_MIN_WORDS:
                note(a, "short")
            else:
                out[a["id"]] = html
                note(a, "page")

    by_id = {a["id"]: a for a in candidates}
    for aid, html in out.items():
        by_id[aid]["has_text"] = True
        by_id[aid]["text_tried"] = True
        by_id[aid]["words"] = word_count(html)
    return out, stats
