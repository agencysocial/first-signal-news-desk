import json

import pytest
from sqlalchemy import select

from app.clustering import assign_cluster, merge_clusters, split_cluster
from app.models import StoryCluster, StoryClusterArticle


def test_merge_moves_all_articles_and_unions_entities(session, make_source, ingest_article):
    source_a = make_source(name="Outlet A")
    source_b = make_source(name="Outlet B")

    a1 = ingest_article(source_a, "Hurricane Delta slams Florida coast overnight")
    cluster_1 = assign_cluster(session, a1, raw_headline="Hurricane Delta slams Florida coast overnight")

    a2 = ingest_article(source_b, "Completely separate wildfire story out west")
    cluster_2 = assign_cluster(session, a2, raw_headline="Completely separate wildfire story out west")

    assert cluster_1.id != cluster_2.id  # sanity check: these did not auto-cluster

    merged = merge_clusters(session, source_cluster_id=cluster_2.id, target_cluster_id=cluster_1.id)

    assert merged.id == cluster_1.id
    assert merged.article_count == 2
    assert merged.source_count == 2

    # source cluster should be gone
    assert session.get(StoryCluster, cluster_2.id) is None

    # both articles now point at the target cluster
    links = session.execute(
        select(StoryClusterArticle).where(StoryClusterArticle.normalized_article_id.in_([a1.id, a2.id]))
    ).scalars().all()
    assert {link.cluster_id for link in links} == {cluster_1.id}

    merged_entities = json.loads(merged.entities or "[]")
    assert len(merged_entities) > 0


def test_cannot_merge_cluster_into_itself(session, make_source, ingest_article):
    source = make_source()
    a1 = ingest_article(source, "Some headline about a local event")
    cluster = assign_cluster(session, a1, raw_headline="Some headline about a local event")

    with pytest.raises(ValueError):
        merge_clusters(session, source_cluster_id=cluster.id, target_cluster_id=cluster.id)


def test_split_extracts_selected_articles_into_new_cluster(session, make_source, ingest_article):
    source_a = make_source(name="Outlet A")
    source_b = make_source(name="Outlet B")
    source_c = make_source(name="Outlet C")

    # Force all three into one cluster manually (simulating an over-merge an
    # editor needs to correct) by assigning the same headline text.
    a1 = ingest_article(source_a, "Regional flooding overwhelms small towns")
    cluster = assign_cluster(session, a1, raw_headline="Regional flooding overwhelms small towns")
    a2 = ingest_article(source_b, "Regional flooding overwhelms small towns update")
    assign_cluster(session, a2, raw_headline="Regional flooding overwhelms small towns update")
    a3 = ingest_article(source_c, "Regional flooding overwhelms small towns further update")
    assign_cluster(session, a3, raw_headline="Regional flooding overwhelms small towns further update")

    session.refresh(cluster)
    assert cluster.article_count == 3

    new_cluster = split_cluster(session, cluster.id, article_ids=[a3.id])

    session.refresh(cluster)
    assert cluster.article_count == 2
    assert new_cluster.article_count == 1
    assert new_cluster.id != cluster.id

    link = session.execute(
        select(StoryClusterArticle).where(StoryClusterArticle.normalized_article_id == a3.id)
    ).scalars().first()
    assert link.cluster_id == new_cluster.id


def test_split_rejects_extracting_every_article(session, make_source, ingest_article):
    source = make_source()
    a1 = ingest_article(source, "Only story in this cluster")
    cluster = assign_cluster(session, a1, raw_headline="Only story in this cluster")

    with pytest.raises(ValueError):
        split_cluster(session, cluster.id, article_ids=[a1.id])


def test_split_rejects_articles_not_in_the_cluster(session, make_source, ingest_article):
    source = make_source()
    a1 = ingest_article(source, "First unrelated story")
    cluster_1 = assign_cluster(session, a1, raw_headline="First unrelated story")

    a2 = ingest_article(source, "Second unrelated story about something else entirely")
    assign_cluster(session, a2, raw_headline="Second unrelated story about something else entirely")

    with pytest.raises(ValueError):
        split_cluster(session, cluster_1.id, article_ids=[a2.id])
