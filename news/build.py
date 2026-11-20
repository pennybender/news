"""Fetch every feed and build the website.

    python -m news.build --out site --state state

GitHub Actions runs this on a schedule (see .github/workflows/update.yml). It loads the previous run's stories
from the state folder (kept between runs by the Actions cache), adds new ones with their full text, dedupes,
drops old ones, and writes site/ = the app + data/. The state folder is then updated for the next run.
"""
import argparse
import hashlib
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from .config import ROOT, load_config
from .ranking import assign_clusters
from .reader import add_full_text
from .sources import HEADERS, fetch_source


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
            if sid in by_id:
                continue
            s = dict(s)
            contents[sid] = s.pop("content", "")
            a = {"id": sid, "source": src["name"], "section": src["section"], "long_read": src["long_read"],
                 "paywalled": src["paywalled"], "has_text": False, "fetched": now_iso(), **s}
            by_id[sid] = a
            new.append(a)
            added += 1
        status.append({"source": src["name"], "ok": err is None, "found": len(stories), "new": added, "error": err})

    s = cfg["settings"]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=s["keep_days"])).isoformat()
    current = {src["name"] for src in cfg["sources"]}  # a source removed from feeds.toml leaves straight away
    articles = [a for a in by_id.values() if a["published"] >= cutoff and a["source"] in current]
    new = [a for a in new if a["published"] >= cutoff]
    assign_clusters(articles, new, s["dedupe_threshold"])
    texts = add_full_text(new, contents, client) if full_text else {}
    articles.sort(key=lambda a: a["published"], reverse=True)
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
    print(f"\n{ok}/{len(status)} sources OK · {len(articles)} stories ({len(previous)} carried over) · "
          f"{with_text} readable in the app ({len(texts)} new)")
    return 0 if ok or previous else 1  # only fail the run if nothing at all worked


if __name__ == "__main__":
    sys.exit(main())
