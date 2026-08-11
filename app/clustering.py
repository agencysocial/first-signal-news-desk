"""
Layered rules-based story clustering (Phase 1b). No semantic/embedding step --
headline token similarity + entity/location overlap only, per the Phase 1
spec. Biased toward false negatives (separate clusters) over incorrect
merges: the match threshold is intentionally conservative.

Duplicates (Level 1/2 dedup hits) skip the heavier match logic entirely and
inherit their canonical article's cluster directly -- same wording, same
story, no need to re-score it.
"""
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_scoring import score_story_content
from app.entities import extract_entities, extract_keywords, extract_location, GENERIC_ENTITIES, KNOWN_LOCATIONS
from app.models import NormalizedArticle, StoryCluster, StoryClusterArticle
from app.normalize import headline_tokens
from app.scoring import compute_scores

CLUSTER_LOOKBACK_HOURS = 48

# One specific shared entity needs at least this much headline-text overlap
# as corroboration before it counts as a match.
CLUSTER_MIN_HEADLINE_SCORE_WITH_ONE_ENTITY = 0.20
# Headline text alone can qualify as a match without any entity support if
# it's this similar (near-identical wording, e.g. wire-service syndication
# entity extraction happened to miss).
CLUSTER_MIN_HEADLINE_SCORE_ALONE = 0.50

# An entity shared by this many or more of the currently-active candidate
# clusters is common for THIS news cycle (e.g. "World Cup" during World Cup
# week) and gets the same "not a distinguishing signal" treatment as the
# hardcoded GENERIC_ENTITIES/KNOWN_LOCATIONS lists -- self-correcting instead
# of requiring a new manual blocklist entry every time a big event name
# causes the same over-merge pattern (already found for political figures,
# then city names, then event names -- three different fixed lists would
# never fully cover this).
COMMON_ENTITY_FREQUENCY_THRESHOLD = 4


def build_entity_frequency(clusters: list[StoryCluster]) -> Counter:
    freq = Counter()
    for c in clusters:
        seen_in_this_cluster = set()
        for e in json.loads(c.entities or "[]"):
            key = e.lower()
            if key not in seen_in_this_cluster:
                freq[key] += 1
                seen_in_this_cluster.add(key)
    return freq


def _dt_aware(dt):
    if dt and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _score_against_cluster(article_tokens: set[str], article_entities: list[str],
                            cluster: StoryCluster,
                            entity_frequency: Counter | None = None) -> tuple[bool, float]:
    """Returns (is_match, rank_score). Matching is rule-gated, not a single
    additive score crossing one cutoff -- an additive formula is exactly
    what caused four different real incorrect merges during testing (two
    generic political entities, a shared city, a shared big-event name, and
    a shared hot-topic acronym each separately added up to "just enough"
    across a weighted sum, regardless of which specific weak signal it was).

    A match now requires one of:
    - 2+ shared entities that are genuinely SPECIFIC (not generic terms,
      not place names, not something common across this batch's other
      active clusters) -- strong enough alone.
    - 1 specific shared entity PLUS real headline-text overlap as
      corroboration -- a specific entity alone was the exact mechanism
      behind the Miami and "ICE" over-merges.
    - Headline text alone similar enough that it's almost certainly the
      same wording, with no entity support needed.

    Location is deliberately NOT part of this decision. It's still
    extracted and shown to editors on the story detail page, but it
    contributed to two of the four incorrect merges (Miami, New York) when
    used as a scoring signal, and a simple gazetteer/substring match can't
    reliably tell "same specific place, same story" from "two unrelated
    things that happened in the same city" -- not worth the false-merge
    risk for what it added.
    """
    cluster_tokens = set(json.loads(cluster.keywords or "[]"))
    cluster_entities = {e.lower() for e in json.loads(cluster.entities or "[]")}
    article_entities_l = {e.lower() for e in article_entities}
    entity_frequency = entity_frequency or Counter()

    headline_score = 0.0
    if article_tokens and cluster_tokens:
        union = article_tokens | cluster_tokens
        headline_score = len(article_tokens & cluster_tokens) / len(union) if union else 0.0

    shared_entities = article_entities_l & cluster_entities
    non_generic = shared_entities - GENERIC_ENTITIES
    non_place = {e for e in non_generic if e not in KNOWN_LOCATIONS}
    specific_shared = {e for e in non_place if entity_frequency.get(e, 0) < COMMON_ENTITY_FREQUENCY_THRESHOLD}

    if len(specific_shared) >= 2:
        return True, 1.0 + headline_score
    if len(specific_shared) == 1 and headline_score >= CLUSTER_MIN_HEADLINE_SCORE_WITH_ONE_ENTITY:
        return True, 0.7 + headline_score
    if headline_score >= CLUSTER_MIN_HEADLINE_SCORE_ALONE:
        return True, headline_score

    # Not a match -- rank_score only matters relative to other non-matches,
    # which assign_cluster never selects anyway.
    weak_score = 0.35 * headline_score
    if specific_shared:
        weak_score += 0.15
    elif shared_entities:
        weak_score += 0.05
    return False, weak_score


