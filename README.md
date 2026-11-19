# News

A personal morning paper built from RSS feeds: Tech, Science, Money, Letters & Ideas, and Sea.
Nothing runs on your own computer. A GitHub Action fetches the feeds every 30 minutes and publishes the app to
GitHub Pages, so it works anywhere. What you've read and saved is kept on your phone.

## One-time setup

1. Create an empty **public** repo called `news` on GitHub (free GitHub Pages needs a public repo) and push this folder to it.
2. On the repo, go to **Settings → Pages → Build and deployment → Source** and choose **GitHub Actions**.
3. Go to the **Actions** tab, open **Update news** and click **Run workflow** (it also runs on every push).
4. After about a minute, open `https://<your-username>.github.io/news/` on your iPhone in Safari, then
   **Share → Add to Home Screen**.

From then on it updates itself. The first run starts with an empty paper and fills from whatever the feeds have now.

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

### AFR

AFR has no RSS feed. `news/sources.py` includes an `afr` adapter that scans AFR section pages, but it's switched off.
To try it, add a source with `kind = "afr"` and `pages = ["https://www.afr.com/latest"]`.

## How it works

```
feeds.toml                    sections + sources
news/sources.py               adapters: rss (and an unused afr scraper)   ← add new source kinds here
news/ranking.py               headline-similarity dedupe
news/build.py                 fetch → merge with the live site's stories → dedupe → prune → write site/
web/                          the app (HTML/CSS/JS, no build step) + offline support
.github/workflows/update.yml  runs build.py every 30 min and deploys to Pages
```

There's no database. Each run downloads the current `data/articles.json` from the live site, adds new stories,
drops ones older than `keep_days`, and publishes again. The front-page ranking runs in the app, so it can skip
what you've already read. Score = section weight × source weight × freshness × a boost when several sources cover a story.

**Note:** the repo and site are public. The site holds only headlines and links from public feeds. Your reads and saves never leave your phone.

## Ideas for next versions

- AI one-line summaries and a daily brief (an extra step in `build.py`, with an API key as a repo secret)
- "Hype check" notes on science stories, and DOI → paper links
- BOM coastal forecast card in the Sea section
- Sync saves between devices (e.g. via a gist), or move to a Raspberry Pi server later
- Weekly digest of saved stories
