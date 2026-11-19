"""Test every feed without touching the database.  Run:  python -m news.check"""
import httpx

from .config import load_config
from .sources import USER_AGENT, fetch_source


def main():
    cfg = load_config()
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True) as client:
        for src in cfg["sources"]:
            try:
                stories = fetch_source(src, client)
                first = stories[0]["title"][:60] if stories else "(no stories)"
                print(f"✓ {src['name']:<22} {len(stories):>3}  e.g. {first}")
            except Exception as e:
                print(f"✗ {src['name']:<22}  {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
