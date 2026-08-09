"""
Regression test for a real operator-reported bug: picking a category filter
then clicking a time-window quick-filter chip (e.g. "Last 6h") dropped the
category and reset to a general search. Root cause: each chip only ever
encoded its own single param, discarding every other active filter.
"""
from app.render import render_wire_page


def _filters(**overrides):
    base = {
        "category": None, "status": None, "verification": None,
        "source_id": None, "window": None, "min_viral": None,
        "min_confidence": None, "exclude_covered": False,
    }
    base.update(overrides)
    return base


def test_window_chip_preserves_active_category_filter():
    html = render_wire_page(
        [], [], filters=_filters(category="trump"),
        categories=["trump"], sources=[], statuses=[],
    )
    import re
    from urllib.parse import urlsplit, parse_qs
    href = re.search(r'<a href="([^"]*)"[^>]*>Last 6h</a>', html).group(1)
    qs = parse_qs(urlsplit(href).query)
    assert qs.get("category") == ["trump"]
    assert qs.get("window") == ["6h"]


def test_window_chip_preserves_multiple_active_filters():
    html = render_wire_page(
        [], [], filters=_filters(category="trump", min_viral=50),
        categories=["trump"], sources=[], statuses=[],
    )
    assert "window=6h" in html
    assert "category=trump" in html
    assert "min_viral=50" in html
    # confirm all three land on the same "Last 6h" anchor, not three separate links
    import re
    m = re.search(r'<a href="([^"]*window=6h[^"]*)"[^>]*>Last 6h</a>', html)
    assert m, "could not find the Last 6h chip"
    href = m.group(1)
    assert "category=trump" in href
    assert "min_viral=50" in href


def test_all_chip_is_a_true_reset_even_with_active_filters():
    html = render_wire_page(
        [], [], filters=_filters(category="trump", window="6h"),
        categories=["trump"], sources=[], statuses=[],
    )
    import re
    m = re.search(r'<a href="([^"]*)"[^>]*>All</a>', html)
    assert m, "could not find the All chip"
    href = m.group(1)
    assert "category" not in href
    assert "window" not in href


def test_category_filter_persists_after_clicking_window_chip_end_to_end():
    """Simulates the exact reported sequence: category picked, then a
    window chip clicked -- the chip's own href must be the URL that gets
    navigated to next, and it must carry the category forward."""
    html = render_wire_page(
        [], [], filters=_filters(category="trump"),
        categories=["trump"], sources=[], statuses=[],
    )
    import re
    six_hr_link = re.search(r'<a href="([^"]*)"[^>]*>Last 6h</a>', html).group(1)
    # Parse the query string the way the real route would
    from urllib.parse import urlsplit, parse_qs
    qs = parse_qs(urlsplit(six_hr_link).query)
    assert qs.get("category") == ["trump"]
    assert qs.get("window") == ["6h"]
