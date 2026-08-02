"""Tests for agent_html_drop.auth_anno — cookie sign/verify, CSRF Origin check."""
import time

import pytest

from agent_html_drop.auth_anno import (
    sign_cookie, verify_cookie, csrf_check,
    ANNO_COOKIE_NAME, ANNO_COOKIE_MAX_AGE,
)
from agent_html_drop.config import Config, save_config


@pytest.fixture(autouse=True)
def annotation_auth_config(_isolate_agent_html_drop_state):
    save_config(_isolate_agent_html_drop_state["agent_html_drop_config_file"], Config(token="test-secret"))


def test_sign_cookie_format_is_pipe_separated():
    cookie = sign_cookie("tok-abc")
    parts = cookie.split("|")
    assert len(parts) == 3
    assert parts[0] == "tok-abc"


def test_sign_cookie_roundtrip():
    cookie = sign_cookie("tok-abc", max_age=60)
    assert verify_cookie(cookie) == "tok-abc"


def test_verify_cookie_expired_returns_none():
    cookie = sign_cookie("tok-abc", max_age=1)
    time.sleep(1.2)
    assert verify_cookie(cookie) is None


def test_verify_cookie_tampered_returns_none():
    cookie = sign_cookie("tok-abc")
    tampered = cookie[:-2] + "AA"
    assert verify_cookie(tampered) is None


def test_verify_cookie_garbage_returns_none():
    assert verify_cookie("not-a-cookie") is None
    assert verify_cookie("") is None


def test_anno_cookie_name_constant():
    assert ANNO_COOKIE_NAME == "anno_session"


def test_anno_cookie_max_age_is_30_minutes():
    assert ANNO_COOKIE_MAX_AGE == 1800


def test_csrf_check_no_origin_header_passes():
    assert csrf_check("notes.example.com", None) is True


def test_csrf_check_matching_origin_passes():
    assert csrf_check("notes.example.com", "https://notes.example.com") is True


def test_csrf_check_mismatched_origin_fails():
    assert csrf_check("notes.example.com", "https://evil.com") is False
    assert csrf_check("notes.example.com", "http://notes.example.com") is False


def test_csrf_check_origin_with_port_matches_hostname_only():
    assert csrf_check("notes.example.com:443", "https://notes.example.com") is True
