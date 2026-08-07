"""
Rules-based scoring only -- no AI calls. Weights are hardcoded constants for
Phase 1b (promote to a `scoring_settings` table only once AI scoring in
Phase 3 makes runtime tuning worth the complexity -- see the Phase 1 spec's
database-tables section).

viral_score is explicitly a PRELIMINARY approximation: momentum + source-tier
mix + recency + source count. The original spec's emotional-strength /
visual-potential / conversation-potential / novelty sub-scores need AI
classification and are deferred to Phase 3 -- do not stub them here as fake
zeros dressed up as real fields.
"""
from datetime import datetime, timezone


def _dt_aware(dt):
    if dt and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def compute_scores(cluster, articles: list) -> tuple[float, float, float]:
    now = datetime.now(timezone.utc)
    first_detected = _dt_aware(cluster.first_detected_at) or now
    age_minutes = max((now - first_detected).total_seconds() / 60, 0)

    distinct_sources = {a.source_id for a in articles}
    high_tier_count = sum(1 for a in articles if a.source_tier <= 2)
    sources_last_15 = sum(
        1 for a in articles if (now - _dt_aware(a.detected_at)).total_seconds() <= 900
    )

    # --- Momentum (0-100): source_velocity + source_quality + recency +
    # update_frequency + national_spread, per the spec's suggested formula.
    # Not raw article count alone. ---
    velocity = min(sources_last_15 / 4, 1.0) * 30
    quality = min(high_tier_count / 3, 1.0) * 20
    if age_minutes <= 15:
        recency = 20.0
    elif age_minutes <= 60:
        recency = 15.0
    elif age_minutes <= 180:
        recency = 10.0
    elif age_minutes <= 1440:
        recency = 5.0
    else:
        recency = 0.0
    update_frequency = min(len(articles) / 8, 1.0) * 15
    spread = min(len(distinct_sources) / 5, 1.0) * 15
    momentum = round(velocity + quality + recency + update_frequency + spread, 1)

    # --- Viral score (0-100), PRELIMINARY rules-only approximation. ---
    tier_mix_pct = min(high_tier_count / max(len(distinct_sources), 1), 1.0) * 100
    recency_pct = (recency / 20) * 100
    source_count_pct = min(len(distinct_sources) / 10, 1.0) * 100
    viral = round(
        0.40 * momentum + 0.30 * tier_mix_pct + 0.15 * recency_pct + 0.15 * source_count_pct, 1
    )

    # --- Confidence score (0-100): kept independent of viral score, always.
    # official_source_presence rewards a genuine Tier-1 (official/government)
    # source specifically, distinct from high_tier_coverage's tier<=2 (which
    # also counts ordinary major outlets). This was hardcoded to 0.0 with a
    # comment saying "no Tier-1 feeds seeded yet" -- true when written, but
    # went stale once a real Tier-1 source (FBI National Press Releases) was
    # added later; found via a live-data audit that 288 real clusters
    # containing that source were scoring identically to ordinary
    # single-source stories, capped at confidence=32.5 with no way to reach
    # higher even with a literal federal law-enforcement confirmation. ---
    independent_sources = min(len(distinct_sources) / 4, 1.0) * 30
    high_tier_coverage = min(high_tier_count / 2, 1.0) * 30
    cross_report_agreement = min(len(distinct_sources) / 2, 1.0) * 20
    official_source_presence = 20.0 if any(a.source_tier == 1 for a in articles) else 0.0
    confidence = round(
        independent_sources + high_tier_coverage + cross_report_agreement + official_source_presence, 1
    )

    return momentum, viral, confidence
