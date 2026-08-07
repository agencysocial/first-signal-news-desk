"""
One-off: recalculate viral/confidence/momentum for every existing cluster
using the current app/scoring.py formula, WITHOUT touching status,
verification_status, or cluster membership -- a pure score refresh, not a
re-run of the clustering state machine.

Run this after any scoring.py change that should apply retroactively to
already-collected data. New-article-triggered recomputation alone
(_recompute_cluster, which only fires when a new article attaches) leaves
single-source clusters that never get a second article stuck with stale
scores from the old formula indefinitely -- which is exactly what happened
after the official_source_presence fix: most of the 288 real clusters
containing the FBI Tier-1 source are single-source and rarely gain a second,
so without this script they'd keep the old (wrong) confidence score forever.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select

from app.db import SessionLocal
from app.models import StoryCluster, StoryClusterArticle, NormalizedArticle
from app.scoring import compute_scores


def run():
    session = SessionLocal()
    try:
        clusters = session.execute(select(StoryCluster)).scalars().all()
        changed = 0
        for cluster in clusters:
            links = session.execute(
                select(StoryClusterArticle).where(StoryClusterArticle.cluster_id == cluster.id)
            ).scalars().all()
            article_ids = [link.normalized_article_id for link in links]
            articles = session.execute(
                select(NormalizedArticle).where(NormalizedArticle.id.in_(article_ids))
            ).scalars().all()
            if not articles:
                continue

            momentum, viral, confidence = compute_scores(cluster, articles)
            if (momentum, viral, confidence) != (cluster.momentum_score, cluster.viral_score, cluster.confidence_score):
                changed += 1
            cluster.momentum_score = momentum
            cluster.viral_score = viral
            cluster.confidence_score = confidence

        session.commit()
        print(f"Recomputed {len(clusters)} clusters, {changed} had score changes.")
    finally:
        session.close()


if __name__ == "__main__":
    run()
