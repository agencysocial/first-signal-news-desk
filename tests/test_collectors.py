import socket
from types import SimpleNamespace

import app.collectors.rss as rss_module


class FakeEntry(dict):
    """feedparser entries behave like dicts with .get()."""
    pass


def test_collect_source_handles_malformed_feed_gracefully(monkeypatch, session, make_source):
    source = make_source(name="Broken Feed")

    def fake_fetch(url, user_agent=None):
        return SimpleNamespace(entries=[], bozo=True, bozo_exception=Exception("not well-formed"))

    monkeypatch.setattr(rss_module, "_fetch_feed", fake_fetch)

    stats = rss_module.collect_source(session, source)

    assert stats["error"] is not None
    assert source.last_error is not None
    assert stats["inserted"] == 0


def test_collect_source_handles_network_exception_without_raising(monkeypatch, session, make_source):
    source = make_source(name="Unreachable Feed")

    def raising_fetch(url, user_agent=None):
        raise ConnectionError("could not connect")

    monkeypatch.setattr(rss_module, "_fetch_feed", raising_fetch)

    stats = rss_module.collect_source(session, source)  # must not raise

    assert stats["error"] is not None
    assert "could not connect" in source.last_error


def test_collect_source_handles_slow_source_via_timeout_not_a_hang(monkeypatch, session, make_source):
    """Regression test for a real production bug: feedparser.parse(url) has
    no network timeout, so a slow/unresponsive source (BBC World News, live)
    hung long enough to hit a Windows socket timeout (WinError 10060),
    stalling every other source queued behind it in the same scan -- which
    is what made a manual "Scan Now" look permanently stuck. _fetch_feed
    must raise a timeout error promptly (via urllib's `timeout=`) rather
    than let the collector hang indefinitely, and collect_source must
    handle that error the same as any other fetch failure.
    """
    source = make_source(name="Slow Feed")

    def timing_out_fetch(url, user_agent=None):
        raise socket.timeout("timed out")

    monkeypatch.setattr(rss_module, "_fetch_feed", timing_out_fetch)

    stats = rss_module.collect_source(session, source)  # must not raise or hang

    assert stats["error"] is not None
    assert "timed out" in source.last_error


def test_collect_source_inserts_and_clusters_valid_entries(monkeypatch, session, make_source):
    source = make_source(name="Good Feed")

    entries = [
        FakeEntry(link="https://example.com/a", title="City hall passes new ordinance",
                  summary="A summary.", author="Jane Doe", id="guid-1", published_parsed=None),
        FakeEntry(link="https://example.com/b", title="Second unrelated headline entirely",
                  summary="Another summary.", author=None, id="guid-2", published_parsed=None),
    ]

    def fake_fetch(url, user_agent=None):
        return SimpleNamespace(entries=entries, bozo=False)

    monkeypatch.setattr(rss_module, "_fetch_feed", fake_fetch)

    stats = rss_module.collect_source(session, source)

    assert stats["error"] is None
    assert stats["fetched"] == 2
    assert stats["inserted"] == 2
    assert source.last_error is None


def test_collect_source_skips_already_collected_urls(monkeypatch, session, make_source):
    source = make_source(name="Repeated Feed")
    entry = FakeEntry(link="https://example.com/same", title="Same story every time",
                       summary=None, author=None, id="guid-1", published_parsed=None)

    def fake_fetch(url, user_agent=None):
        return SimpleNamespace(entries=[entry], bozo=False)

    monkeypatch.setattr(rss_module, "_fetch_feed", fake_fetch)

    first_stats = rss_module.collect_source(session, source)
    second_stats = rss_module.collect_source(session, source)

    assert first_stats["inserted"] == 1
    assert second_stats["inserted"] == 0  # already collected this raw URL from this source


def test_collect_source_passes_per_source_user_agent_override(monkeypatch, session, make_source):
    """Regression test: Newsmax hangs specifically on the shared browser UA
    (confirmed live, 3/3 requests) but responds instantly to a plain UA --
    Politico needs the opposite. One shared UA can't satisfy both, so
    collect_source must pass the source's own override through when set."""
    source = make_source(name="Newsmax Politics")
    source.user_agent = "plain-ua/1.0"

    captured = {}

    def fake_fetch(url, user_agent=None):
        captured["user_agent"] = user_agent
        return SimpleNamespace(entries=[], bozo=False)

    monkeypatch.setattr(rss_module, "_fetch_feed", fake_fetch)
    rss_module.collect_source(session, source)

    assert captured["user_agent"] == "plain-ua/1.0"


def test_collect_source_passes_none_when_no_override_set(monkeypatch, session, make_source):
    """No override configured -- _fetch_feed must receive None so it falls
    back to the shared default UA, not silently break every other source."""
    source = make_source(name="Ordinary Feed")
    assert source.user_agent is None

    captured = {}

    def fake_fetch(url, user_agent=None):
        captured["user_agent"] = user_agent
        return SimpleNamespace(entries=[], bozo=False)

    monkeypatch.setattr(rss_module, "_fetch_feed", fake_fetch)
    rss_module.collect_source(session, source)

    assert captured["user_agent"] is None
