"""
Content handoff: writes one JSON record per story cluster for the existing
First Signal Facebook pipeline to consume (see its /batch "from sheet" flow).
This is NOT AI content generation -- no caption/image logic lives here, only
the story data an editor decided is worth pushing downstream.
"""
import json
import os
from datetime import datetime, timezone

HANDOFF_DIR = "handoff"


def write_handoff(cluster, articles: list) -> str:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = os.path.join(HANDOFF_DIR, date_str)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{cluster.id}.json")

    record = {
        "cluster_id": cluster.id,
        "canonical_headline": cluster.canonical_headline,
        "category": cluster.category,
        "status": cluster.status,
        "verification_status": cluster.verification_status,
        "scores": {
            "viral_score_preliminary": cluster.viral_score,
            "confidence_score": cluster.confidence_score,
            "momentum_score": cluster.momentum_score,
        },
        "entities": json.loads(cluster.entities or "[]"),
        "keywords": json.loads(cluster.keywords or "[]"),
        "location": cluster.location,
        "first_detected_at": cluster.first_detected_at.isoformat() if cluster.first_detected_at else None,
        "latest_update_at": cluster.latest_update_at.isoformat() if cluster.latest_update_at else None,
        "sources": [
            {
                "source_name": a.source.name if a.source else None,
                "headline": a.raw_article.headline if a.raw_article else a.normalized_headline,
                "url": a.canonical_url,
                "tier": a.source_tier,
                "published_at": a.published_at.isoformat() if a.published_at else None,
            }
            for a in articles
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    return path
