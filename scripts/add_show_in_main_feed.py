"""Migration: add show_in_main_feed column to sources table."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sqlalchemy import text
from app.db import engine

with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE sources ADD COLUMN show_in_main_feed BOOLEAN NOT NULL DEFAULT 1"))
        conn.commit()
        print("Migration complete: show_in_main_feed added to sources.")
    except Exception as e:
        if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
            print("Column already exists — skipping.")
        else:
            raise
