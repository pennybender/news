"""Source adapters. Each takes a source dict + httpx client and returns a list of story dicts:
{url, title, summary, author, image, words, published (ISO UTC)}
Add a new kind by writing a function and registering it in ADAPTERS.
"""
import calendar
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import feedparser
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (personal RSS reader)"
HEADERS = {
    "User-Agent": USER_AGENT,
    # some sites (New Scientist) refuse requests that don't say they accept feeds
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.8",
}


def _clean(html, limit=320):
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def _word_count(html):
    if not html:
        return 0
    return len(BeautifulSoup(html, "html.parser").get_text(" ").split())


def _iso(struct_time):
    if not struct_time:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    return datetime.fromtimestamp(calendar.timegm(struct_time), timezone.utc).isoformat(timespec="seconds")


def _image(entry):
    for key in ("media_content", "media_thumbnail"):
        for m in entry.get(key, []) or []:
            if m.get("url"):
                return m["url"]
    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image"):
            return link.get("href", "")
    html = (entry.get("content") or [{}])[0].get("value", "") or entry.get("summary", "")
    m = re.search(r'<img[^>]+src="([^"]+)"', html or "")
    return m.group(1) if m else ""


def fetch_rss(src, client):
    resp = client.get(src["url"])
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"Could not parse feed: {feed.bozo_exception}")
    stories = []
    for e in feed.entries[: src["max_items"]]:
        url = e.get("link")
        title = _clean(e.get("title", ""), 300)
        if not url or not title:
            continue
        full = (e.get("content") or [{}])[0].get("value", "")
        stories.append({
            "url": url,
            "title": title,
            "summary": _clean(e.get("summary", "") or full),
            "author": e.get("author", "") or "",
            "image": _image(e),
            "words": _word_count(full),
            "published": _iso(e.get("published_parsed") or e.get("updated_parsed")),
            "content": full or e.get("summary", ""),  # used for the reader view, not stored in the feed list
        })
    return stories


# AFR article URLs end like  /some-headline-20251118-p5abcd
AFR_URL = re.compile(r"^/[a-z0-9\-/]+-(\d{8})-p5[a-z0-9]{4}$")


def fetch_afr(src, client):
    """AFR publishes no RSS. Scan section pages for article links and use the link text as the headline."""
    seen, stories = set(), []
    for page in src.get("pages", ["https://www.afr.com/latest"]):
        resp = client.get(page)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].split("?")[0]
            path = href.replace("https://www.afr.com", "")
            m = AFR_URL.match(path)
            if not m or path in seen:
                continue
            heading = a.find(["h1", "h2", "h3", "h4"])
            title = (heading or a).get_text(" ", strip=True)
            if len(title) < 20:
                continue
            seen.add(path)
            # The summary is often a sibling <p> in the same card
            card = a.find_parent(["article", "div"])
            p = card.find("p") if card else None
            date = datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=timezone.utc)
            # URL carries only the date; keep page order as a rough freshness signal
            published = date.replace(hour=12, minute=59 - min(len(stories), 59))
            if published > datetime.now(timezone.utc):
                published = datetime.now(timezone.utc)
            stories.append({
                "url": urljoin("https://www.afr.com", path),
                "title": title,
                "summary": _clean(p.get_text(" ", strip=True)) if p else "",
                "author": "",
                "image": "",
                "words": 0,
                "published": published.isoformat(timespec="seconds"),
            })
            if len(stories) >= src["max_items"]:
                return stories
    return stories


ADAPTERS = {"rss": fetch_rss, "afr": fetch_afr}


def fetch_source(src, client):
    return apply_filters(src, ADAPTERS[src["kind"]](src, client))


def apply_filters(src, stories):
    """include / exclude keywords from feeds.toml (also re-applied to stored stories when they change)."""
    text = lambda s: (s["title"] + " " + s.get("summary", "")).lower()
    words = [w.lower() for w in src.get("include", [])]
    if words:
        stories = [s for s in stories if any(w in text(s) for w in words)]
    skip = [w.lower() for w in src.get("exclude", [])]
    if skip:
        stories = [s for s in stories if not any(w in s["title"].lower() for w in skip)]
    # digests: emails that are mostly a list of "READ NOW"-style links rather than one article
    marker = src.get("digest_marker", "").lower()
    if marker:
        limit = src.get("digest_min", 2)
        stories = [s for s in stories if s.get("content", "").lower().count(marker) < limit]
    return stories
