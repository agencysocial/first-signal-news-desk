"""
Seed RSS and Google News sources for the NYC Topic Pipeline and Competitor
Website Monitor. Called once at startup — idempotent (skips URLs already in DB).
"""
from __future__ import annotations

_SEEDS = [
    # ── NYC Topic Pipeline (excluded from main feed — NYC tab only) ────────────
    {
        "name": "NY Post",
        "type": "rss",
        "url": "https://nypost.com/feed/",
        "category": "NYC",
        "credibility_tier": 3,
        "polling_tier": "standard",
        "show_in_main_feed": False,
    },
    {
        "name": "Gothamist",
        "type": "rss",
        "url": "https://gothamist.com/feed",
        "category": "NYC",
        "credibility_tier": 3,
        "polling_tier": "standard",
        "show_in_main_feed": False,
    },
    {
        "name": "NYC Mayor Office (Google News)",
        "type": "google_news",
        "query": "NYC Mayor Mamdani",
        "category": "NYC",
        "credibility_tier": 2,
        "polling_tier": "priority",
        "show_in_main_feed": False,
    },
    {
        "name": "NYC Politics (Google News)",
        "type": "google_news",
        "query": "New York City politics",
        "category": "NYC",
        "credibility_tier": 2,
        "polling_tier": "standard",
        "show_in_main_feed": False,
    },
    # ── Competitor Website Monitor ─────────────────────────────────────────────
    {
        "name": "Breitbart",
        "type": "rss",
        "url": "https://feeds.feedburner.com/breitbart",
        "category": "Conservative Media",
        "credibility_tier": 4,
        "polling_tier": "standard",
    },
    {
        "name": "Daily Wire",
        "type": "rss",
        "url": "https://feeds.megaphone.fm/dailywire",
        "category": "Conservative Media",
        "credibility_tier": 4,
        "polling_tier": "standard",
    },
    {
        "name": "The Political Insider",
        "type": "rss",
        "url": "https://thepoliticalinsider.com/feed/",
        "category": "Conservative Media",
        "credibility_tier": 4,
        "polling_tier": "standard",
    },
    {
        "name": "Washington Examiner",
        "type": "rss",
        "url": "https://www.washingtonexaminer.com/feeds/",
        "category": "Conservative Media",
        "credibility_tier": 3,
        "polling_tier": "standard",
    },
    {
        "name": "Daily Wire (Google News)",
        "type": "google_news",
        "query": "Daily Wire conservative news",
        "category": "Conservative Media",
        "credibility_tier": 4,
        "polling_tier": "low",
    },
]


def seed_news_sources() -> int:
    """Insert missing seed sources. Safe to call multiple times.
    Returns count of newly added sources."""
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import Source
    from app.collectors.google_news import build_google_news_url

    session = SessionLocal()
    added = 0
    try:
        existing_names = {
            row[0] for row in session.execute(select(Source.name)).all()
        }
        for s in _SEEDS:
            if s["name"] in existing_names:
                continue
            if s["type"] == "google_news":
                url = build_google_news_url(s["query"])
            else:
                url = s["url"]
            src = Source(
                name=s["name"],
                type=s["type"],
                url=url,
                query=s.get("query"),
                category=s["category"],
                credibility_tier=s["credibility_tier"],
                polling_tier=s["polling_tier"],
                enabled=True,
                show_in_main_feed=s.get("show_in_main_feed", True),
            )
            session.add(src)
            added += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return added
