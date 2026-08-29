"""
Twitter/X and Reddit social scanner + article text extractor via Apify REST.
Surfaces viral political content signalling what's about to break on Facebook.
Also provides full article text extraction for AI caption context.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

_APIFY_BASE = "https://api.apify.com/v2"
_TWITTER_ACTOR = "apidojo/tweet-scraper"
_REDDIT_ACTOR  = "trudax/reddit-search-scraper"
_ARTICLE_ACTOR = "apify/article-extractor-smart"

_DEFAULT_TWITTER_QUERIES = [
    "Trump breaking",
    "Congress breaking news",
    "Biden breaking",
    "immigration America First",
    "Republican Democrat breaking",
    "MAGA America First news",
    "Mamdani NYC",
    "Vance breaking",
]
_DEFAULT_REDDIT_SUBS = [
    "politics", "Conservative", "news",
    "PoliticalDiscussion", "Republican",
]


# ── Apify REST helpers ─────────────────────────────────────────────────────────

def _apify_run(token: str, actor: str, payload: dict) -> str:
    import httpx
    r = httpx.post(
        f"{_APIFY_BASE}/acts/{actor}/runs?token={token}",
        json=payload, timeout=30,
    )
    r.raise_for_status()
    return r.json()["data"]["id"]


def _apify_poll(token: str, run_id: str) -> tuple[str, str | None]:
    import httpx
    r = httpx.get(f"{_APIFY_BASE}/actor-runs/{run_id}?token={token}", timeout=15)
    r.raise_for_status()
    d = r.json()["data"]
    return d["status"], d.get("defaultDatasetId")


def _apify_items(token: str, dataset_id: str, limit: int = 200) -> list[dict]:
    import httpx
    r = httpx.get(
        f"{_APIFY_BASE}/datasets/{dataset_id}/items?token={token}&limit={limit}",
        timeout=60,
    )
    r.raise_for_status()
    items = r.json()
    return items if isinstance(items, list) else []


# ── Engagement score (mirrors FB formula) ─────────────────────────────────────

def social_engagement_score(item: dict) -> int:
    return (
        int(item.get("reactions") or 0)
        + int(item.get("shares") or 0) * 3
        + int(item.get("comments") or 0) * 2
    )


# ── Twitter/X ─────────────────────────────────────────────────────────────────

def start_twitter_scan(token: str, queries: list[str] | None = None, hours: int = 24) -> str:
    queries = queries or _DEFAULT_TWITTER_QUERIES
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d")
    return _apify_run(token, _TWITTER_ACTOR, {
        "searchTerms": queries,
        "maxItems": 60,
        "since": since,
        "onlyVerifiedUsers": False,
        "minimumRetweets": 5,
        "minimumLikes": 25,
        "lang": "en",
    })


def _normalize_tweet(raw: dict) -> dict:
    author = raw.get("author") or raw.get("user") or {}
    media = raw.get("extendedEntities") or raw.get("entities") or {}
    media_list = (media.get("media") or [{}])[0] if media.get("media") else {}
    return {
        "platform":     "twitter",
        "url":          raw.get("url") or f"https://twitter.com/i/web/status/{raw.get('id', '')}",
        "text":         (raw.get("text") or raw.get("full_text") or "")[:2000],
        "preview":      (raw.get("text") or raw.get("full_text") or "")[:160].replace("\n", " "),
        "image_url":    media_list.get("media_url_https") or media_list.get("url") or "",
        "reactions":    int(raw.get("likeCount") or raw.get("favorite_count") or 0),
        "comments":     int(raw.get("replyCount") or raw.get("reply_count") or 0),
        "shares":       int(raw.get("retweetCount") or raw.get("retweet_count") or 0),
        "published_at": raw.get("createdAt") or raw.get("created_at") or "",
        "page_name":    author.get("userName") or author.get("screen_name") or "",
        "page_display": author.get("name") or author.get("userName") or "",
    }


# ── Reddit ─────────────────────────────────────────────────────────────────────

def start_reddit_scan(token: str, subreddits: list[str] | None = None, hours: int = 24) -> str:
    subs = subreddits or _DEFAULT_REDDIT_SUBS
    time_filter = "day" if hours <= 24 else "week"
    return _apify_run(token, _REDDIT_ACTOR, {
        "startUrls": [{"url": f"https://www.reddit.com/r/{s}/hot/"} for s in subs],
        "maxItems": 60,
        "time": time_filter,
        "searchType": "link",
    })


def _normalize_reddit(raw: dict) -> dict:
    score   = int(raw.get("score") or raw.get("ups") or 0)
    comments = int(raw.get("numComments") or raw.get("num_comments") or 0)
    sub     = raw.get("subreddit") or raw.get("community") or ""
    return {
        "platform":     "reddit",
        "url":          raw.get("url") or raw.get("permalink") or "",
        "text":         (raw.get("title") or "")[:2000],
        "preview":      (raw.get("title") or "")[:160],
        "image_url":    raw.get("thumbnail") or "",
        "reactions":    score,
        "comments":     comments,
        "shares":       0,
        "published_at": str(raw.get("createdAt") or raw.get("created_utc") or ""),
        "page_name":    f"r/{sub}",
        "page_display": f"r/{sub}",
    }


# ── Unified fetch ──────────────────────────────────────────────────────────────

def fetch_results(token: str, dataset_id: str, platform: str) -> list[dict]:
    raw_items = _apify_items(token, dataset_id)
    normalize = _normalize_tweet if platform == "twitter" else _normalize_reddit
    results = []
    for raw in raw_items:
        try:
            item = normalize(raw)
            item["engagement_score"] = social_engagement_score(item)
            results.append(item)
        except Exception:
            pass
    results.sort(key=lambda x: x["engagement_score"], reverse=True)
    return results


# ── Poll until done or timeout ─────────────────────────────────────────────────

def poll_until_done(token: str, run_id: str, timeout: int = 900) -> tuple[str, str | None]:
    """Poll Apify run until SUCCEEDED/FAILED/ABORTED or timeout. Returns (status, dataset_id)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, dataset_id = _apify_poll(token, run_id)
        if status in ("SUCCEEDED",):
            return status, dataset_id
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            return status, None
        time.sleep(8)
    return "TIMEOUT", None


# ── Article text extraction ────────────────────────────────────────────────────

def extract_article_text(token: str, url: str, timeout: int = 90) -> str | None:
    """Fetch full article body from a URL via Apify article-extractor-smart.
    Returns up to 8000 chars of article text, or None on failure."""
    try:
        run_id = _apify_run(token, _ARTICLE_ACTOR, {
            "startUrls": [{"url": url}],
            "proxyConfiguration": {"useApifyProxy": True},
        })
        status, dataset_id = poll_until_done(token, run_id, timeout=timeout)
        if status == "SUCCEEDED" and dataset_id:
            items = _apify_items(token, dataset_id, limit=1)
            if items:
                text = (
                    items[0].get("text")
                    or items[0].get("article")
                    or items[0].get("body")
                    or ""
                )
                return text[:8000] if text else None
    except Exception:
        pass
    return None
