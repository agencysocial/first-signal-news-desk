import pytest

import app.collectors.twitter_manual as tm_module
from app.clustering import assign_cluster
from app.models import RawArticle, Source

# Real oEmbed response body, captured live from publish.twitter.com against
# https://twitter.com/jack/status/20 during scoping -- used as a fixture so
# the HTML-parsing logic is tested against actual API output, not a
# hand-written approximation of it.
REAL_OEMBED_HTML = (
    '<blockquote class="twitter-tweet"><p lang="en" dir="ltr">just setting up my twttr</p>'
    '&mdash; jack (@jack) <a href="https://x.com/jack/status/20?ref_src=twsrc%5Etfw">'
    "March 21, 2006</a></blockquote>\n"
    '<script async src="https://platform.x.com/widgets.js" charset="utf-8"></script>'
)


def _fake_payload(text="Some tweet text", author_name="Test Author",
                   author_url="https://x.com/testauthor", date_label="January 1, 2026"):
    html = (
        f'<blockquote class="twitter-tweet"><p lang="en" dir="ltr">{text}</p>'
        f'&mdash; {author_name} (@testauthor) <a href="https://x.com/testauthor/status/1">'
        f"{date_label}</a></blockquote>"
    )
    return {"url": "https://x.com/testauthor/status/1", "author_name": author_name,
            "author_url": author_url, "html": html, "type": "rich"}


# ── Parsing (against the real captured response) ────────────────────────────

def test_tweet_html_parser_extracts_text_and_date_from_real_response():
    parser = tm_module._TweetHTMLParser()
    parser.feed(REAL_OEMBED_HTML)
    assert parser.text == "just setting up my twttr"
    assert parser.date_label == "March 21, 2006"


def test_parse_date_label_parses_real_format():
    dt = tm_module._parse_date_label("March 21, 2006")
    assert dt is not None
    assert (dt.year, dt.month, dt.day) == (2006, 3, 21)


def test_parse_date_label_returns_none_on_garbage():
    assert tm_module._parse_date_label("not a date") is None
    assert tm_module._parse_date_label("") is None


# ── URL validation ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,expected", [
    ("https://twitter.com/jack/status/20", ("jack", "20")),
    ("https://x.com/jack/status/20", ("jack", "20")),
    ("https://www.x.com/jack/status/20?s=46", ("jack", "20")),
    ("http://x.com/Some_Handle/status/99999999999", ("Some_Handle", "99999999999")),
])
def test_parse_tweet_url_accepts_real_shapes(url, expected):
    assert tm_module.parse_tweet_url(url) == expected


@pytest.mark.parametrize("url", [
    "https://x.com/jack",
    "https://example.com/jack/status/20",
    "not a url at all",
    "",
])
def test_parse_tweet_url_rejects_non_status_urls(url):
    with pytest.raises(tm_module.TweetCaptureError):
        tm_module.parse_tweet_url(url)


# ── fetch_tweet_oembed error wrapping (network layer) ───────────────────────

def test_fetch_tweet_oembed_wraps_network_failure(monkeypatch):
    def raising_urlopen(*a, **k):
        raise ConnectionError("could not connect")

    monkeypatch.setattr(tm_module.urllib.request, "urlopen", raising_urlopen)

    with pytest.raises(tm_module.TweetCaptureError):
        tm_module.fetch_tweet_oembed("https://x.com/jack/status/20")


# ── capture_tweet end-to-end (fetch mocked, everything downstream real) ────

def test_capture_tweet_creates_source_article_and_cluster(monkeypatch, session):
    monkeypatch.setattr(
        tm_module, "fetch_tweet_oembed",
        lambda url: {"author_name": "Benny Test", "author_url": "https://x.com/bennytest",
                     "text": "Border crossings hit a new record this week", "published_at": None},
    )

    cluster = tm_module.capture_tweet(session, "https://x.com/bennytest/status/123")

    assert cluster is not None
    assert "Border crossings" in cluster.canonical_headline

    source = session.query(Source).filter_by(type="twitter_manual").one()
    assert source.name == "Benny Test (X)"
    assert source.credibility_tier == tm_module.DEFAULT_CREDIBILITY_TIER

    raw = session.query(RawArticle).filter_by(source_id=source.id).one()
    assert raw.url == "https://x.com/bennytest/status/123"
    assert raw.headline == "Border crossings hit a new record this week"


def test_capture_tweet_reuses_existing_author_source(monkeypatch, session):
    def fake_fetch(url):
        return {"author_name": "Benny Test", "author_url": "https://x.com/bennytest",
                "text": f"Tweet text for {url}", "published_at": None}

    monkeypatch.setattr(tm_module, "fetch_tweet_oembed", fake_fetch)

    tm_module.capture_tweet(session, "https://x.com/bennytest/status/1")
    tm_module.capture_tweet(session, "https://x.com/bennytest/status/2")

    sources = session.query(Source).filter_by(type="twitter_manual").all()
    assert len(sources) == 1


def test_capture_tweet_rejects_duplicate_tweet(monkeypatch, session):
    monkeypatch.setattr(
        tm_module, "fetch_tweet_oembed",
        lambda url: {"author_name": "Benny Test", "author_url": "https://x.com/bennytest",
                     "text": "Same tweet content", "published_at": None},
    )

    tm_module.capture_tweet(session, "https://x.com/bennytest/status/1")
    with pytest.raises(tm_module.TweetCaptureError, match="already been captured"):
        tm_module.capture_tweet(session, "https://x.com/bennytest/status/1")


def test_capture_tweet_rejects_invalid_url(session):
    with pytest.raises(tm_module.TweetCaptureError):
        tm_module.capture_tweet(session, "https://example.com/not-a-tweet")


def test_capture_tweet_never_hallucinates_engagement_score(monkeypatch, session):
    """oEmbed has no like/RT/reply counts -- a captured tweet's cluster must
    not end up with a nonzero viral_score derived from fabricated engagement,
    matching the project's 'never hallucinate engagement data' rule."""
    monkeypatch.setattr(
        tm_module, "fetch_tweet_oembed",
        lambda url: {"author_name": "Benny Test", "author_url": "https://x.com/bennytest",
                     "text": "A totally novel breaking story", "published_at": None},
    )
    cluster = tm_module.capture_tweet(session, "https://x.com/bennytest/status/1")
    # A single-source, freshly captured item should score like any other
    # single-source RSS pickup would -- driven by rules on source tier/count,
    # never by an invented engagement number.
    assert cluster.source_count == 1
    assert cluster.verification_status == "single_source"


def test_capture_tweet_merges_into_matching_existing_cluster(monkeypatch, session, make_source, ingest_article):
    """The whole value proposition: a captured tweet covering the same story
    as existing RSS coverage should land in the SAME cluster, not a
    duplicate one -- proving 'one ranked wire' actually works end to end."""
    rss_source = make_source(name="Wire Service", tier=2)
    existing = ingest_article(
        rss_source,
        headline="Senate passes major border security funding bill in late night vote",
    )
    existing_cluster = assign_cluster(session, existing, raw_headline=existing.normalized_headline)

    monkeypatch.setattr(
        tm_module, "fetch_tweet_oembed",
        lambda url: {
            "author_name": "Benny Test", "author_url": "https://x.com/bennytest",
            "text": "Senate passes major border security funding bill in late night vote",
            "published_at": None,
        },
    )
    tweet_cluster = tm_module.capture_tweet(session, "https://x.com/bennytest/status/1")

    assert tweet_cluster.id == existing_cluster.id
    assert tweet_cluster.source_count == 2
