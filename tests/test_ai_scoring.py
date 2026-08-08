from types import SimpleNamespace

import pytest

import app.ai_scoring as ai_scoring_module
from app.ai_scoring import score_story_content

# Real Claude response body, captured live during scoping -- Claude was
# explicitly told not to use markdown fences and used them anyway, so the
# parser must handle this shape, not a hypothetical bare-JSON one.
REAL_RESPONSE_BODY = {
    "content": [
        {"type": "text", "text": '```json\n{"emotional_strength": 62, "visual_potential": 45, "conversation_potential": 78, "novelty": 35}\n```'}
    ],
}


def _fake_response(status_code=200, body=None):
    return SimpleNamespace(status_code=status_code, json=lambda: body or REAL_RESPONSE_BODY)


def test_score_story_content_parses_real_fenced_response(monkeypatch):
    monkeypatch.setattr(ai_scoring_module, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(ai_scoring_module.httpx, "post", lambda *a, **k: _fake_response())

    scores = score_story_content("Senate passes border security bill", "politics", ["Senate"])

    assert scores == {
        "emotional_strength": 62.0, "visual_potential": 45.0,
        "conversation_potential": 78.0, "novelty": 35.0,
    }


def test_score_story_content_returns_none_without_api_key(monkeypatch):
    monkeypatch.setattr(ai_scoring_module, "ANTHROPIC_API_KEY", "")

    def fail_if_called(*a, **k):
        raise AssertionError("must not call the network without a key")

    monkeypatch.setattr(ai_scoring_module.httpx, "post", fail_if_called)

    assert score_story_content("Headline", "politics", []) is None


def test_score_story_content_returns_none_on_network_error(monkeypatch):
    import httpx as real_httpx

    monkeypatch.setattr(ai_scoring_module, "ANTHROPIC_API_KEY", "test-key")

    def raising_post(*a, **k):
        raise real_httpx.ConnectError("could not connect")

    monkeypatch.setattr(ai_scoring_module.httpx, "post", raising_post)

    assert score_story_content("Headline", "politics", []) is None


def test_score_story_content_returns_none_on_non_200(monkeypatch):
    monkeypatch.setattr(ai_scoring_module, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(ai_scoring_module.httpx, "post", lambda *a, **k: _fake_response(status_code=529))

    assert score_story_content("Headline", "politics", []) is None


def test_score_story_content_returns_none_on_malformed_json(monkeypatch):
    monkeypatch.setattr(ai_scoring_module, "ANTHROPIC_API_KEY", "test-key")
    bad_body = {"content": [{"type": "text", "text": "not json at all"}]}
    monkeypatch.setattr(ai_scoring_module.httpx, "post", lambda *a, **k: _fake_response(body=bad_body))

    assert score_story_content("Headline", "politics", []) is None


def test_score_story_content_returns_none_on_missing_dimension(monkeypatch):
    """Response is valid JSON but incomplete -- must not silently substitute
    a default for a dimension Claude didn't actually score."""
    monkeypatch.setattr(ai_scoring_module, "ANTHROPIC_API_KEY", "test-key")
    incomplete_body = {"content": [{"type": "text", "text": '{"emotional_strength": 50, "visual_potential": 50}'}]}
    monkeypatch.setattr(ai_scoring_module.httpx, "post", lambda *a, **k: _fake_response(body=incomplete_body))

    assert score_story_content("Headline", "politics", []) is None


def test_score_story_content_returns_none_on_out_of_range_value(monkeypatch):
    monkeypatch.setattr(ai_scoring_module, "ANTHROPIC_API_KEY", "test-key")
    bad_range_body = {"content": [{"type": "text", "text": '{"emotional_strength": 150, "visual_potential": 50, "conversation_potential": 50, "novelty": 50}'}]}
    monkeypatch.setattr(ai_scoring_module.httpx, "post", lambda *a, **k: _fake_response(body=bad_range_body))

    assert score_story_content("Headline", "politics", []) is None


def test_score_story_content_handles_bare_json_without_fences(monkeypatch):
    """Even though the real response used fences, the parser shouldn't
    assume fences are always present -- confirm bare JSON also works."""
    monkeypatch.setattr(ai_scoring_module, "ANTHROPIC_API_KEY", "test-key")
    bare_body = {"content": [{"type": "text", "text": '{"emotional_strength": 10, "visual_potential": 20, "conversation_potential": 30, "novelty": 40}'}]}
    monkeypatch.setattr(ai_scoring_module.httpx, "post", lambda *a, **k: _fake_response(body=bare_body))

    scores = score_story_content("Headline", "politics", [])
    assert scores == {"emotional_strength": 10.0, "visual_potential": 20.0, "conversation_potential": 30.0, "novelty": 40.0}
