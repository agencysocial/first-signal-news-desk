from collections import Counter

from app.clustering import assign_cluster, get_cluster_for_normalized_article, _score_against_cluster


def test_unrelated_stories_from_same_hyphenated_outlet_do_not_merge(session, make_source, ingest_article):
    """Regression test for a sixth incorrect-merge bug: two completely
    unrelated stories (a congressional-race piece and an unrelated stabbing
    case) both from "Yakima Herald-Republic" merged, because the outlet's
    own hyphenated name leaked past strip_source_suffix and got extracted as
    fake entities ("Yakima Herald", "Republic") shared by definition between
    any two articles from that outlet -- not evidence they're the same
    story. Fixed in the suffix-stripping regex (see test_entities.py).
    """
    source = make_source(name="Google News: immigration")

    headline_a = "Immigration a key issue in 4th District congressional race in Central WA - Yakima Herald-Republic"
    a1 = ingest_article(source, headline_a)
    cluster_1 = assign_cluster(session, a1, raw_headline=headline_a)

    headline_b = "Naches woman charged in connection with stabbing father - Yakima Herald-Republic"
    a2 = ingest_article(source, headline_b)
    cluster_2 = assign_cluster(session, a2, raw_headline=headline_b)

    assert cluster_1.id != cluster_2.id


def test_similar_articles_with_shared_specific_entity_cluster_together(session, make_source, ingest_article):
    source_a = make_source(name="Outlet A")
    source_b = make_source(name="Outlet B")

    headline_a = "Hurricane Delta slams Florida coast overnight"
    a1 = ingest_article(source_a, headline_a)
    c1 = assign_cluster(session, a1, raw_headline=headline_a)

    headline_b = "Hurricane Delta makes landfall along Florida coast"
    a2 = ingest_article(source_b, headline_b)
    c2 = assign_cluster(session, a2, raw_headline=headline_b)

    assert c1.id == c2.id
    assert c1.source_count == 2


def test_unrelated_articles_sharing_only_generic_entities_do_not_merge(session, make_source, ingest_article):
    """Regression test for the incorrect-merge bug found in Phase 1b: an
    unrelated Supreme Court/asylum story got merged into an Iran-strikes
    cluster because the two headlines shared exactly two entities -- "Trump"
    and "U.S." -- both of which appear in nearly every US political headline.
    The old formula gave 2+ shared entities full match credit regardless of
    how generic they were (entity_overlap/2, capped at 1.0), so two shared
    generic entities alone (0.5 * 1.0 = 0.5) cleared the 0.45 merge threshold
    with zero regard for how different the actual stories were.

    These two headlines are built to share exactly "Trump" + "U.S." and
    nothing else specific, reproducing that exact mechanism.
    """
    source_a = make_source(name="Outlet A")
    source_b = make_source(name="Outlet B")

    headline_a = "Trump says U.S. forces will strike Iran again this week"
    a1 = ingest_article(source_a, headline_a)
    cluster_1 = assign_cluster(session, a1, raw_headline=headline_a)

    headline_b = (
        "Breaking News: The Supreme Court allows Trump administration to "
        "enforce U.S. asylum rules at Mexico border"
    )
    a2 = ingest_article(source_b, headline_b)
    cluster_2 = assign_cluster(session, a2, raw_headline=headline_b)

    assert cluster_1.id != cluster_2.id


def test_unrelated_articles_sharing_only_a_common_city_do_not_merge(session, make_source, ingest_article):
    """Regression test for a second incorrect-merge bug found after adding
    more sources: a citizenship-case story, the Tate brothers arrest, and an
    unrelated FBI robbery press release all merged into one cluster because
    all three happened to be Miami-based. "Miami" alone was extracted both as
    a location AND as a capitalized single-word "entity", so it was scored
    as if it were a specific, distinguishing entity (0.6 credit) on top of
    the separate location bonus (0.15) -- enough to clear 0.45 with a
    genuinely unrelated story that shared nothing else at all.

    Two headlines here share only "Miami" and nothing else specific.
    """
    source_a = make_source(name="Outlet A")
    source_b = make_source(name="Outlet B")

    headline_a = "Tate brothers arrested in Miami following sex crime allegations"
    a1 = ingest_article(source_a, headline_a)
    cluster_1 = assign_cluster(session, a1, raw_headline=headline_a)

    headline_b = (
        "Colombian Transnational Robbery Crew Member Pleads Guilty to "
        "$5 Million-Dollar Organized Jewelry Theft Ring in Miami"
    )
    a2 = ingest_article(source_b, headline_b)
    cluster_2 = assign_cluster(session, a2, raw_headline=headline_b)

    assert cluster_1.id != cluster_2.id


def test_title_cased_press_release_headlines_do_not_merge_on_generic_words(session, make_source, ingest_article):
    """Regression test for a fifth incorrect-merge bug: two unrelated FBI
    press releases (a Sinaloa cartel kingpin's sentencing, and an unrelated
    Gambian man's torture conviction) merged because both headlines are
    Title Cased -- FBI/DOJ press-release convention capitalizes nearly every
    word, so the capitalization-run heuristic extracted generic words like
    "Sentenced" and "Prison" as if they were named entities, and those two
    matched. Fixed in extract_entities: when most of a headline's words are
    capitalized, capitalization no longer signals "proper noun" and entity
    extraction is skipped for that headline entirely.
    """
    source_a = make_source(name="Outlet A")
    source_b = make_source(name="Outlet B")

    headline_a = "Sinaloa Cartel Kingpin 'El Mayo' Sentenced in U.S. to Life in Prison"
    a1 = ingest_article(source_a, headline_a)
    cluster_1 = assign_cluster(session, a1, raw_headline=headline_a)

    headline_b = (
        "Gambian Man, First Non-U.S. National Convicted of Torture, "
        "Sentenced to More Than 67 Years in Prison"
    )
    a2 = ingest_article(source_b, headline_b)
    cluster_2 = assign_cluster(session, a2, raw_headline=headline_b)

    assert cluster_1.id != cluster_2.id


