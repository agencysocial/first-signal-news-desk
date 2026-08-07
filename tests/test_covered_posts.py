from sqlalchemy import select

from app.clustering import assign_cluster
from app.main import mark_covered
from app.models import CoveredPost


def test_mark_covered_creates_a_record_with_full_metadata(session, make_source, ingest_article):
    source = make_source()
    a1 = ingest_article(source, "City council approves new budget plan")
    cluster = assign_cluster(session, a1, raw_headline="City council approves new budget plan")

    mark_covered(
        session, cluster, platform="Facebook", post_url="https://facebook.com/firstsignal/posts/123",
        post_id="123", format_used="Template A image", editor="Sumit", notes="Posted at 9am",
    )
    session.flush()

    covered = session.execute(select(CoveredPost).where(CoveredPost.cluster_id == cluster.id)).scalars().all()
    assert len(covered) == 1
    assert covered[0].platform == "Facebook"
    assert covered[0].post_url == "https://facebook.com/firstsignal/posts/123"
    assert covered[0].editor == "Sumit"
    assert covered[0].notes == "Posted at 9am"
    assert cluster.covered_at is not None


def test_mark_covered_defaults_headline_used_to_canonical_headline(session, make_source, ingest_article):
    source = make_source()
    a1 = ingest_article(source, "Senate passes infrastructure bill")
    cluster = assign_cluster(session, a1, raw_headline="Senate passes infrastructure bill")

    mark_covered(session, cluster)  # no headline_used supplied
    session.flush()

    covered = session.execute(select(CoveredPost).where(CoveredPost.cluster_id == cluster.id)).scalars().first()
    assert covered.headline_used == "Senate passes infrastructure bill"


def test_covered_post_history_survives_reopen_on_new_development(session, make_source, ingest_article):
    source_a = make_source(name="Outlet A")
    source_b = make_source(name="Outlet B")

    a1 = ingest_article(source_a, "Mayor announces new infrastructure plan")
    cluster = assign_cluster(session, a1, raw_headline="Mayor announces new infrastructure plan")

    mark_covered(session, cluster, platform="Facebook", editor="Sumit")
    cluster.status = "Covered"
    session.flush()

    # A new development attaches -- clustering.py's own reopen logic flips
    # status back to Developing. Nothing should touch the CoveredPost row.
    a2 = ingest_article(source_b, "Mayor announces new infrastructure plan with added funding")
    reopened = assign_cluster(session, a2, raw_headline="Mayor announces new infrastructure plan with added funding")

    assert reopened.status == "Developing"
    history = session.execute(select(CoveredPost).where(CoveredPost.cluster_id == cluster.id)).scalars().all()
    assert len(history) == 1
    assert history[0].editor == "Sumit"


def test_multiple_covered_events_accumulate_not_overwrite(session, make_source, ingest_article):
    source_a = make_source(name="Outlet A")
    source_b = make_source(name="Outlet B")

    a1 = ingest_article(source_a, "Wildfire forces evacuations near Boulder")
    cluster = assign_cluster(session, a1, raw_headline="Wildfire forces evacuations near Boulder")

    mark_covered(session, cluster, platform="Facebook", notes="first post")
    cluster.status = "Covered"
    session.flush()

    a2 = ingest_article(source_b, "Wildfire forces new evacuations near Boulder overnight")
    cluster = assign_cluster(session, a2, raw_headline="Wildfire forces new evacuations near Boulder overnight")
    assert cluster.status == "Developing"  # reopened

    mark_covered(session, cluster, platform="Instagram", notes="follow-up post")
    cluster.status = "Covered"
    session.flush()

    history = session.execute(
        select(CoveredPost).where(CoveredPost.cluster_id == cluster.id).order_by(CoveredPost.id)
    ).scalars().all()
    assert len(history) == 2
    assert [h.notes for h in history] == ["first post", "follow-up post"]
    assert [h.platform for h in history] == ["Facebook", "Instagram"]
