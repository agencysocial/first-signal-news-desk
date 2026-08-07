import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import adapter_to_first_signal as adapter  # noqa: E402


def _make_record(cluster_id, headline, viral, sources):
    return {
        "cluster_id": cluster_id,
        "canonical_headline": headline,
        "category": "politics",
        "status": "Developing",
        "verification_status": "multi_source",
        "scores": {"viral_score_preliminary": viral, "confidence_score": 65.0, "momentum_score": 70.0},
        "entities": ["Trump"],
        "keywords": ["trump", "tariffs"],
        "location": None,
        "first_detected_at": "2026-07-21T00:00:00+00:00",
        "latest_update_at": "2026-07-21T00:05:00+00:00",
        "sources": sources,
        "generated_at": "2026-07-21T00:06:00+00:00",
    }


def test_clean_headline_strips_google_news_suffix():
    assert adapter.clean_headline("Big story happens here - CBS News") == "Big story happens here"


def test_clean_headline_leaves_short_headlines_alone():
    headline = "Man vs wild - a short one"
    assert len(adapter.clean_headline(headline)) > 10


def test_record_to_post_uses_primary_source_url_for_both_url_fields():
    record = _make_record(1, "Test headline", 80.0, [
        {"source_name": "NPR", "headline": "Test headline", "url": "https://npr.org/a", "tier": 2, "published_at": None},
        {"source_name": "CBS", "headline": "Test headline - CBS", "url": "https://cbsnews.com/a", "tier": 2, "published_at": None},
    ])
    post = adapter.record_to_post(record)
    assert post["url"] == "https://npr.org/a"
    assert post["post_url"] == "https://npr.org/a"
    assert post["image_url"] == "https://npr.org/a"


def test_record_to_post_strips_outlet_suffix_from_headline():
    headline = "Senate passes major infrastructure funding bill after long debate - NPR"
    record = _make_record(1, headline, 80.0, [
        {"source_name": "NPR", "headline": headline, "url": "https://npr.org/a", "tier": 2, "published_at": None},
    ])
    post = adapter.record_to_post(record)
    assert post["text"] == "Senate passes major infrastructure funding bill after long debate"


def test_record_to_post_never_fabricates_a_url_when_no_sources():
    record = _make_record(1, "Headline with no sources somehow", 50.0, [])
    post = adapter.record_to_post(record)
    assert post["url"] == ""
    assert post["image_url"] == ""


def test_convert_orders_by_viral_score_descending():
    records = [
        _make_record(1, "Low viral story", 40.0, [{"source_name": "A", "headline": "x", "url": "https://a.com", "tier": 2, "published_at": None}]),
        _make_record(2, "High viral story", 90.0, [{"source_name": "B", "headline": "x", "url": "https://b.com", "tier": 2, "published_at": None}]),
        _make_record(3, "Mid viral story", 65.0, [{"source_name": "C", "headline": "x", "url": "https://c.com", "tier": 2, "published_at": None}]),
    ]
    posts = adapter.convert(records)
    assert [p["text"] for p in posts] == ["High viral story", "Mid viral story", "Low viral story"]


def test_load_handoff_records_by_date(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "HANDOFF_DIR", tmp_path)
    day_dir = tmp_path / "2026-07-21"
    day_dir.mkdir()
    record = _make_record(42, "A real story", 75.0, [
        {"source_name": "NPR", "headline": "A real story", "url": "https://npr.org/x", "tier": 2, "published_at": None},
    ])
    (day_dir / "42.json").write_text(json.dumps(record), encoding="utf-8")

    records = adapter.load_handoff_records(date="2026-07-21", cluster_id=None)
    assert len(records) == 1
    assert records[0]["cluster_id"] == 42


def test_load_handoff_records_by_cluster_id_searches_all_dates(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "HANDOFF_DIR", tmp_path)
    day_dir = tmp_path / "2026-07-20"
    day_dir.mkdir()
    record = _make_record(99, "Another real story", 60.0, [
        {"source_name": "CBS", "headline": "Another real story", "url": "https://cbsnews.com/y", "tier": 2, "published_at": None},
    ])
    (day_dir / "99.json").write_text(json.dumps(record), encoding="utf-8")

    records = adapter.load_handoff_records(date=None, cluster_id=99)
    assert len(records) == 1
    assert records[0]["cluster_id"] == 99


def test_main_writes_expected_shape_to_out_path(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "HANDOFF_DIR", tmp_path)
    day_dir = tmp_path / "2026-07-21"
    day_dir.mkdir()
    record = _make_record(7, "Headline for main test - Reuters", 55.0, [
        {"source_name": "Reuters", "headline": "x", "url": "https://reuters.com/z", "tier": 1, "published_at": None},
    ])
    (day_dir / "7.json").write_text(json.dumps(record), encoding="utf-8")

    out_path = tmp_path / "output" / "posts.json"
    monkeypatch.setattr(sys, "argv", [
        "adapter_to_first_signal.py", "--date", "2026-07-21", "--out", str(out_path),
    ])
    adapter.main()

    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(written) == 1
    assert written[0]["text"] == "Headline for main test"
    assert written[0]["url"] == "https://reuters.com/z"