def get_cluster_for_normalized_article(session: Session, normalized_article_id: int) -> StoryCluster | None:
    link = session.execute(
        select(StoryClusterArticle).where(
            StoryClusterArticle.normalized_article_id == normalized_article_id
        )
    ).scalars().first()
    if not link:
        return None
    return session.get(StoryCluster, link.cluster_id)


def _attach(session: Session, cluster: StoryCluster, normalized: NormalizedArticle,
            match_level: str, match_score: float, location: str | None = None):
    """Attach a new member to a cluster. Deliberately does NOT merge the new
    article's entities/keywords into cluster.entities/keywords.

    Earlier versions accumulated every member's entities/keywords into an
    ever-growing pool used for matching future candidates. In production
    this caused cluster drift: as a cluster absorbed more (even correctly
    matched) articles, its pool grew large and generic enough that a later,
    genuinely unrelated story could share just enough weak overlap with
    SOMETHING in that swollen bag to cross the match threshold -- observed
    twice with real data (an Iran cluster absorbing an unrelated Supreme
    Court story via 2 shared generic entities, then separately three
    unrelated Miami stories and a New York cluster absorbing unrelated FBI
    press releases via shared place names in various phrasings that a fixed
    gazetteer couldn't fully enumerate). Matching against the cluster's
    fixed founding (seed) entities/keywords instead of an ever-growing
    accumulated pool bounds the matching surface permanently and prevents
    this drift regardless of how the "is this a generic term" heuristic is
    tuned. This is a stricter, more false-negative-biased trade-off, which
    is exactly the direction the spec asks for.
    """
    session.add(StoryClusterArticle(
        cluster_id=cluster.id,
        normalized_article_id=normalized.id,
        match_level=match_level,
        match_score=match_score,
    ))

    if not cluster.location and location:
        cluster.location = location

    if not cluster.category and normalized.source and normalized.source.category:
        cluster.category = normalized.source.category

    dt = _dt_aware(normalized.detected_at)
    if dt and (not cluster.latest_update_at or _dt_aware(cluster.latest_update_at) < dt):
        cluster.latest_update_at = normalized.detected_at

    pub = _dt_aware(normalized.published_at)
    existing_earliest = _dt_aware(cluster.earliest_published_at)
    if pub and (not existing_earliest or pub < existing_earliest):
        cluster.earliest_published_at = normalized.published_at

    session.flush()


