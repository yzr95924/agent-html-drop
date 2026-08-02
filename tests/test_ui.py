"""Smoke tests for the management page UI assets + handler."""
import http.client
import os
import threading

import pytest

from agent_html_drop import server as srv
from agent_html_drop import ui as ui_mod


@pytest.fixture
def ui_server():
    srv.routes.clear()
    ui_mod.register_routes()
    http = srv.make_server("127.0.0.1", 0, quiet=True)
    t = threading.Thread(target=http.serve_forever, daemon=True)
    t.start()
    try:
        yield http
    finally:
        http.shutdown()
        http.server_close()
        srv.routes.clear()


def _get(srv_, path):
    host, port = srv_.server_address
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("GET", path, headers={})
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        conn.close()


# --- assets exist on disk ---------------------------------------------------

def test_index_html_exists():
    assert os.path.isfile(os.path.join(ui_mod._UI_DIR, "index.html"))


def test_style_css_exists():
    assert os.path.isfile(os.path.join(ui_mod._UI_DIR, "style.css"))


def test_app_js_exists():
    assert os.path.isfile(os.path.join(ui_mod._UI_DIR, "app.js"))


# --- served correctly -------------------------------------------------------

def test_serves_index_html(ui_server):
    status, headers, body = _get(ui_server, "/")
    assert status == 200
    assert "text/html" in headers.get("Content-Type", "")
    assert b"agent-html-drop" in body
    assert b"<title>" in body


def test_serves_style_css(ui_server):
    status, headers, body = _get(ui_server, "/style.css")
    assert status == 200
    assert "text/css" in headers.get("Content-Type", "")
    assert b"--bg" in body  # CSS variable from style.css


def test_serves_app_js(ui_server):
    status, headers, body = _get(ui_server, "/app.js")
    assert status == 200
    assert "javascript" in headers.get("Content-Type", "")
    # Read-only for file list; anno mode uses Bearer in dialog only.
    assert b"localStorage" not in body


# --- no auth required on / --------------------------------------------------

def test_index_no_auth_required(ui_server):
    """The page is static; auth happens at /api/*."""
    status, _, _ = _get(ui_server, "/")
    assert status == 200


# --- HTML contains expected structure ---------------------------------------

def test_index_has_no_token_ui(ui_server):
    """The management page deliberately exposes no save-token button —
    the token only lives on the server config + the agent's MCP config,
    never persisted in the browser. (Annotation mode has a dialog where
    the user pastes the token per-session; nothing is stored.)"""
    _, _, body = _get(ui_server, "/")
    text = body.decode("utf-8")
    assert 'id="token-input"' not in text
    assert 'id="token-bar"' not in text
    assert 'id="token-save"' not in text
    # Required structure stays.
    assert 'id="file-tbody"' in text
    assert 'sandbox="allow-same-origin"' in text  # iframe sandbox for annotation DOM-walk


def test_app_js_does_not_store_token(ui_server):
    """The JS must not persist the token to any storage. Bearer is sent
    only as a one-shot Authorization header during the /api/auth login
    flow; nothing is kept client-side."""
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    assert "localStorage" not in text
    assert "sessionStorage" not in text


def test_app_js_handles_401_as_version_mismatch(ui_server):
    """If a 401 ever comes back, it's a version-mismatch (older daemon
    that still required Bearer) — surface a hint, not a token prompt."""
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    assert "r.status === 401" in text or "r.status == 401" in text
    assert "版本" in text or "version" in text.lower()


def test_app_js_uses_clipboard_for_copy(ui_server):
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    assert "clipboard" in text