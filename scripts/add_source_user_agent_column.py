"""
One-shot schema migration: adds Source.user_agent (per-source User-Agent
override) to the live Postgres database. Idempotent (IF NOT EXISTS), safe
to re-run. Not part of the app's runtime.
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
        conn.execute(text("ALTER TABLE sources ADD COLUMN IF NOT EXISTS user_agent TEXT"))
    print("Migration complete.")


if __name__ == "__main__":
    main()
