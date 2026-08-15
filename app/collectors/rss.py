"""
Generic RSS/Atom collector. Google News RSS is just an RSS feed at a search URL,
so app/collectors/google_news.py builds the URL and this same function fetches it --
no separate parser needed.
"""
import gzip
import json
import time
import urllib.request
from datetime import datetime, timezone

import feedparser
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clustering import assign_cluster
from app.config import FEED_FETCH_TIMEOUT_SECONDS
from app.dedup import find_duplicate
from app.models import RawArticle, NormalizedArticle, Source
from app.normalize import canonicalize_url, normalize_headline, compute_hashes

# A generic bot-labeled UA ("AIMNewsDesk/1.0") got blocked with a 403 by at
# least one real source (Politico) that had previously been reachable (if
# malformed) under feedparser's own default UA. RSS feeds are published
# specifically for aggregation, so presenting a standard browser UA to fetch
# a public feed is normal, widely-used practice for feed readers -- this
# isn't bypassing auth or a bot-detection challenge, just avoiding a crude
# UA-string block on an otherwise-public endpoint.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _fetch_feed(url: str, user_agent: str | None = None):
    """feedparser.parse(url) has no built-in network timeout -- it can hang
    on a slow/unresponsive server for as long as the OS socket timeout
    allows (observed: several minutes on Windows, WinError 10060), which
    blocks every other source queued behind it in the same scan. Fetch with
    an explicit bounded timeout, then hand the bytes to feedparser -- it
    never touches the network itself this way.

    user_agent overrides the shared default for one source -- see
    Source.user_agent's docstring for why this needs to be per-source
    rather than one value for every feed.

    Full browser header set is sent because some CDN/WAF setups (e.g. Politico)
    block requests that carry only a UA string without the Accept/Language/etc.
    headers a real browser would send.
    """
    headers = {
        "User-Agent": user_agent or _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        # No Accept-Encoding — urllib doesn't auto-decompress when we set this
        # manually, so compressed responses land as raw bytes that feedparser
        # can't parse (observed: every source showing "not well-formed" at 2:0).
        # Let the server decide; decompress gzip below if it comes back compressed.
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=FEED_FETCH_TIMEOUT_SECONDS) as resp:
        raw_bytes = resp.read()
        encoding = resp.headers.get("Content-Encoding", "")
        if encoding == "gzip" or (raw_bytes[:2] == b"\x1f\x8b"):
            raw_bytes = gzip.decompress(raw_bytes)
        return feedparser.parse(raw_bytes)


def _struct_to_dt(struct_time) -> datetime | None:
    if not struct_time:
        return None
    return datetime.fromtimestamp(time.mktime(struct_time), tz=timezone.utc)


def _entry_to_payload(entry) -> str:
    keys = ("id", "link", "title", "summary", "author", "published", "tags")
    safe = {k: entry.get(k) for k in keys if k in entry}
    return json.dumps(safe, default=str)[:20000]


def collect_source(session: Session, source: Source) -> dict:
    """Fetch one source, insert new raw articles, normalize + dedup each one.
    Never raises -- errors are captured on the source record so one bad feed
    doesn't stop the batch.
    """
    stats = {"fetched": 0, "inserted": 0, "duplicates": 0, "canonical": 0, "error": None}

    try:
        parsed = _fetch_feed(source.url, user_agent=source.user_agent)
    except Exception as exc:  # network / parser failure
        source.last_error = f"fetch failed: {exc}"
        source.last_fetch_at = datetime.now(timezone.utc)
        stats["error"] = str(exc)
        return stats

    entries = getattr(parsed, "entries", [])
    stats["fetched"] = len(entries)

    if parsed.bozo and not entries:
        source.last_error = f"parse failed: {getattr(parsed, 'bozo_exception', 'unknown')}"
        source.last_fetch_at = datetime.now(timezone.utc)
        stats["error"] = source.last_error
        return stats

    for entry in entries:
        raw_url = entry.get("link")
        headline = entry.get("title", "").strip()
        if not raw_url or not headline:
            continue

        already = session.execute(
            select(RawArticle).where(
                RawArticle.source_id == source.id, RawArticle.url == raw_url
            )
        ).scalars().first()
        if already:
            continue  # already collected this exact raw article from this source

        raw = RawArticle(
            source_id=source.id,
            external_id=entry.get("id"),
            url=raw_url,
            headline=headline,
            description=entry.get("summary"),
            author=entry.get("author"),
            published_at=_struct_to_dt(entry.get("published_parsed")),
            raw_payload=_entry_to_payload(entry),
        )
        session.add(raw)
        session.flush()  # assign raw.id

        canonical_url = canonicalize_url(raw_url)
        norm_headline = normalize_headline(headline)
        url_hash, headline_hash, content_hash = compute_hashes(
            canonical_url, norm_headline, raw.description
        )

        dup_of_id, dup_level, dup_score = find_duplicate(
            session,
            canonical_url=canonical_url,
            url_hash=url_hash,
            headline_hash=headline_hash,
            content_hash=content_hash,
            normalized_headline=norm_headline,
        )

        normalized = NormalizedArticle(
            raw_article_id=raw.id,
            source_id=source.id,
            canonical_url=canonical_url,
            url_hash=url_hash,
            normalized_headline=norm_headline,
            headline_hash=headline_hash,
            content_hash=content_hash,
            description=raw.description,
            source_tier=source.credibility_tier,
            published_at=raw.published_at,
            duplicate_of_id=dup_of_id,
            duplicate_level=dup_level,
            duplicate_similarity_score=dup_score,
        )
        session.add(normalized)
        session.flush()  # assign normalized.id before clustering
        assign_cluster(session, normalized, raw_headline=headline)

        stats["inserted"] += 1
        if dup_of_id:
            stats["duplicates"] += 1
        else:
            stats["canonical"] += 1

    source.last_fetch_at = datetime.now(timezone.utc)
    source.last_error = None
    session.commit()
    return stats
