"""
Phase 3: AI content-judgment sub-scores. The rules-based coverage score
(app/scoring.py) can measure how many sources picked a story up and how
fast -- it has no way to judge whether the story ITSELF is the kind of
thing people react to. This module asks Claude (Haiku, cheap) to score
that missing half on 4 independent 0-100 dimensions from the original
spec: emotional strength, visual potential, conversation potential, and
novelty.

Fails soft everywhere: a network error, timeout, or malformed response
returns None rather than raising, so a Claude outage never blocks the
scanner from ingesting and clustering new stories. This is called from the
background poll loop, not a user-facing request, but the same discipline
applies as everywhere else in this codebase -- one flaky dependency must
not take down the whole scan.
"""
import json
import re

import httpx

from app.config import ANTHROPIC_API_KEY

_ENDPOINT = "https://api.anthropic.com/v1/messages"
_MODEL = "claude-haiku-4-5-20251001"
_TIMEOUT = 30

_DIMENSIONS = ("emotional_strength", "visual_potential", "conversation_potential", "novelty")

_PROMPT_TEMPLATE = """You are scoring a news story for social-media viral potential on 4 independent 0-100 dimensions. Respond with ONLY a JSON object, no other text, no markdown fences.

Story headline: {headline}
Category: {category}
Entities: {entities}

Score each dimension 0-100:
- emotional_strength: how much this triggers anger, fear, outrage, or excitement
- visual_potential: how well this maps to a concrete, dramatic visual scene
- conversation_potential: how much this invites debate, argument, or strong opinions
- novelty: how genuinely new/surprising this is, vs. a routine update

Respond with exactly this JSON shape: {{"emotional_strength": <int>, "visual_potential": <int>, "conversation_potential": <int>, "novelty": <int>}}"""

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _extract_json(text: str) -> dict | None:
    """Claude was explicitly told not to use markdown fences and used them
    anyway (confirmed live) -- strip ```/```json fences before parsing
    rather than assume a bare JSON response."""
    cleaned = _FENCE_RE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return None


def score_story_content(headline: str, category: str | None, entities: list[str]) -> dict | None:
    """Returns {"emotional_strength": float, "visual_potential": float,
    "conversation_potential": float, "novelty": float} or None on any
    failure. Never raises."""
    if not ANTHROPIC_API_KEY:
        return None

    prompt = _PROMPT_TEMPLATE.format(
        headline=headline, category=category or "general",
        entities=", ".join(entities) if entities else "none extracted",
    )
    try:
        r = httpx.post(
            _ENDPOINT,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={"model": _MODEL, "max_tokens": 200, "messages": [{"role": "user", "content": prompt}]},
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError:
        return None

    if r.status_code != 200:
        return None

    try:
        text = r.json()["content"][0]["text"]
    except (KeyError, IndexError, ValueError):
        return None

    parsed = _extract_json(text)
    if not parsed:
        return None

    try:
        scores = {dim: float(parsed[dim]) for dim in _DIMENSIONS}
    except (KeyError, TypeError, ValueError):
        return None

    if not all(0 <= v <= 100 for v in scores.values()):
        return None

    return scores
