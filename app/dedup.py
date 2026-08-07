"""
Duplicate detection, Levels 1 and 2 only (Phase 1a scope -- no embeddings).

Level 1 (exact): canonical URL match, content hash match, exact normalized
headline match.

Level 2 (near): headline token Jaccard similarity + RapidFuzz token-sort ratio,
checked only against articles detected within NEAR_DUP_LOOKBACK_HOURS (comparing
against the entire history isn't necessary -- duplicate coverage of the same
story shows up within hours, not weeks).

Returns (duplicate_of_id, level, score) or (None, None, None) if the article
is canonical (first-seen).
"""
from datetime import datetime, timedelta, timezone

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import (
    HEADLINE_JACCARD_THRESHOLD,
    HEADLINE_FUZZ_RATIO_THRESHOLD,
    NEAR_DUP_LOOKBACK_HOURS,
)
from app.models import NormalizedArticle
from app.normalize import headline_tokens


def find_duplicate(
    session: Session,
    *,
    canonical_url: str,
    url_hash: str,
    headline_hash: str,
    content_hash: str,
    normalized_headline: str,
) -> tuple[int | None, str | None, float | None]:
    # --- Level 1: exact ---
    exact = session.execute(
        select(NormalizedArticle).where(
            (NormalizedArticle.url_hash == url_hash)
            | (NormalizedArticle.content_hash == content_hash)
            | (NormalizedArticle.headline_hash == headline_hash)
        ).order_by(NormalizedArticle.id.asc())
    ).scalars().first()
    if exact:
        if exact.url_hash == url_hash:
            level = "exact_url"
        elif exact.content_hash == content_hash:
            level = "exact_content"
        else:
            level = "exact_headline"
        canonical_id = exact.duplicate_of_id or exact.id
        return canonical_id, level, 1.0

    # --- Level 2: near-duplicate, recent window only ---
    cutoff = datetime.now(timezone.utc) - timedelta(hours=NEAR_DUP_LOOKBACK_HOURS)
    recent = session.execute(
        select(NormalizedArticle)
        .where(NormalizedArticle.detected_at >= cutoff)
        .where(NormalizedArticle.duplicate_of_id.is_(None))  # compare against canonicals only
        .order_by(NormalizedArticle.id.desc())
        .limit(500)
    ).scalars().all()

    candidate_tokens = headline_tokens(normalized_headline)
    best_match = None
    best_score = 0.0
    best_level = None

    for other in recent:
        other_tokens = headline_tokens(other.normalized_headline)
        if not candidate_tokens or not other_tokens:
            continue
        union = candidate_tokens | other_tokens
        jaccard = len(candidate_tokens & other_tokens) / len(union) if union else 0.0
        if jaccard >= HEADLINE_JACCARD_THRESHOLD and jaccard > best_score:
            best_match, best_score, best_level = other, jaccard, "near_jaccard"

        ratio = fuzz.token_sort_ratio(normalized_headline, other.normalized_headline)
        if ratio >= HEADLINE_FUZZ_RATIO_THRESHOLD and (ratio / 100) > best_score:
            best_match, best_score, best_level = other, ratio / 100, "near_fuzzy"

    if best_match:
        return best_match.id, best_level, round(best_score, 3)

    return None, None, None