def _recompute_cluster(session: Session, cluster: StoryCluster):
    links = session.execute(
        select(StoryClusterArticle).where(StoryClusterArticle.cluster_id == cluster.id)
    ).scalars().all()
    article_ids = [link.normalized_article_id for link in links]
    articles = session.execute(
        select(NormalizedArticle).where(NormalizedArticle.id.in_(article_ids))
    ).scalars().all()

    previous_article_count = cluster.article_count
    cluster.article_count = len(articles)
    cluster.source_count = len({a.source_id for a in articles})

    earliest = min(_dt_aware(a.detected_at) for a in articles)
    if not cluster.first_detected_at or earliest < _dt_aware(cluster.first_detected_at):
        cluster.first_detected_at = earliest

    # Automatic status transitions:
    #  - New -> Developing (per spec, the rest are editor-set)
    #  - Covered/Dismissed -> Developing, but ONLY when a genuinely new
    #    article just attached (not on every recompute). New developments on
    #    a covered topic must resurface, not be silently absorbed into a
    #    closed story -- see the Phase 1 spec's Definition of Done.
    gained_new_article = cluster.article_count > previous_article_count
    if cluster.status == "New" and cluster.source_count >= 2:
        cluster.status = "Developing"
    elif cluster.status in ("Covered", "Dismissed") and gained_new_article:
        cluster.status = "Developing"
        cluster.covered_at = None

    # verification_status describes SOURCE CORROBORATION, never factual truth.
    high_tier = sum(1 for a in articles if a.source_tier <= 2)
    if cluster.source_count >= 2 and high_tier >= 1:
        cluster.verification_status = "multi_source"
    elif cluster.source_count >= 2:
        cluster.verification_status = "developing_coverage"
    else:
        cluster.verification_status = "single_source"

    momentum, viral, confidence = compute_scores(cluster, articles)
    cluster.momentum_score = momentum
    cluster.viral_score = viral
    cluster.confidence_score = confidence

    session.flush()


def assign_cluster(session: Session, normalized: NormalizedArticle, raw_headline: str) -> StoryCluster:
    if normalized.duplicate_of_id:
        canonical_cluster = get_cluster_for_normalized_article(session, normalized.duplicate_of_id)
        if canonical_cluster:
            _attach(session, canonical_cluster, normalized, match_level="duplicate_inherit", match_score=1.0)
            _recompute_cluster(session, canonical_cluster)
            return canonical_cluster
        # fall through if the canonical's cluster link is somehow missing

    entities = extract_entities(raw_headline)
    keywords = extract_keywords(normalized.normalized_headline)
    location = extract_location(raw_headline)
    article_tokens = headline_tokens(normalized.normalized_headline)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=CLUSTER_LOOKBACK_HOURS)
    candidates = session.execute(
        select(StoryCluster).where(StoryCluster.latest_update_at >= cutoff)
        .order_by(StoryCluster.latest_update_at.desc())
        .limit(300)
    ).scalars().all()

    entity_frequency = build_entity_frequency(candidates)

    best_cluster, best_score = None, 0.0
    for cluster in candidates:
        is_match, rank_score = _score_against_cluster(article_tokens, entities, cluster, entity_frequency)
        if is_match and rank_score > best_score:
            best_cluster, best_score = cluster, rank_score

    if best_cluster:
        _attach(session, best_cluster, normalized, match_level="matched", match_score=best_score,
                location=location)
        _recompute_cluster(session, best_cluster)
        return best_cluster

    cluster = StoryCluster(
        canonical_headline=raw_headline,
        summary=(normalized.description or raw_headline)[:500],
        status="New",
        verification_status="single_source",
        first_detected_at=normalized.detected_at,
        latest_update_at=normalized.detected_at,
        earliest_published_at=normalized.published_at,
        primary_source_id=normalized.source_id,
        entities=json.dumps(entities),
        keywords=json.dumps(keywords),
        location=location,
    )
    session.add(cluster)
    session.flush()
    _attach(session, cluster, normalized, match_level="seed", match_score=1.0)

    # AI-score once per genuinely NEW story, not on every article that
    # merges into an existing cluster -- keeps Claude usage proportional to
    # new stories discovered, not total article volume (most incoming
    # articles match an existing cluster via the block above). Fails soft:
    # score_story_content returns None on any error, leaving the cluster to
    # fall back to the coverage-only formula in compute_scores.
    ai_scores = score_story_content(raw_headline, cluster.category, entities)
    if ai_scores:
        cluster.ai_emotional_strength = ai_scores["emotional_strength"]
        cluster.ai_visual_potential = ai_scores["visual_potential"]
        cluster.ai_conversation_potential = ai_scores["conversation_potential"]
        cluster.ai_novelty = ai_scores["novelty"]
        cluster.ai_topic_relevance = ai_scores.get("topic_relevance")
        cluster.ai_scored_at = datetime.now(timezone.utc)

    _recompute_cluster(session, cluster)
    return cluster


