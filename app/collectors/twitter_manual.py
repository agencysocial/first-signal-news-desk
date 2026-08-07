"""
Manual Twitter/X capture: an operator pastes a tweet URL from their existing
Twitter Lists, and this module fetches it via Twitter's free oEmbed endpoint
(no API key, no per-read billing -- confirmed live against a real tweet
before this was built, see BUILD_STATUS) and runs it through the exact same
normalize -> dedup -> cluster -> score pipeline every RSS article goes
through, so a tweet can merge into an existing cluster's coverage or seed a
new one.

Known oEmbed limits (confirmed against a real request, not assumed):
  - no engagement metrics (likes/RTs/replies) -- same "editorial, not
    data-driven" situation the Facebook scores are already in
  - no time-of-day on the tweet's date, only a rendered "Month DD, YYYY"
    string inside the HTML -- best-effort parsed into published_at (date
    only); detected_at (capture time) is what actually drives freshness/sort
  - single tweet only, no thread or quote-tweet expansion
"""
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clustering import assign_cluster
from app.config import FEED_FETCH_TIMEOUT_SECONDS
from app.dedup import find_duplicate
from app.models import NormalizedArticle, RawArticle, Source, StoryCluster
from app.normalize import canonicalize_url, compute_hashes, normalize_headline

_STATUS_RE = re.compile(
    r"^https?://(?:www\.)?(?:twitter|x)\.com/([A-Za-z0-9_]{1,15})/status/(\d+)", re.I
)
_OEMBED_ENDPOINT = "https://publish.twitter.com/oembed"
# Same UA rationale as app/collectors/rss.py -- a public embed endpoint meant
# for exactly this kind of fetch, not bypassing auth or a bot challenge.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_CREDIBILITY_TIER = 2  # operator hand-picked it off a curated List


class TweetCaptureError(Exception):
    pass


class _TweetHTMLParser(HTMLParser):
    """oEmbed's `html` field looks like:
    <blockquote class="twitter-tweet"><p ...>TEXT</p>&mdash; NAME (@handle)
    <a href="...">Month DD, YYYY</a></blockquote>
    Pull the tweet text out of <p>, and the date out of the trailing <a>.
    convert_charrefs defaults to True, so entities arrive already decoded.
    """

    def __init__(self):
        super().__init__()
        self._in_p = False
        self._in_trailing_a = False
        self._after_p = False
        self.text_parts: list[str] = []
        self.date_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self._in_p = True
        elif tag == "br" and self._in_p:
            self.text_parts.append("\n")
        elif tag == "a" and self._after_p:
            self._in_trailing_a = True

    def handle_endtag(self, tag):
        if tag == "p":
            self._in_p = False
            self._after_p = True
        elif tag == "a":
            self._in_trailing_a = False

    def handle_data(self, data):
        if self._in_p:
            self.text_parts.append(data)
        elif self._in_trailing_a:
            self.date_parts.append(data)

    @property
    def text(self) -> str:
        return "".join(self.text_parts).strip()

    @property
    def date_label(self) -> str:
        return "".join(self.date_parts).strip()


def parse_tweet_url(url: str) -> tuple[str, str]:
    """Returns (screen_name, status_id). Raises TweetCaptureError if the URL
    isn't a recognizable twitter.com/x.com status link."""
    m = _STATUS_RE.match((url or "").strip())
    if not m:
        raise TweetCaptureError(
            "Not a recognizable tweet URL -- expected https://x.com/<handle>/status/<id>"
        )
    return m.group(1), m.group(2)


def _parse_date_label(label: str) -> datetime | None:
    if not label:
        return None
    try:
        return datetime.strptime(label, "%B %d, %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def fetch_tweet_oembed(canonical_status_url: str) -> dict:
    """Calls the free oEmbed endpoint. Raises TweetCaptureError on any
    failure: network error, deleted/protected tweet (404), or a payload we
    can't extract text from."""
    query = urllib.parse.urlencode({"url": canonical_status_url, "omit_script": "true"})
    req = urllib.request.Request(
        f"{_OEMBED_ENDPOINT}?{query}", headers={"User-Agent": _USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=FEED_FETCH_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise TweetCaptureError(
            f"Could not fetch tweet (deleted, protected, or network error): {exc}"
        ) from exc

    parser = _TweetHTMLParser()
    parser.feed(payload.get("html") or "")
    text = parser.text
    if not text:
        raise TweetCaptureError("Tweet fetched but no text could be extracted from it")

    return {
        "author_name": payload.get("author_name") or "Unknown",
        "author_url": payload.get("author_url") or "",
        "text": text,
        "published_at": _parse_date_label(parser.date_label),
    }


def _get_or_create_author_source(session: Session, author_name: str, author_url: str) -> Source:
    source_name = f"{author_name} (X)"
    existing = session.execute(
        select(Source).where(Source.type == "twitter_manual", Source.name == source_name)
    ).scalars().first()
    if existing:
        return existing
    source = Source(
        name=source_name,
        type="twitter_manual",
        url=author_url or f"https://x.com/{urllib.parse.quote(author_name)}",
        category=None,
        credibility_tier=DEFAULT_CREDIBILITY_TIER,
        polling_tier="standard",  # not actually polled -- capture is manual/on-demand
        enabled=True,
    )
    session.add(source)
    session.flush()
    return source


def capture_tweet(session: Session, tweet_url: str) -> StoryCluster:
    """Full capture: validate URL, fetch via oEmbed, ingest through the same
    normalize -> dedup -> cluster pipeline collect_source() uses for RSS.
    Raises TweetCaptureError on any failure (never partially commits)."""
    screen_name, status_id = parse_tweet_url(tweet_url)
    canonical_status_url = f"https://x.com/{screen_name}/status/{status_id}"

    tweet = fetch_tweet_oembed(canonical_status_url)
    source = _get_or_create_author_source(session, tweet["author_name"], tweet["author_url"])

    already = session.execute(
        select(RawArticle).where(
            RawArticle.source_id == source.id, RawArticle.url == canonical_status_url
        )
    ).scalars().first()
    if already:
        raise TweetCaptureError("This tweet has already been captured")

    raw = RawArticle(
        source_id=source.id,
        external_id=status_id,
        url=canonical_status_url,
        headline=tweet["text"],
        description=tweet["text"],
        author=tweet["author_name"],
        published_at=tweet["published_at"],
        raw_payload=json.dumps(tweet, default=str)[:20000],
    )
    session.add(raw)
    session.flush()

    canonical_url = canonicalize_url(canonical_status_url)
    norm_headline = normalize_headline(tweet["text"])
    url_hash, headline_hash, content_hash = compute_hashes(canonical_url, norm_headline, raw.description)

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
    session.flush()

    cluster = assign_cluster(session, normalized, raw_headline=tweet["text"])
    source.last_fetch_at = datetime.now(timezone.utc)
    session.commit()
    return cluster
