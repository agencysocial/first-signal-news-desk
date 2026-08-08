"""
One-shot backfill: AI-score existing clusters that predate Phase 3.

Deliberately scoped to ACTIVE clusters only (not Covered/Dismissed/
Archived) -- there are 27,000+ historical clusters in the live DB, and
re-scoring old, closed-out stories that no one will ever look at again
burns real API cost for zero practical benefit. Going forward, new
clusters get scored automatically at creation time (see
clustering.assign_cluster); this script only needs to run once, and again
later only if you want to extend backfill coverage.

Uses compute_scores() directly, same pattern as recompute_all_scores.py --
a pure score refresh, not a re-run of the clustering state machine. Doesn't
call the heavier _recompute_cluster (which also does status transitions
like Covered -> Developing on new-article-attach) since re-scoring
shouldn't reopen an already-closed-out story.

Usage:
    python scripts/backfill_ai_scores.py [--limit N]
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(override=True)

from sqlalchemy import select

from app.ai_scoring import score_story_content
from app.db import SessionLocal
from app.models import NormalizedArticle, StoryCluster, StoryClusterArticle
from app.scoring import compute_scores

EXCLUDED_STATUSES = {"Covered", "Dismissed", "Archived"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--status", default=None, help="Scope to one status exactly (e.g. Developing) instead of the default not-Covered/Dismissed/Archived filter")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        query = select(StoryCluster).where(StoryCluster.ai_scored_at.is_(None))
        if args.status:
            query = query.where(StoryCluster.status == args.status)
        else:
            query = query.where(StoryCluster.status.notin_(EXCLUDED_STATUSES))

        clusters = session.execute(
            query
            .order_by(StoryCluster.latest_update_at.desc())
            .limit(args.limit)
        ).scalars().all()

        print(f"{len(clusters)} unscored active cluster(s) to backfill")
        scored, failed = 0, 0

        for cluster in clusters:
            try:
                entities = json.loads(cluster.entities or "[]")
            except (ValueError, TypeError):
                entities = []

            result = score_story_content(cluster.canonical_headline, cluster.category, entities)
            if not result:
                failed += 1
                continue

            cluster.ai_emotional_strength = result["emotional_strength"]
            cluster.ai_visual_potential = result["visual_potential"]
            cluster.ai_conversation_potential = result["conversation_potential"]
            cluster.ai_novelty = result["novelty"]
            cluster.ai_scored_at = datetime.now(timezone.utc)

            links = session.execute(
                select(StoryClusterArticle).where(StoryClusterArticle.cluster_id == cluster.id)
            ).scalars().all()
            article_ids = [link.normalized_article_id for link in links]
            articles = session.execute(
                select(NormalizedArticle).where(NormalizedArticle.id.in_(article_ids))
            ).scalars().all()
            if articles:
                _, viral, _ = compute_scores(cluster, articles)
                cluster.viral_score = viral
            scored += 1

            if (scored + failed) % 20 == 0:
                session.commit()
                print(f"  {scored + failed}/{len(clusters)} (scored={scored} failed={failed})")

        session.commit()
        print(f"Done. scored={scored} failed={failed}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
