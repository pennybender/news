"""Fetch every feed and build the website.

    python -m news.build --out site [--previous URL_OR_PATH_TO_OLD_articles.json]

GitHub Actions runs this on a schedule (see .github/workflows/update.yml). It loads the stories from the
last published site, adds new ones, dedupes, drops old ones, and writes site/ = the app + data/articles.json.
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
from .sources import USER_AGENT, fetch_source


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def story_id(url):
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def _client():
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)


def _pull(src):
    with _client() as client:
        try:
            return src, fetch_source(src, client), None
        except Exception as e:  # one bad feed must never stop the others
            return src, [], f"{type(e).__name__}: {e}"[:300]


def load_previous(where):
    if not where:
        return []
    try:
        if where.startswith("http"):
            with _client() as c:
                r = c.get(where)
                if r.status_code == 404:
                    print("No previous site yet — starting fresh.")
                    return []
                r.raise_for_status()
                data = r.json()
        else:
            data = json.loads(Path(where).read_text())
        return data.get("articles", [])
    except Exception as e:
        print(f"Couldn't load previous stories ({e}) — starting fresh.")
        return []


def merge(cfg, previous, results):
    """Add fetched stories to the previous set; returns (articles, status)."""
    by_id = {a["id"]: a for a in previous}
    new, status = [], []
    for src, stories, err in results:
        added = 0
        for s in stories:
            sid = story_id(s["url"])
            if sid in by_id:
                continue
            a = {"id": sid, "source": src["name"], "section": src["section"],
                 "long_read": src["long_read"], "paywalled": src["paywalled"], "fetched": now_iso(), **s}
            by_id[sid] = a
            new.append(a)
            added += 1
        status.append({"source": src["name"], "ok": err is None, "found": len(stories), "new": added, "error": err})

    s = cfg["settings"]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=s["keep_days"])).isoformat()
    articles = [a for a in by_id.values() if a["published"] >= cutoff]
    new = [a for a in new if a["published"] >= cutoff]
    assign_clusters(articles, new, s["dedupe_threshold"])
    articles.sort(key=lambda a: a["published"], reverse=True)
    return articles, status


def write_site(cfg, articles, status, out):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "web", out)
    (out / "data").mkdir(exist_ok=True)
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
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site")
    ap.add_argument("--previous", help="URL or path of the last articles.json")
    args = ap.parse_args(argv)

    cfg = load_config()
    previous = load_previous(args.previous)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_pull, cfg["sources"]))
    articles, status = merge(cfg, previous, results)
    write_site(cfg, articles, status, args.out)

    width = max(len(x["source"]) for x in status)
    for x in status:
        if x["ok"]:
            print(f"  ✓ {x['source']:<{width}}  {x['found']:>3} found, {x['new']:>3} new")
        else:
            print(f"  ✗ {x['source']:<{width}}  {x['error']}")
    ok = sum(x["ok"] for x in status)
    print(f"\n{ok}/{len(status)} sources OK · {len(articles)} stories in the paper ({len(previous)} carried over)")
    return 0 if ok or previous else 1  # only fail the run if nothing at all worked


if __name__ == "__main__":
    sys.exit(main())
