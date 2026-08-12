"""
Facebook competitor scraper — calls Apify REST directly (no subprocess,
works on Render). Mirrors the logic in the FSN pipeline's scrape.py but
lives inside the AIM News Desk server so it runs in the cloud.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any


_ACTOR = "apify~facebook-posts-scraper"
_APIFY_BASE = "https://api.apify.com/v2"


# ── Engagement scoring (FSN formula) ──────────────────────────────────────────

def engagement_score(item: dict) -> int:
    return (
        int(item.get("reactions") or 0)
        + int(item.get("shares") or 0) * 3
        + int(item.get("comments") or 0) * 2
    )


# ── Normalization ──────────────────────────────────────────────────────────────

def _parse_iso(s: Any) -> datetime | None:
    if not s:
        return None
    if isinstance(s, (int, float)):
        try:
            return datetime.fromtimestamp(int(s), tz=timezone.utc)
        except (OSError, ValueError):
            return None
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize(raw: dict) -> dict:
    media = raw.get("media") or []
    image_url = ""
    if media and isinstance(media, list):
        m0 = media[0] or {}
        image_url = (
            (m0.get("large_share_image") or {}).get("uri")
            or m0.get("thumbnail")
            or ""
        )
    text = (raw.get("text") or raw.get("postText") or "")[:2000]
    return {
        "url":          raw.get("url") or raw.get("postUrl") or "",
        "text":         text,
        "preview":      text[:160].replace("\n", " "),
        "image_url":    image_url,
        "reactions":    int(raw.get("reactionCount") or 0),
        "comments":     int(raw.get("commentsCount") or 0),
        "shares":       int(raw.get("sharesCount") or 0),
        "published_at": raw.get("time") or raw.get("publishedTime") or "",
        "page_name":    raw.get("pageName") or raw.get("ownerName") or "",
    }


# ── Apify REST helpers ─────────────────────────────────────────────────────────

def start_scan(token: str, page_urls: list[str], days: int = 14,
               limit_per_page: int = 30) -> str:
    """Start an Apify Facebook scrape and return the run_id. Non-blocking."""
    import httpx
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    ) if days > 0 else None
    payload: dict = {
        "startUrls": [{"url": u} for u in page_urls],
        "resultsLimit": limit_per_page,
    }
    if since:
        payload["onlyPostsNewerThan"] = since

    url = f"{_APIFY_BASE}/acts/{_ACTOR}/runs?token={token}"
    r = httpx.post(url, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()["data"]
    return data["id"]


def poll_run(token: str, run_id: str) -> tuple[str, str | None]:
    """Return (status, dataset_id|None). status is an Apify status string."""
    import httpx
    r = httpx.get(f"{_APIFY_BASE}/actor-runs/{run_id}?token={token}", timeout=15)
    r.raise_for_status()
    d = r.json()["data"]
    return d["status"], d.get("defaultDatasetId")


def fetch_results(token: str, dataset_id: str,
                  days: int = 14) -> list[dict]:
    """Download, normalize, filter and rank results from a finished run."""
    import httpx
    r = httpx.get(
        f"{_APIFY_BASE}/datasets/{dataset_id}/items?token={token}",
        timeout=60,
    )
    r.raise_for_status()
    raw_items: list[dict] = r.json()

    normalized = []
    for raw in raw_items:
        try:
            normalized.append(_normalize(raw))
        except Exception:
            pass

    # Date filter
    if days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        kept = []
        for it in normalized:
            ts = _parse_iso(it.get("published_at"))
            if ts is not None and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts is None or ts >= cutoff:
                kept.append(it)
        normalized = kept

    # Score and rank
    for it in normalized:
        it["engagement_score"] = engagement_score(it)
    normalized.sort(key=lambda x: x["engagement_score"], reverse=True)

    return normalized
