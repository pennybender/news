# News

A personal morning paper built from RSS feeds: Tech, Science, Money, Letters & Ideas, and Sea.
A GitHub Action fetches the feeds every 30 minutes, pulls out each article's full text for the in-app reader,
and publishes the app to Cloudflare Pages behind a Cloudflare Access login, so only you can open it.
What you've read and saved is kept on your phone.

## One-time setup

1. **Cloudflare API token**: Cloudflare dashboard → My Profile → API Tokens → Create Token → Custom token.
   Give it the permission **Account → Cloudflare Pages → Edit**, then create it and copy the token.
2. **Account ID**: Cloudflare dashboard → Workers & Pages. The Account ID is in the right-hand column (or in the URL).
3. **GitHub secrets**: on the repo, Settings → Secrets and variables → Actions → New repository secret:
   `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.
4. **Run it**: Actions tab → Update news → Run workflow. The log's deploy step prints the site address,
   something like `https://news-xxx.pages.dev`.
5. **Lock it**: Cloudflare Zero Trust → Access → Applications → Add an application → Self-hosted.
   Add two destinations: `news-xxx.pages.dev` and `*.news-xxx.pages.dev` (the second covers per-deploy preview links).
   Add a policy: Action **Allow**, Include **Emails** → your email address. The free Zero Trust plan covers this.
   From then on the site asks for your email and sends a one-time code.
6. On the iPhone, open the address in Safari, log in, then **Share → Add to Home Screen**.

## Views

- **Today**: the 7 best unread stories (at most 2 per section), then each section's top stories.
- **River**: everything from the last 7 days, newest first, with section filters.
- **Long reads**: essays from long-read sources (Quillette, Aeon, Quanta…) or anything over ~2,000 words.
- **Saved**: anything you've starred. Saves stay on the phone even after the story drops out of the feed.

Opening a story marks it read, along with every other source's copy of the same story. Read stories leave the
front page. If any source failed on the last update, it's listed at the bottom of Today.

## Changing sources

Everything is in `feeds.toml`. You can edit it right on github.com (pencil icon); committing triggers a rebuild.

```toml
[[sources]]
name = "The Conversation"
section = "science"
kind = "rss"
url = "https://theconversation.com/au/articles.atom"
weight = 0.8
```

- `weight`: how strongly a source competes for the front page.
- `long_read = true`: also show its stories in Long reads.
- `include = ["word", …]`: keep only matching stories (useful for arXiv).
- `max_items`: cap per update for very busy feeds.

To check feeds from your own computer: `pip install -r requirements.txt` then `python -m news.check`.
To see the app with sample stories: `python -m news.demo --out site && python -m http.server -d site`.
To build for real on your computer: `python -m news.build --out site --state state`.

### AFR

AFR has no RSS feed. `news/sources.py` includes an `afr` adapter that scans AFR section pages, but it's switched off.
To try it, add a source with `kind = "afr"` and `pages = ["https://www.afr.com/latest"]`.

## Reading in the app

Tapping a story opens it in the app's reader view when its full text is available. The text comes from the
feed when the feed includes it, otherwise from the article page (the way Safari Reader works). Paywalled sources
(The Economist) and pages the extractor can't read open on the original site instead. Every reader page has
an "Original ↗" link.

## How it works

```
feeds.toml                    sections + sources
news/sources.py               adapters: rss (and an unused afr scraper)   ← add new source kinds here
news/reader.py                full text for the reader view: feed text or page extraction, cleaned to safe HTML
news/ranking.py               headline-similarity dedupe
news/build.py                 fetch → merge with last run → dedupe → full text → prune → write site/
web/                          the app (HTML/CSS/JS, no build step) + offline support
.github/workflows/update.yml  runs build.py every 30 min and deploys to Cloudflare Pages
```

There's no database. Each run restores the previous run's stories and article texts from the GitHub Actions
cache (never committed to the repo), adds new ones, drops ones older than `keep_days`, deploys, and saves the
state for next time. The front-page ranking runs in the app, so it can skip what you've already read.
Score = section weight × source weight × freshness × a boost when several sources cover a story.

**Privacy:** the code repo is public, but article texts only ever live in the Actions cache and on the
Access-protected site. Your reads and saves never leave your phone.

## Ideas for next versions

- AI one-line summaries and a daily brief (an extra step in `build.py`, with an API key as a repo secret)
- "Hype check" notes on science stories, and DOI → paper links
- BOM coastal forecast card in the Sea section
- Sync saves between devices (e.g. via a gist), or move to a Raspberry Pi server later
- Weekly digest of saved stories
