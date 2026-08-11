from datetime import datetime, timezone

from sqlalchemy import (
    String, Integer, Boolean, DateTime, Text, Float, ForeignKey, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(30))  # "rss" | "google_news"
    url: Mapped[str] = mapped_column(Text)  # feed URL, or built Google News query URL
    query: Mapped[str | None] = mapped_column(String(200), nullable=True)  # raw keyword, google_news only
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    credibility_tier: Mapped[int] = mapped_column(Integer, default=3)  # 1 (official) - 5 (unverified)
    polling_tier: Mapped[str] = mapped_column(String(20), default="standard")  # priority|standard|low
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Per-source User-Agent override. Null = use the shared default in
    # app/collectors/rss.py. Found live that different sites' bot-detection
    # actively disagrees with each other: Politico previously 403'd the
    # default feedparser UA and needed a browser UA to work; Newsmax does
    # the opposite -- it hangs specifically when the shared browser UA is
    # used (confirmed 3/3 live requests) but responds instantly to a plain
    # UA. One shared UA can't satisfy both, so this is per-source.
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    raw_articles: Mapped[list["RawArticle"]] = relationship(back_populates="source")


class RawArticle(Base):
    __tablename__ = "raw_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    # Text, not String(N): external_id is frequently the entry's full URL
    # (used as the RSS GUID by several feeds) -- SQLite never enforced the
    # old String(500)/String(300) caps here, so real feed data quietly
    # exceeded them (895 chars seen for external_id, 347 for author) without
    # error until Postgres started enforcing the column length for real.
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(Text)
    headline: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped["Source"] = relationship(back_populates="raw_articles")

    __table_args__ = (
        Index("ix_raw_articles_url", "url"),
    )


class NormalizedArticle(Base):
    __tablename__ = "normalized_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_article_id: Mapped[int] = mapped_column(ForeignKey("raw_articles.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)

    canonical_url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64), index=True)
    normalized_headline: Mapped[str] = mapped_column(Text)
    headline_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_tier: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    # Dedup result. duplicate_of_id is null for a "canonical" (first-seen) story.
    duplicate_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("normalized_articles.id"), nullable=True, index=True
    )
    duplicate_level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    duplicate_similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    source: Mapped["Source"] = relationship()
    raw_article: Mapped["RawArticle"] = relationship()


class StoryCluster(Base):
    __tablename__ = "story_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_headline: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # extracted, not AI-generated, in Phase 1
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)

    status: Mapped[str] = mapped_column(String(30), default="New", index=True)
    # Describes SOURCE CORROBORATION only (single_source / developing_coverage /
    # multi_source) -- never "verified", since no code here checks whether a
    # claim is factually true. See _PIPELINE-BUILD-DOCTRINE.md-style doctrine:
    # the human is the only control on truth.
    verification_status: Mapped[str] = mapped_column(String(30), default="single_source")

    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    latest_update_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    earliest_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    article_count: Mapped[int] = mapped_column(Integer, default=0)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    primary_source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)

    # Rules-only Phase 1 scores. viral_score blends the coverage-based
    # formula (momentum/tier-mix/recency/source-count -- unchanged from
    # Phase 1) with the Phase 3 AI sub-scores below when they're present
    # (see scoring.compute_scores); falls back to coverage-only when a
    # cluster hasn't been AI-scored yet, so nothing regresses.
    viral_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    momentum_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Phase 3: AI content-judgment sub-scores (0-100 each), the piece a
    # rules engine can't compute -- does the STORY ITSELF read as something
    # people react to, independent of how many sources have picked it up so
    # far. Null until scored (see app/ai_scoring.py); compute_scores falls
    # back to coverage_component alone when null, so nothing regresses for
    # an unscored cluster.
    ai_emotional_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_visual_potential: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_conversation_potential: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_novelty: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_topic_relevance: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    entities: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    location: Mapped[str | None] = mapped_column(String(100), nullable=True)

    handoff_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    covered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # FSN Production Queue state — JSON blob persisted to DB so cloud team edits survive redeploys.
    # Stores: queue_status, post_type, draft, approved_at, generated_image_url, image_gen_status, tobi_text.
    fsn_state: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    primary_source: Mapped["Source | None"] = relationship()

    __table_args__ = (
        Index("ix_story_clusters_viral", "viral_score"),
        Index("ix_story_clusters_confidence", "confidence_score"),
        Index("ix_story_clusters_momentum", "momentum_score"),
    )


class StoryClusterArticle(Base):
    __tablename__ = "story_cluster_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("story_clusters.id"), index=True)
    normalized_article_id: Mapped[int] = mapped_column(
        ForeignKey("normalized_articles.id"), unique=True, index=True
    )
    match_level: Mapped[str] = mapped_column(String(30))  # seed|matched|duplicate_inherit
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CoveredPost(Base):
    """One row per Mark-Covered event, not one row per cluster -- a story can
    be covered, reopen on a new development (see clustering.py's
    Covered/Dismissed -> Developing transition), and get covered again later.
    StoryCluster.covered_at stays as a quick "most recently covered" lookup;
    the full history with platform/URL/editor/notes lives here."""
    __tablename__ = "covered_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("story_clusters.id"), index=True)
    covered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    platform: Mapped[str | None] = mapped_column(String(50), nullable=True)
    post_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    format: Mapped[str | None] = mapped_column(String(100), nullable=True)
    headline_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    editor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
