from types import SimpleNamespace

import pytest
from starlette.requests import Request

import app.auth as auth_module
from app.auth import NotAuthenticated, get_user_role, require_user, verify_password_login


def _fake_scope(session: dict | None = None):
    return {
        "type": "http",
        "path": "/",
        "session": session if session is not None else {},
        "headers": [],
    }


def test_verify_password_login_returns_user_on_success(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        assert "grant_type=password" in url
        assert json == {"email": "john@agencysocial.com", "password": "correct-horse"}
        return SimpleNamespace(status_code=200, json=lambda: {"user": {"email": "john@agencysocial.com", "app_metadata": {"role": "admin"}}})

    monkeypatch.setattr(auth_module.httpx, "post", fake_post)

    user = verify_password_login("john@agencysocial.com", "correct-horse")
    assert user["email"] == "john@agencysocial.com"
    assert get_user_role(user) == "admin"


def test_verify_password_login_returns_none_on_bad_credentials(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        return SimpleNamespace(status_code=400, json=lambda: {"error": "invalid_grant"})

    monkeypatch.setattr(auth_module.httpx, "post", fake_post)

    assert verify_password_login("nobody@agencysocial.com", "wrong") is None


def test_verify_password_login_returns_none_on_network_error(monkeypatch):
    import httpx

    def raising_post(*a, **k):
        raise httpx.ConnectError("could not connect")

    monkeypatch.setattr(auth_module.httpx, "post", raising_post)

    assert verify_password_login("john@agencysocial.com", "anything") is None


def test_get_user_role_defaults_to_member_when_unset():
    assert get_user_role({"app_metadata": {}}) == "member"
    assert get_user_role({}) == "member"


def test_require_user_raises_when_no_session():
    request = Request(_fake_scope(session={}))
    with pytest.raises(NotAuthenticated):
        require_user(request)


def test_require_user_returns_user_dict_when_session_present():
    request = Request(_fake_scope(session={"email": "cathy@agencysocial.com", "role": "member"}))
    user = require_user(request)
    assert user == {"email": "cathy@agencysocial.com", "role": "member"}


def test_require_user_defaults_role_to_member_if_missing_from_session():
    request = Request(_fake_scope(session={"email": "cathy@agencysocial.com"}))
    user = require_user(request)
    assert user["role"] == "member"
