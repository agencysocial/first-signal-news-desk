"""
Tests the same filter the First Signal Wire route applies (app/main.py::wire)
-- exercised directly against the query rather than through FastAPI, since
main.py's routes open their own SessionLocal() tied to the real dev DB file
rather than accepting an injected session.
"""
from sqlalchemy import select

from app.clustering import assign_cluster
from app.main import _optional_int
from app.models import StoryCluster


def test_optional_int_parses_blank_form_fields_as_none():
    """Regression test: the filter form's <select>/<input> fields submit ""
    (not omit the param) when left on "Any ..." or blank. FastAPI's
    `int | None = None` route typing only supplies the default when a param
    is ABSENT, so it raised a 422 on every real filter-form submission that
    left any field blank -- e.g. picking just a category with everything
    else untouched. `_optional_int` is what fixed it.
    """
    assert _optional_int("") is None
    assert _optional_int(None) is None
    assert _optional_int("70") == 70
    assert _optional_int("0") == 0  # "0" is a non-empty string, must not become None


def _wire_query():
    return (
        select(StoryCluster)
        .where(StoryCluster.status.notin_(["Dismissed", "Archived"]))
        .order_by(StoryCluster.viral_score.desc())
    )


def test_dismissed_and_archived_clusters_are_excluded_from_the_wire(session, make_source, ingest_article):
    source = make_source()

    a1 = ingest_article(source, "Story that stays on the wire")
    kept = assign_cluster(session, a1, raw_headline="Story that stays on the wire")

    a2 = ingest_article(source, "Story that gets dismissed")
    dismissed = assign_cluster(session, a2, raw_headline="Story that gets dismissed")
    dismissed.status = "Dismissed"

    a3 = ingest_article(source, "Story that gets archived")
    archived = assign_cluster(session, a3, raw_headline="Story that gets archived")
    archived.status = "Archived"

    session.flush()

    visible_ids = {c.id for c in session.execute(_wire_query()).scalars().all()}

    assert kept.id in visible_ids
    assert dismissed.id not in visible_ids
    assert archived.id not in visible_ids