def merge_clusters(session: Session, source_cluster_id: int, target_cluster_id: int) -> StoryCluster:
    """Editor-triggered merge: rules-based clustering will misfire sometimes
    (see the module docstring's false-negative bias), so this is the manual
    correction path. Moves every article from source into target, unions
    entities/keywords, then deletes the source cluster."""
    if source_cluster_id == target_cluster_id:
        raise ValueError("cannot merge a cluster into itself")

    source_cluster = session.get(StoryCluster, source_cluster_id)
    target_cluster = session.get(StoryCluster, target_cluster_id)
    if not source_cluster or not target_cluster:
        raise ValueError("cluster not found")

    links = session.execute(
        select(StoryClusterArticle).where(StoryClusterArticle.cluster_id == source_cluster_id)
    ).scalars().all()
    for link in links:
        link.cluster_id = target_cluster_id

    merged_entities = json.loads(target_cluster.entities or "[]")
    for e in json.loads(source_cluster.entities or "[]"):
        if e not in merged_entities:
            merged_entities.append(e)
    target_cluster.entities = json.dumps(merged_entities[:20])

    merged_keywords = json.loads(target_cluster.keywords or "[]")
    for k in json.loads(source_cluster.keywords or "[]"):
        if k not in merged_keywords:
            merged_keywords.append(k)
    target_cluster.keywords = json.dumps(merged_keywords[:25])

    if not target_cluster.location and source_cluster.location:
        target_cluster.location = source_cluster.location
    if not target_cluster.category and source_cluster.category:
        target_cluster.category = source_cluster.category

    src_pub = _dt_aware(source_cluster.earliest_published_at)
    tgt_pub = _dt_aware(target_cluster.earliest_published_at)
    if src_pub and (not tgt_pub or src_pub < tgt_pub):
        target_cluster.earliest_published_at = source_cluster.earliest_published_at

    session.delete(source_cluster)
    session.flush()
    _recompute_cluster(session, target_cluster)
    return target_cluster


def split_cluster(session: Session, cluster_id: int, article_ids: list[int]) -> StoryCluster:
    """Editor-triggered split: extracts the given normalized_article_ids out
    of `cluster_id` into a brand-new cluster, then recomputes both."""
    cluster = session.get(StoryCluster, cluster_id)
    if not cluster:
        raise ValueError("cluster not found")

    links = session.execute(
        select(StoryClusterArticle).where(
            StoryClusterArticle.cluster_id == cluster_id,
            StoryClusterArticle.normalized_article_id.in_(article_ids),
        )
    ).scalars().all()
    if not links:
        raise ValueError("no matching articles in this cluster")
    if len(links) >= cluster.article_count:
        raise ValueError("cannot split every article out of a cluster")

    moved_ids = [link.normalized_article_id for link in links]
    moved_articles = session.execute(
        select(NormalizedArticle).where(NormalizedArticle.id.in_(moved_ids))
    ).scalars().all()

    seed_article = min(moved_articles, key=lambda a: _dt_aware(a.detected_at))
    seed_headline = seed_article.raw_article.headline if seed_article.raw_article else seed_article.normalized_headline

    new_entities: list[str] = []
    new_keywords: list[str] = []
    for a in moved_articles:
        headline = a.raw_article.headline if a.raw_article else a.normalized_headline
        for e in extract_entities(headline):
            if e not in new_entities:
                new_entities.append(e)
        for k in extract_keywords(a.normalized_headline):
            if k not in new_keywords:
                new_keywords.append(k)

    new_cluster = StoryCluster(
        canonical_headline=seed_headline,
        summary=(seed_article.description or seed_headline)[:500],
        status="New",
        verification_status="single_source",
        first_detected_at=seed_article.detected_at,
        latest_update_at=seed_article.detected_at,
        earliest_published_at=seed_article.published_at,
        primary_source_id=seed_article.source_id,
        entities=json.dumps(new_entities[:20]),
        keywords=json.dumps(new_keywords[:25]),
    )
    session.add(new_cluster)
    session.flush()

    for link in links:
        link.cluster_id = new_cluster.id
    session.flush()

    _recompute_cluster(session, cluster)
    _recompute_cluster(session, new_cluster)
    return new_cluster
