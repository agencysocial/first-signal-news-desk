from datetime import datetime, timedelta, timezone

from app.scoring import compute_scores


class FakeCluster:
    def __init__(self, first_detected_at, latest_update_at):
        self.first_detected_at = first_detected_at
        self.latest_update_at = latest_update_at


class FakeArticle:
    def __init__(self, source_id, source_tier, detected_at):
        self.source_id = source_id
        self.source_tier = source_tier
        self.detected_at = detected_at


def test_momentum_higher_for_recent_multi_source_high_tier_story():
    now = datetime.now(timezone.utc)

    fresh_cluster = FakeCluster(first_detected_at=now - timedelta(minutes=5), latest_update_at=now)
    fresh_articles = [
        FakeArticle(source_id=1, source_tier=1, detected_at=now - timedelta(minutes=4)),
        FakeArticle(source_id=2, source_tier=2, detected_at=now - timedelta(minutes=2)),
        FakeArticle(source_id=3, source_tier=1, detected_at=now - timedelta(minutes=1)),
    ]
    fresh_momentum, _, _ = compute_scores(fresh_cluster, fresh_articles)

    stale_cluster = FakeCluster(first_detected_at=now - timedelta(days=3), latest_update_at=now - timedelta(days=3))
    stale_articles = [FakeArticle(source_id=1, source_tier=5, detected_at=now - timedelta(days=3))]
    stale_momentum, _, _ = compute_scores(stale_cluster, stale_articles)

    assert fresh_momentum > stale_momentum


def test_confidence_and_viral_scores_are_not_mechanically_coupled():
    """A single very recent tier-2 source (an ordinary major outlet, not an
    official one -- see test_official_source_presence_increases_confidence
    for that case) should score well on viral (momentum/recency driven) but
    poorly on confidence (needs independent corroboration) -- the two scores
    must not move in lockstep.
    """
    now = datetime.now(timezone.utc)
    cluster = FakeCluster(first_detected_at=now - timedelta(minutes=2), latest_update_at=now)
    single_source_articles = [FakeArticle(source_id=1, source_tier=2, detected_at=now - timedelta(minutes=1))]

    momentum, viral, confidence = compute_scores(cluster, single_source_articles)

    assert confidence < 50  # single source: can't be highly confident
    assert viral > confidence  # recency/momentum still drive viral up despite low confidence


def test_official_source_presence_increases_confidence():
    """Regression test for a real live-data finding: 288 real clusters
    containing a genuine Tier-1 official source (FBI National Press
    Releases) were scoring identically to ordinary single-source stories,
    because official_source_presence was hardcoded to 0.0 with a comment
    saying no Tier-1 feed existed yet -- true when written, stale once one
    was actually added. A single official (tier-1) source must score higher
    confidence than a single ordinary (tier-2) source, even with the same
    source count.
    """
    now = datetime.now(timezone.utc)
    cluster = FakeCluster(first_detected_at=now - timedelta(minutes=10), latest_update_at=now)

    ordinary_source = [FakeArticle(source_id=1, source_tier=2, detected_at=now)]
    _, _, confidence_ordinary = compute_scores(cluster, ordinary_source)

    official_source = [FakeArticle(source_id=1, source_tier=1, detected_at=now)]
    _, _, confidence_official = compute_scores(cluster, official_source)

    assert confidence_official > confidence_ordinary


def test_confidence_increases_with_independent_source_count():
    now = datetime.now(timezone.utc)
    cluster = FakeCluster(first_detected_at=now - timedelta(minutes=10), latest_update_at=now)

    one_source = [FakeArticle(source_id=1, source_tier=2, detected_at=now)]
    _, _, confidence_one = compute_scores(cluster, one_source)

    four_sources = [
        FakeArticle(source_id=1, source_tier=2, detected_at=now),
        FakeArticle(source_id=2, source_tier=1, detected_at=now),
        FakeArticle(source_id=3, source_tier=2, detected_at=now),
        FakeArticle(source_id=4, source_tier=1, detected_at=now),
    ]
    _, _, confidence_four = compute_scores(cluster, four_sources)

    assert confidence_four > confidence_one


def test_scores_are_bounded_0_to_100():
    now = datetime.now(timezone.utc)
    cluster = FakeCluster(first_detected_at=now - timedelta(minutes=1), latest_update_at=now)
    many_articles = [FakeArticle(source_id=i, source_tier=1, detected_at=now) for i in range(20)]

    momentum, viral, confidence = compute_scores(cluster, many_articles)
    for score in (momentum, viral, confidence):
        assert 0 <= score <= 100