def test_one_shared_specific_entity_without_headline_support_does_not_merge(session, make_source, ingest_article):
    """Regression test for a fourth incorrect-merge bug: a New York Times
    media-criticism story about ICE reporting merged with an unrelated "anti-
    ICE" incendiary device story, because both mentioned "ICE" (Immigration
    and Customs Enforcement) -- an extremely common current-news acronym
    that isn't in GENERIC_ENTITIES, isn't a place name, and hadn't yet
    accumulated enough frequency across other clusters to be caught by the
    entity_frequency check. One shared specific-looking entity with no real
    headline-text corroboration must not be sufficient on its own -- this is
    the rule-gated design's actual fix (CLUSTER_MIN_HEADLINE_SCORE_WITH_ONE_ENTITY),
    not reliant on frequency accumulation timing.
    """
    source_a = make_source(name="Outlet A")
    source_b = make_source(name="Outlet B")

    headline_a = "New York Times torched for 'FALSE' reporting on ICE investigations, outlet fires back"
    a1 = ingest_article(source_a, headline_a)
    cluster_1 = assign_cluster(session, a1, raw_headline=headline_a)

    headline_b = "Suspect named in New York City alleged incendiary device attack, had 'anti-ICE stuff' on him"
    a2 = ingest_article(source_b, headline_b)
    cluster_2 = assign_cluster(session, a2, raw_headline=headline_b)

    assert cluster_1.id != cluster_2.id


def test_entity_common_across_many_active_clusters_is_not_a_specific_signal():
    """Unit-level regression test for a third incorrect-merge bug: during
    World Cup week, "World Cup" and "Spain" both showed up in many unrelated
    sub-stories (a death, Trump's remarks, the victors' parade). Neither
    term is in the hardcoded GENERIC_ENTITIES or KNOWN_LOCATIONS lists (they
    aren't inherently generic words), but they became generic FOR THIS NEWS
    CYCLE -- exactly the case a fixed blocklist can never anticipate, and
    why entity_frequency exists as a dynamic, self-correcting check.
    """
    # "World Cup" appears in 5 other currently-active clusters this batch --
    # over the threshold, so it should no longer count as a specific signal.
    freq = Counter({"world cup": 5, "spain": 1})

    article_tokens = {"different", "story", "entirely", "about", "something", "else"}
    article_entities = ["World Cup", "Spain"]

    class FakeCluster:
        entities = '["World Cup", "Spain"]'
        keywords = '["boy", "dies", "during", "celebrations"]'
        location = None

    is_match, _ = _score_against_cluster(article_tokens, article_entities, FakeCluster(), freq)
    # "world cup" is suppressed by frequency, leaving only "spain" as a
    # single specific shared entity -- with zero headline-text overlap to
    # corroborate it, that's not enough to match under the rule-gated
    # design (it would have been under the old additive-threshold design,
    # where 2 "specific-looking" shared entities crossed 0.45 alone).
    assert not is_match


def test_duplicate_article_inherits_canonical_cluster_without_rescoring(session, make_source, ingest_article):
    source_a = make_source(name="Outlet A")
    source_b = make_source(name="Outlet B")
    shared_url = "https://news.example.com/wire-story"

    a1 = ingest_article(source_a, "Storm forces evacuations along the coast", url=shared_url)
    cluster_1 = assign_cluster(session, a1, raw_headline="Storm forces evacuations along the coast")

    # Same URL -> Level 1 exact dedup -> should inherit cluster_1 directly,
    # regardless of how different its own wording might otherwise cluster.
    a2 = ingest_article(source_b, "Completely unrelated wording", url=shared_url)
    cluster_2 = assign_cluster(session, a2, raw_headline="Completely unrelated wording")

    assert a2.duplicate_of_id == a1.id
    assert cluster_2.id == cluster_1.id
    assert get_cluster_for_normalized_article(session, a2.id).id == cluster_1.id


def test_status_auto_transitions_new_to_developing_at_two_sources(session, make_source, ingest_article):
    source_a = make_source(name="Outlet A")
    source_b = make_source(name="Outlet B")

    a1 = ingest_article(source_a, "City council approves new zoning law")
    cluster = assign_cluster(session, a1, raw_headline="City council approves new zoning law")
    assert cluster.status == "New"

    a2 = ingest_article(source_b, "City council approves new zoning law for downtown")
    cluster = assign_cluster(session, a2, raw_headline="City council approves new zoning law for downtown")
    assert cluster.status == "Developing"


def test_covered_story_reopens_on_new_development(session, make_source, ingest_article):
    source_a = make_source(name="Outlet A")
    source_b = make_source(name="Outlet B")

    a1 = ingest_article(source_a, "Mayor announces new infrastructure plan")
    cluster = assign_cluster(session, a1, raw_headline="Mayor announces new infrastructure plan")

    cluster.status = "Covered"
    session.flush()

    a2 = ingest_article(source_b, "Mayor announces new infrastructure plan with added funding")
    cluster_after = assign_cluster(session, a2, raw_headline="Mayor announces new infrastructure plan with added funding")

    assert cluster_after.id == cluster.id
    assert cluster_after.status == "Developing"
    assert cluster_after.covered_at is None
