import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app import models  # noqa: F401 -- registers models on Base.metadata
from app.models import Source, RawArticle, NormalizedArticle
from app.normalize import canonicalize_url, normalize_headline, compute_hashes
from app.dedup import find_duplicate
import app.clustering as clustering_module


@pytest.fixture(autouse=True)
def _no_real_ai_scoring_calls(monkeypatch):
    """assign_cluster() calls Claude on every genuinely new cluster (Phase
    3). Without this, every test that creates a cluster -- most of
    test_clustering.py, test_collectors.py, test_twitter_capture.py, etc --
    would make a REAL network call to Anthropic's API on every run (this
    was caught live: the suite went from ~2s to ~50s the moment AI scoring
    was wired in, because ANTHROPIC_API_KEY is genuinely set in this repo's
    .env, so score_story_content() didn't short-circuit). Autouse so no
    individual test file has to remember to mock this -- returning None
    matches "Claude unreachable / not yet scored", which is exactly the
    fallback compute_scores already handles, so existing coverage-only
    assertions elsewhere in the suite stay valid unchanged.
    """
    monkeypatch.setattr(clustering_module, "score_story_content", lambda *a, **k: None)


@pytest.fixture()
def session():
    """Isolated in-memory DB per test -- never touches the real dev DB file."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    yield s
    s.close()
    engine.dispose()


@pytest.fixture()
def make_source(session):
    counter = {"n": 0}

    def _make(name=None, tier=2, category="general", type_="rss", polling_tier="standard"):
        counter["n"] += 1
        name = name or f"Test Source {counter['n']}"
        src = Source(
            name=name, type=type_, url=f"https://example.com/feed/{counter['n']}",
            category=category, credibility_tier=tier, polling_tier=polling_tier, enabled=True,
        )
        session.add(src)
        session.flush()
        return src

    return _make


@pytest.fixture()
def ingest_article(session):
    """Runs the real normalize + dedup steps (mirrors app/collectors/rss.py)
    against a plain headline/url, without needing a live feed fetch. Returns
    the NormalizedArticle -- callers add clustering themselves when needed.
    """
    counter = {"n": 0}

    def _ingest(source, headline, description=None, url=None,
                published_at=None, detected_at=None):
        counter["n"] += 1
        url = url or f"https://{source.name.lower().replace(' ', '')}.example.com/article-{counter['n']}"
        detected_at = detected_at or datetime.now(timezone.utc)

        raw = RawArticle(
            source_id=source.id, url=url, headline=headline, description=description,
            published_at=published_at, detected_at=detected_at,
        )
        session.add(raw)
        session.flush()

        canonical_url = canonicalize_url(url)
        norm_headline = normalize_headline(headline)
        url_hash, headline_hash, content_hash = compute_hashes(canonical_url, norm_headline, description)

        dup_of_id, dup_level, dup_score = find_duplicate(
            session, canonical_url=canonical_url, url_hash=url_hash,
            headline_hash=headline_hash, content_hash=content_hash,
            normalized_headline=norm_headline,
        )

        normalized = NormalizedArticle(
            raw_article_id=raw.id, source_id=source.id, canonical_url=canonical_url,
            url_hash=url_hash, normalized_headline=norm_headline, headline_hash=headline_hash,
            content_hash=content_hash, description=description, source_tier=source.credibility_tier,
            published_at=published_at, detected_at=detected_at,
            duplicate_of_id=dup_of_id, duplicate_level=dup_level, duplicate_similarity_score=dup_score,
        )
        session.add(normalized)
        session.flush()
        return normalized

    return _ingest
