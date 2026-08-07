"""
One-shot data migration: local SQLite (aim_news_desk.db) -> Supabase Postgres.

Run once, by hand, with the app/scanner stopped so the source data is frozen.
Not part of the app's normal runtime -- this is a migration tool, not a
recurring job.

Order matters for foreign keys: sources -> raw_articles -> normalized_articles
(ascending id, since duplicate_of_id self-references an earlier row) ->
story_clusters -> story_cluster_articles -> covered_posts.

Datetimes: SQLite has no real timezone type, so SQLAlchemy hands back naive
datetimes even though the columns are declared DateTime(timezone=True) --
this app treats every naive datetime as UTC everywhere else (see _dt_aware()
helpers), so this script attaches UTC tzinfo explicitly before writing to
Postgres rather than trusting the driver's default interpretation of naive
values.
"""
import os
import sys
from datetime import timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(override=True)

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base, Source, RawArticle, NormalizedArticle,
    StoryCluster, StoryClusterArticle, CoveredPost,
)

SQLITE_URL = "sqlite:///./aim_news_desk.db"
PG_URL = os.environ["SUPABASE_DATABASE_URL"]

BATCH_SIZE = 2000

TABLES_IN_ORDER = [
    (Source, "sources"),
    (RawArticle, "raw_articles"),
    (NormalizedArticle, "normalized_articles"),
    (StoryCluster, "story_clusters"),
    (StoryClusterArticle, "story_cluster_articles"),
    (CoveredPost, "covered_posts"),
]


def _aware(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


DATETIME_COLUMNS = {
    "sources": ["last_fetch_at", "created_at"],
    "raw_articles": ["published_at", "detected_at"],
    "normalized_articles": ["published_at", "detected_at", "created_at"],
    "story_clusters": ["first_detected_at", "latest_update_at", "earliest_published_at",
                        "handoff_sent_at", "covered_at", "created_at", "updated_at"],
    "story_cluster_articles": ["added_at"],
    "covered_posts": ["covered_at"],
}


def row_to_dict(obj, table_name):
    d = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    for col in DATETIME_COLUMNS.get(table_name, []):
        if col in d:
            d[col] = _aware(d[col])
    return d


def main():
    sqlite_engine = create_engine(SQLITE_URL)
    pg_engine = create_engine(PG_URL)
    SqliteSession = sessionmaker(bind=sqlite_engine)
    sqlite_session = SqliteSession()

    print(f"Creating schema on Supabase (Base.metadata.create_all)...")
    Base.metadata.create_all(pg_engine)

    for model, table_name in TABLES_IN_ORDER:
        rows = sqlite_session.execute(
            select(model).order_by(model.id.asc())
        ).scalars().all()
        total = len(rows)
        print(f"{table_name}: {total} rows to migrate")

        with pg_engine.begin() as conn:
            for i in range(0, total, BATCH_SIZE):
                batch = rows[i:i + BATCH_SIZE]
                dicts = [row_to_dict(r, table_name) for r in batch]
                if dicts:
                    conn.execute(model.__table__.insert(), dicts)
                print(f"  {min(i + BATCH_SIZE, total)}/{total}")

        # Reset the Postgres identity sequence so future auto-inserts don't
        # collide with the explicit ids we just wrote.
        with pg_engine.begin() as conn:
            from sqlalchemy import text
            max_id = conn.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table_name}")).scalar()
            conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), {max_id}, true)"
            ))
        print(f"  sequence reset to {max_id}")

    sqlite_session.close()
    print("Migration complete.")


if __name__ == "__main__":
    main()
