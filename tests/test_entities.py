from app.entities import (
    strip_source_suffix, extract_entities, extract_keywords, extract_location,
)


def test_strip_source_suffix_removes_google_news_outlet():
    assert strip_source_suffix("Big story happens here - CBS News") == "Big story happens here"


def test_strip_source_suffix_handles_hyphenated_outlet_names():
    # Regression: "Yakima Herald-Republic" has its own internal hyphen.
    # Excluding hyphens from the suffix match left "Herald-Republic"
    # fragments in the text, which then got extracted as fake entities
    # that matched between ANY two unrelated stories from that outlet.
    headline = "Immigration a key issue in 4th District race in Central WA - Yakima Herald-Republic"
    assert strip_source_suffix(headline) == "Immigration a key issue in 4th District race in Central WA"


def test_strip_source_suffix_leaves_short_headlines_alone():
    # Guard against stripping a real hyphen-joined headline down to nothing
    headline = "Man vs wild - a short one"
    result = strip_source_suffix(headline)
    assert len(result) > 10


def test_extract_entities_finds_proper_noun_runs():
    entities = extract_entities("Federal Bureau of Investigation raids office in Ohio")
    assert "Federal Bureau of Investigation" in entities


def test_extract_entities_excludes_headline_boilerplate():
    entities = extract_entities("Breaking News: Congress passes new bill - Reuters")
    lowered = [e.lower() for e in entities]
    assert "breaking news" not in lowered
    assert "the latest" not in lowered


def test_extract_entities_excludes_short_common_words():
    # "As" is followed by a lowercase word, so it stands alone as a run and
    # should be filtered as a stopword rather than kept as a bare entity.
    entities = extract_entities("As talks continue, officials meet in the region")
    assert "As" not in entities


def test_extract_keywords_filters_stopwords_and_short_tokens():
    keywords = extract_keywords("the man was at the store and it was a big deal")
    assert "the" not in keywords
    assert "was" not in keywords
    assert "store" in keywords


def test_extract_location_matches_known_city_and_state():
    assert extract_location("Fire breaks out in Chicago overnight") == "Chicago"
    assert extract_location("New tax law passes in Texas") == "Texas"


def test_extract_location_returns_none_when_no_match():
    assert extract_location("Global markets react to earnings report") is None
