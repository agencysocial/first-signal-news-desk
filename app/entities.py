"""
Best-effort entity/keyword/location extraction. Deliberately a simple
heuristic, not an ML model -- per the spec, "a simple noun-phrase/proper-noun
extractor is fine, no ML model required yet" for Phase 1.
"""
import re

STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "but",
    "is", "are", "was", "were", "be", "been", "with", "by", "from", "as",
    "that", "this", "it", "its", "after", "before", "over", "under", "into",
    "about", "amid", "his", "her", "their", "they", "he", "she", "new",
    "says", "say", "said", "will", "has", "have", "had", "not", "no", "than",
}

# Google News RSS always appends " - Outlet Name" to the headline; strip it
# before extraction so outlet names don't pollute entities/keywords. Must NOT
# exclude hyphens from the suffix itself -- outlet names like "Yakima
# Herald-Republic" have their own internal hyphen, and excluding hyphens left
# "Herald"/"Republic" fragments in the text, extracted as fake entities that
# then matched ANY two unrelated articles from that same outlet (a real
# incorrect merge: two Yakima Herald-Republic stories with nothing else in
# common at all).
_SOURCE_SUFFIX_RE = re.compile(r"\s+-\s+.{2,60}$")


def strip_source_suffix(headline: str) -> str:
    m = _SOURCE_SUFFIX_RE.search(headline)
    if m and len(headline) - len(m.group(0)) > 15:
        return headline[: m.start()]
    return headline


_CAP_RUN_RE = re.compile(
    r"\b[A-Z][a-zA-Z.]*(?:\s+(?:[A-Z][a-zA-Z.]*|of|and|for|the))*\b"
)

# Headline boilerplate that the capitalization heuristic mistakes for named
# entities -- these aren't a "who/what" of the story, they're wire-service
# preamble.
_ENTITY_BLOCKLIST = {
    "the latest", "breaking news", "live updates", "opinion", "analysis",
    "exclusive", "watch live", "as it happened", "developing story",
}

# Entities that show up in nearly every day's US political news. Shared
# ONLY generic entities (no specific one) is deliberately a weak clustering
# signal -- see GENERIC_ENTITIES usage in app/clustering.py. Two different
# stories both mentioning "Trump" and "the U.S." is not evidence they're the
# same story.
GENERIC_ENTITIES = {
    "trump", "biden", "vance", "harris", "white house", "the white house",
    "congress", "senate", "house", "u.s", "u.s.", "us", "usa",
    "united states", "america", "american", "washington",
}


def extract_entities(headline: str) -> list[str]:
    text = strip_source_suffix(headline)

    # Many press-release-style sources (FBI/DOJ especially) Title Case their
    # whole headline, e.g. "Sinaloa Cartel Kingpin 'El Mayo' Sentenced in
    # U.S. to Life in Prison" -- when most words are capitalized, capitalization
    # stops meaning "proper noun" and this heuristic would extract generic
    # words like "Sentenced" or "Prison" as if they were named entities.
    # Two unrelated sentencing stories both matching on shared "Sentenced" +
    # "Prison" caused a real incorrect merge. Skip entity extraction entirely
    # for headlines where the signal is this unreliable; keyword/headline-text
    # matching still applies.
    words = text.split()
    if len(words) >= 5:
        capitalized = sum(1 for w in words if w[:1].isupper())
        if capitalized / len(words) >= 0.6:
            return []

    candidates = []
    for m in _CAP_RUN_RE.finditer(text):
        run = m.group(0).strip()
        words = run.split()
        if run.lower() in _ENTITY_BLOCKLIST:
            continue
        if len(words) == 1 and words[0].lower() in STOPWORDS:
            continue
        if len(words) == 1 and len(words[0]) < 3:
            continue
        candidates.append(run)

    seen, out = set(), []
    for c in candidates:
        key = c.lower()
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out[:8]


def extract_keywords(normalized_headline: str) -> list[str]:
    tokens = [t for t in normalized_headline.split() if len(t) > 3 and t not in STOPWORDS]
    seen, out = set(), []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:12]


_US_STATES = {
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming",
}

_US_CITIES = {
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix",
    "Philadelphia", "San Antonio", "San Diego", "Dallas", "Austin",
    "Washington", "Boston", "Seattle", "Denver", "Detroit", "Miami",
    "Atlanta", "Portland", "Minneapolis", "Baltimore", "Louisville",
    "Milwaukee", "Las Vegas", "Nashville", "Charlotte", "Columbus",
    "Indianapolis", "San Francisco", "San Jose", "Jacksonville",
    "Kansas City", "Sacramento", "Orlando", "Pittsburgh", "St. Louis",
    "Salt Lake City", "Cincinnati", "Memphis", "New Orleans",
}

_US_LOCATIONS_SORTED = sorted(_US_STATES | _US_CITIES, key=len, reverse=True)

# Exposed so clustering.py can exclude place names from "specific entity"
# credit -- a shared city/state (e.g. two different Miami stories) is not
# evidence two articles are the same story, any more than shared "Trump" is.
KNOWN_LOCATIONS = {loc.lower() for loc in (_US_STATES | _US_CITIES)}


def extract_location(headline: str) -> str | None:
    text = strip_source_suffix(headline)
    for loc in _US_LOCATIONS_SORTED:
        if re.search(rf"\b{re.escape(loc)}\b", text):
            return loc
    return None
