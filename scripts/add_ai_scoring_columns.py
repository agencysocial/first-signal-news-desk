"""
One-shot schema migration: adds the Phase 3 AI sub-score columns to
story_clusters on the live Postgres database. Idempotent (IF NOT EXISTS),
safe to re-run. Not part of the app's runtime.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(override=True)

from sqlalchemy import create_engine, text


def main():
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE story_clusters
            ADD COLUMN IF NOT EXISTS ai_emotional_strength FLOAT,
            ADD COLUMN IF NOT EXISTS ai_visual_potential FLOAT,
            ADD COLUMN IF NOT EXISTS ai_conversation_potential FLOAT,
            ADD COLUMN IF NOT EXISTS ai_novelty FLOAT,
            ADD COLUMN IF NOT EXISTS ai_scored_at TIMESTAMPTZ
        """))
    print("Migration complete.")


if __name__ == "__main__":
    main()
