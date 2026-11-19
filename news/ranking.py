"""Dedupe: group stories that several sources cover. (Front-page scoring runs in the app, web/app.js,
because what's already read lives on your phone.)"""
import re
from datetime import datetime, timedelta, timezone

STOP = set("""a an the and or but of to in on for with at by from as is are was were be been it its this that
these those into over after before about than then new says said will can could would should has have had
not no how why what when who which your our their his her they you we he she more most just also""".split())


def tokens(title):
    words = re.findall(r"[a-z0-9']+", title.lower())
    return {w for w in words if len(w) > 2 and w not in STOP}


def similarity(a, b):
    """Overlap coefficient: shared words / words in the shorter headline. Needs 3+ shared words."""
    if not a or not b:
        return 0.0
    shared = len(a & b)
    if shared < 3:
        return 0.0
    return shared / min(len(a), len(b))


def assign_clusters(articles, new, threshold):
    """articles: all stories (dicts). new: the ones just added. Sets 'cluster' on each new story to the
    cluster of a similar story from the last 72 hours, or to its own id."""
    since = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    new_ids = {a["id"] for a in new}
    pool = [(tokens(a["title"]), a["cluster"]) for a in articles
            if a["id"] not in new_ids and a.get("cluster") and a["published"] >= since]
    for a in sorted(new, key=lambda x: x["published"]):
        t = tokens(a["title"])
        best, best_score = a["id"], 0.0
        for pt, cid in pool:
            s = similarity(t, pt)
            if s >= threshold and s > best_score:
                best, best_score = cid, s
        a["cluster"] = best
        pool.append((t, best))
