"""Create all tables. Safe to re-run (create_all is idempotent)."""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import Base, engine
from app import models  # noqa: F401  -- import registers models on Base.metadata

if __name__ == "__main__":
    Base.metadata.create_all(engine)
    print("Tables created:", list(Base.metadata.tables.keys()))
