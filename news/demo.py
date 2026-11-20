"""Build the site with made-up sample stories, to try the app without fetching anything.
Run:  python -m news.demo --out site     then open site/index.html via any static server.
"""
import argparse
from datetime import datetime, timedelta, timezone

from .build import merge, write_site
from .config import load_config
from .reader import clean, word_count

# (source, hours ago, title, summary, words)  — all SAMPLE text, not real articles
SAMPLES = [
    ("Hacker News", 1.5, "Open-source model runs a full coding agent on a laptop",
     "A walkthrough of running a capable coding assistant locally, with benchmarks on battery life and speed.", 0),
    ("Hackaday", 3, "We tested a coding agent that runs entirely on a laptop",
     "Local models have crossed a usefulness threshold for everyday programming, with caveats.", 1400),
    ("Hacker News", 6, "Why SQLite keeps winning",
     "The case for the world's most deployed database as the default for small apps.", 0),
    ("RTL-SDR", 9, "Battery makers race to commercialise sodium-ion cells",
     "Cheaper chemistry could reshape home storage and small EVs within a few years.", 1200),
    ("Quanta", 4, "The mathematicians mapping the edges of chaos",
     "A decades-old question about turbulent systems is finally yielding to new techniques.", 4200),
    ("Phys.org", 7, "Deep-sea microbes found living off radiation-split water",
     "Communities in ancient rock appear to draw energy from chemistry driven by natural radioactivity.", 0),
    ("Quanta", 2, "Ocean heat records broken again this year",
     "The upper ocean has absorbed more heat than in any year on record, researchers report.", 900),
    ("Phys.org", 5, "Ocean heat records broken again, new analysis finds",
     "Measurements from floats and ships point to another record year.", 600),
    ("arXiv AI", 10, "Reasoning traces as training signal for small language models",
     "We study whether distilled reasoning improves small models on maths and planning tasks.", 0),
    ("Marginal Revolution", 1, "RBA holds rates as economists split on next move",
     "Markets are pricing a long pause while some economists see a cut by mid-year.", 0),
    ("RBA", 2.5, "Statement on monetary policy decision",
     "The Board decided to leave the cash rate target unchanged.", 700),
    ("Noahpinion", 8, "Small business confidence lifts ahead of summer trading",
     "Owners report stronger bookings, but costs remain the main worry.", 0),
    ("Marginal Revolution", 12, "Why do some cities have so many cafés?",
     "Rents, zoning and the economics of the third place.", 500),
    ("Quillette", 5, "In defence of the long novel",
     "Big books ask for patience in an age of fragments. That is exactly their value.", 3800),
    ("Aeon", 14, "What the sea taught the Romantic poets",
     "For Coleridge and Byron, the ocean was a teacher of scale, fear and freedom.", 5200),
    ("The Paris Review", 20, "Notes on rereading Conrad",
     "Returning to Heart of Darkness and The Secret Sharer decades later.", 2600),
    ("Yachting World", 3, "Ten upgrades that make a cruising yacht easier to sail short-handed",
     "From lead-aft lines to a better autopilot, the changes that matter most.", 1800),
    ("Practical Boat Owner", 11, "How to service your winches in an afternoon",
     "A step-by-step guide with the tools and grease you'll need.", 1500),
    ("Yachting World", 22, "Offshore racing fleet takes shape for the summer season",
     "Entries are up, with a strong showing of two-handed crews.", 900),
]


def sample_results(cfg):
    src = {s["name"]: s for s in cfg["sources"]}
    now = datetime.now(timezone.utc)
    grouped = {}
    for i, (name, hrs, title, summary, words) in enumerate(SAMPLES):
        home = src[name].get("url") or src[name].get("pages", ["https://example.com"])[0]
        grouped.setdefault(name, []).append({
            "url": f"{home}#sample-{i}", "title": title, "summary": summary, "author": "", "image": "",
            "words": words, "published": (now - timedelta(hours=hrs)).isoformat(timespec="seconds")})
    return [(s, grouped.get(s["name"], []), None) for s in cfg["sources"]]


SAMPLE_BODY = """<p>This is sample text standing in for the full article, so you can see how the reader view looks.
In the real app this is the story's own text, taken from its feed or from the article page.</p>
<h2>A subheading</h2>
<p>Long paragraphs are set in a comfortable serif at a readable size, with generous line spacing and a narrow
measure so the eye can track easily on a phone. Links like <a href="https://example.com">this one</a> open in Safari.</p>
<blockquote>Pull quotes and block quotes get a quiet rule on the left.</blockquote>
<p>Images in the original article appear at full width, and anything the cleaner doesn't recognise is removed
so pages stay fast and tidy.</p>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site")
    args = ap.parse_args()
    cfg = load_config()
    articles, status, _ = merge(cfg, [], sample_results(cfg), full_text=False)
    texts = {}
    for a in articles:
        if a["words"] and not a["paywalled"]:
            body = clean(SAMPLE_BODY * 3, a["url"])
            texts[a["id"]] = body
            a["has_text"], a["words"] = True, max(a["words"], word_count(body))
    write_site(cfg, articles, status, texts, args.out)
    print(f"Built {args.out}/ with {len(articles)} sample stories ({len(texts)} with reader text).")


if __name__ == "__main__":
    main()
