"""Run one collection pass across all enabled sources, right now, and print
a per-source report. This is the fastest way to see the collector work
without leaving a server running.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Source
from app.collectors.rss import collect_source


def run():
    session = SessionLocal()
    try:
        sources = session.execute(select(Source).where(Source.enabled.is_(True))).scalars().all()
        if not sources:
            print("No enabled sources found. Run seeds/seed_sources.py first.")
            return

        totals = {"fetched": 0, "inserted": 0, "duplicates": 0, "canonical": 0}
        for source in sources:
            stats = collect_source(session, source)
            status = "OK" if not stats["error"] else f"ERROR: {stats['error']}"
            print(
                f"[{source.polling_tier:8s}] {source.name:30s} "
                f"fetched={stats['fetched']:3d} new={stats['inserted']:3d} "
                f"canonical={stats['canonical']:3d} dup={stats['duplicates']:3d}  {status}"
            )
            for k in ("fetched", "inserted", "duplicates", "canonical"):
                totals[k] += stats[k]

        print("-" * 70)
        print(
            f"TOTAL: fetched={totals['fetched']} new_raw={totals['inserted']} "
            f"canonical_stories={totals['canonical']} duplicates_caught={totals['duplicates']}"
        )
    finally:
        session.close()


if __name__ == "__main__":
    run()
