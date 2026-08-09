"""
Regression test for a real operator-reported bug: the scheduled poller (and
"Scan Now" / per-source "Fetch now") was treating twitter_manual sources as
pollable RSS feeds, fetching the author's Twitter profile page and trying to
parse it as XML -- producing "parse failed: not well-formed (invalid token)"
errors for every manually-captured Twitter source, every scan cycle.
twitter_manual sources have no feed; they're populated only by an explicit
/capture/twitter POST, never by polling.
"""
import app.main as main_module
from app.models import Source


def _make_rss_source(session, name="RSS Source", tier="standard"):
    src = Source(name=name, type="rss", url="https://example.com/feed", category="general",
                 credibility_tier=3, polling_tier=tier, enabled=True)
    session.add(src)
    session.flush()
    return src


def _make_twitter_manual_source(session, name="Some Author (X)"):
    src = Source(name=name, type="twitter_manual", url="https://x.com/someauthor",
                 category=None, credibility_tier=2, polling_tier="standard", enabled=True)
    session.add(src)
    session.flush()
    return src


def _patch_session(monkeypatch, session):
    session.close = lambda: None  # let the real `session` fixture own teardown
    monkeypatch.setattr(main_module, "SessionLocal", lambda: session)


def test_poll_tier_skips_twitter_manual_sources(monkeypatch, session):
    _make_rss_source(session, name="Real Feed")
    _make_twitter_manual_source(session, name="jack (X)")
    _patch_session(monkeypatch, session)

    called_with = []
    monkeypatch.setattr(main_module, "collect_source", lambda s, src: called_with.append(src.name) or {"fetched": 0, "inserted": 0, "duplicates": 0, "canonical": 0, "error": None})

    main_module.poll_tier("standard")

    assert "Real Feed" in called_with
    assert "jack (X)" not in called_with


def test_run_full_scan_skips_twitter_manual_sources(monkeypatch, session):
    _make_rss_source(session, name="Real Feed")
    _make_twitter_manual_source(session, name="folkhero (X)")
    _patch_session(monkeypatch, session)
    monkeypatch.setattr(main_module, "_scan_state", {"running": False, "completed_unacknowledged": False, "last_result": None})

    called_with = []
    monkeypatch.setattr(main_module, "collect_source", lambda s, src: called_with.append(src.name) or {"fetched": 0, "inserted": 0, "duplicates": 0, "canonical": 0, "error": None})

    main_module.run_full_scan()

    assert "Real Feed" in called_with
    assert "folkhero (X)" not in called_with


def test_non_pollable_source_types_includes_twitter_manual():
    assert "twitter_manual" in main_module.NON_POLLABLE_SOURCE_TYPES
