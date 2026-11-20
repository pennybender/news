"""Fetch every feed and build the website.

    python -m news.build --out site --state state

GitHub Actions runs this on a schedule (see .github/workflows/update.yml). It loads the previous run's stories
from the state folder (kept between runs by the Actions cache), adds new ones with their full text, dedupes,
drops old ones, and writes site/ = the app + data/. The state folder is then updated for the next run.
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import lxml.html

from .config import ROOT, load_config
from .ranking import assign_clusters
from .reader import add_full_text
from .sources import HEADERS, apply_filters, fetch_source


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def story_id(url):
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def client():
    return httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True)


def _pull(src):
    with client() as c:
        try:
            return src, fetch_source(src, c), None
        except Exception as e:  # one bad feed must never stop the others
            return src, [], f"{type(e).__name__}: {e}"[:300]


def load_state(state):
    path = Path(state) / "articles.json" if state else None
    if not path or not path.exists():
        print("No previous stories — starting fresh.")
        return []
    try:
        return json.loads(path.read_text()).get("articles", [])
    except Exception as e:
        print(f"Couldn't read previous stories ({e}) — starting fresh.")
        return []


def merge(cfg, previous, results, full_text=True):
    """Add fetched stories to the previous set. Returns (articles, status, texts) where texts maps
    id -> reader HTML for the new stories."""
    by_id = {a["id"]: a for a in previous}
    new, status, contents = [], [], {}
    for src, stories, err in results:
        added = 0
        for s in stories:
            sid = story_id(s["url"])
            s = dict(s)
            contents[sid] = s.pop("content", "")
            if sid in by_id:
                continue
            a = {"id": sid, "source": src["name"], "section": src["section"], "long_read": src["long_read"],
                 "paywalled": src["paywalled"], "has_text": False, "fetched": now_iso(), **s}
            by_id[sid] = a
            new.append(a)
            added += 1
        status.append({"source": src["name"], "ok": err is None, "found": len(stories), "new": added, "error": err})

    s = cfg["settings"]
    now = datetime.now(timezone.utc)
    # a source removed from feeds.toml leaves straight away; keep_days can be set per source
    cutoffs = {src["name"]: (now - timedelta(days=src.get("keep_days", s["keep_days"]))).isoformat()
               for src in cfg["sources"]}
    keep = lambda a: a["source"] in cutoffs and a["published"] >= cutoffs[a["source"]]
    articles = [a for a in by_id.values() if keep(a)]
    srcs = {src["name"]: src for src in cfg["sources"]}
    allowed = {a["id"] for name, src in srcs.items()
               for a in apply_filters(src, [x for x in articles if x["source"] == name])}
    articles = [a for a in articles if a["id"] in allowed]
    new = [a for a in new if keep(a)]
    assign_clusters(articles, new, s["dedupe_threshold"])
    texts, text_stats = {}, {}
    if full_text:
        # new stories, plus older ones that never got text under earlier rules (each gets one more try)
        new_ids = {a["id"] for a in new}
        candidates = new + [a for a in articles if a["id"] not in new_ids and not a.get("has_text")
                            and not a.get("text_tried")]
        texts, text_stats = add_full_text(candidates, contents, client)
    articles.sort(key=lambda a: a["published"], reverse=True)
    merge.text_stats = text_stats
    return articles, status, texts


def write_site(cfg, articles, status, texts, out, state=None):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "web", out)
    text_dir = out / "data" / "a"
    text_dir.mkdir(parents=True)

    # reader texts: carry over the ones still in the paper, add the new ones
    keep = {a["id"] for a in articles if a.get("has_text")}
    old_dir = Path(state) / "a" if state else None
    if old_dir and old_dir.exists():
        for f in old_dir.glob("*.json"):
            if f.stem in keep and f.stem not in texts:
                shutil.copy2(f, text_dir / f.name)
    for aid, html in texts.items():
        (text_dir / f"{aid}.json").write_text(json.dumps({"id": aid, "html": html}, ensure_ascii=False))
    for a in articles:  # a text that went missing means no reader view, not a broken one
        if a.get("has_text") and not (text_dir / f"{a['id']}.json").exists():
            a["has_text"] = False

    write_search_index(text_dir, out / "data" / "search.json")

    s = cfg["settings"]
    payload = {
        "generated": now_iso(),
        "sections": cfg["sections"],
        "sources": {src["name"]: {"weight": src["weight"]} for src in cfg["sources"]},
        "settings": {"front_page_size": s["front_page_size"], "max_per_section": s["max_per_section"]},
        "status": status,
        "articles": articles,
    }
    (out / "data" / "articles.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    if state:  # the next run starts from exactly what was published
        state = Path(state)
        if state.exists():
            shutil.rmtree(state)
        shutil.copytree(out / "data", state)
    return payload


WORD = re.compile(r"[a-z0-9][a-z0-9'\-]{2,}")


def write_search_index(text_dir, path, max_words=800):
    """id -> the distinct words in the article's full text, so the app can search inside articles
    without downloading every one. Loaded only when you open Search."""
    index = {}
    for f in text_dir.glob("*.json"):
        try:
            html = json.loads(f.read_text())["html"]
            text = lxml.html.fromstring(f"<div>{html}</div>").text_content().lower()
        except Exception:
            continue
        seen = dict.fromkeys(w.strip("'-") for w in WORD.findall(text))
        index[f.stem] = " ".join(list(seen)[:max_words])
    path.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site")
    ap.add_argument("--state", default="state", help="folder holding the previous run's data")
    ap.add_argument("--no-full-text", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config()
    previous = load_state(args.state)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_pull, cfg["sources"]))
    articles, status, texts = merge(cfg, previous, results, full_text=not args.no_full_text)
    write_site(cfg, articles, status, texts, args.out, args.state)

    width = max(len(x["source"]) for x in status)
    for x in status:
        if x["ok"]:
            print(f"  ✓ {x['source']:<{width}}  {x['found']:>3} found, {x['new']:>3} new")
        else:
            print(f"  ✗ {x['source']:<{width}}  {x['error']}")
    ok = sum(x["ok"] for x in status)
    with_text = sum(1 for a in articles if a.get("has_text"))
    stats = getattr(merge, "text_stats", {})
    if stats:
        print("\nReader text this run (feed = from the feed, page = extracted, short/failed = opens the website):")
        for name, st in sorted(stats.items()):
            print(f"  {name:<{width}}  " + ", ".join(f"{k} {v}" for k, v in st.items() if v))
    readable = {}
    for a in articles:
        r = readable.setdefault(a["source"], [0, 0])
        r[0] += bool(a.get("has_text")); r[1] += 1
    print("\nReadable in the app, by source:")
    for name, (n, total) in sorted(readable.items()):
        print(f"  {name:<{width}}  {n}/{total}")
    print(f"\n{ok}/{len(status)} sources OK · {len(articles)} stories ({len(previous)} carried over) · "
          f"{with_text} readable in the app ({len(texts)} new)")
    return 0 if ok or previous else 1  # only fail the run if nothing at all worked


if __name__ == "__main__":
    sys.exit(main())
