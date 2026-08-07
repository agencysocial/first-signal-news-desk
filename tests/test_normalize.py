from app.normalize import canonicalize_url, normalize_headline, compute_hashes, headline_tokens


def test_canonicalize_url_strips_tracking_params():
    url = "https://www.example.com/news/story?utm_source=fb&utm_medium=social&fbclid=abc123&id=42"
    result = canonicalize_url(url)
    assert "utm_source" not in result
    assert "fbclid" not in result
    assert "id=42" in result  # non-tracking params are kept


def test_canonicalize_url_strips_www_and_trailing_slash():
    assert canonicalize_url("https://WWW.Example.com/Story/") == canonicalize_url("https://example.com/Story")


def test_canonicalize_url_is_deterministic():
    url = "https://example.com/a?b=1&c=2"
    assert canonicalize_url(url) == canonicalize_url(url)


def test_normalize_headline_lowercases_and_strips_punctuation():
    assert normalize_headline("Trump Says: \"It's Over!\"") == "trump says it s over"


def test_normalize_headline_decodes_html_entities():
    assert "amp" not in normalize_headline("Cats &amp; Dogs")
    assert normalize_headline("Cats &amp; Dogs") == "cats dogs"


def test_normalize_headline_collapses_whitespace():
    assert normalize_headline("Too    many     spaces") == "too many spaces"


def test_compute_hashes_deterministic_and_distinct():
    h1 = compute_hashes("https://a.com/1", "same headline text", "desc")
    h2 = compute_hashes("https://a.com/1", "same headline text", "desc")
    h3 = compute_hashes("https://a.com/2", "different headline", "desc")
    assert h1 == h2
    assert h1 != h3


def test_headline_tokens_is_a_set_of_words():
    assert headline_tokens("iran launches strikes") == {"iran", "launches", "strikes"}
