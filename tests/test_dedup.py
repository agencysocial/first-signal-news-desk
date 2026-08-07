from datetime import datetime, timedelta, timezone


def test_exact_url_match_is_a_duplicate(session, make_source, ingest_article):
    source_a = make_source(name="Outlet A")
    source_b = make_source(name="Outlet B")
    shared_url = "https://news.example.com/story-123"

    first = ingest_article(source_a, "Storm hits coastline overnight", url=shared_url)
    second = ingest_article(source_b, "Completely different wording here", url=shared_url)

    assert first.duplicate_of_id is None
    assert second.duplicate_of_id == first.id
    assert second.duplicate_level == "exact_url"


def test_exact_headline_match_is_a_duplicate(session, make_source, ingest_article):
    source_a = make_source(name="Outlet A")
    source_b = make_source(name="Outlet B")

    # Different descriptions so content_hash (headline+description) differs
    # -- isolates the exact_headline path from exact_content, which would
    # otherwise also match whenever descriptions happen to be equal (e.g.
    # both empty).
    first = ingest_article(source_a, "Senate passes new budget bill", description="Full AP wire text A.")
    second = ingest_article(source_b, "Senate Passes New Budget Bill!!!", description="Full AP wire text B.")

    assert second.duplicate_of_id == first.id
    assert second.duplicate_level == "exact_headline"


def test_near_duplicate_headline_is_detected(session, make_source, ingest_article):
    source_a = make_source(name="Outlet A")
    source_b = make_source(name="Outlet B")

    first = ingest_article(source_a, "Wildfire forces evacuation of thousand residents near Boulder")
    second = ingest_article(source_b, "Wildfire forces evacuation of thousands near Boulder Colorado")

    assert second.duplicate_of_id == first.id
    assert second.duplicate_level in ("near_jaccard", "near_fuzzy")


def test_unrelated_headlines_are_not_flagged_as_duplicates(session, make_source, ingest_article):
    source_a = make_source(name="Outlet A")
    source_b = make_source(name="Outlet B")

    first = ingest_article(source_a, "Local school board approves new budget")
    second = ingest_article(source_b, "Championship game ends in dramatic overtime finish")

    assert second.duplicate_of_id is None


def test_near_duplicate_only_checked_within_lookback_window(session, make_source, ingest_article):
    source_a = make_source(name="Outlet A")
    source_b = make_source(name="Outlet B")
    old_time = datetime.now(timezone.utc) - timedelta(hours=200)  # outside NEAR_DUP_LOOKBACK_HOURS

    first = ingest_article(source_a, "Wildfire forces evacuation of thousand residents near Boulder",
                            detected_at=old_time)
    second = ingest_article(source_b, "Wildfire forces evacuation of thousands near Boulder Colorado")

    # Same near-duplicate wording, but the original is too old to compare against
    assert second.duplicate_of_id is None
