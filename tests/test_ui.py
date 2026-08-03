"""Smoke tests for the management page UI assets + handler."""
import http.client
import os
import re
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


def test_filename_link_has_color_rule():
    """Regression: file-table 名称列的 <a> 必须有显式 color 规则。

    没这条规则时，浏览器 user-agent 默认 link 颜色（深蓝 #0000ee）
    在 --bg #0f1115 黑色背景上对比度只有 ~2.0，深色模式下根本看不见。
    """
    text = open(os.path.join(ui_mod._UI_DIR, "style.css"), encoding="utf-8").read()
    assert "#file-table td a" in text, (
        "style.css 没有定义 #file-table td a 的颜色；"
        "浏览器默认 link 蓝色在深色背景上不可读。"
    )
    # 也确认它用了 accent 变量而不是写死深色 hex
    assert "color: var(--accent)" in text


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


def test_serves_anno_viewer_js(ui_server):
    """The public-page annotation viewer is served as a static asset at
    /anno-viewer.js (injected into annotated /files/*.html by the daemon)."""
    status, headers, body = _get(ui_server, "/anno-viewer.js")
    assert status == 200
    assert "javascript" in headers.get("Content-Type", "")
    assert b"buildTextMap" in body  # the highlight core is present


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
    """The bearer token must NEVER be persisted client-side — it's a one-shot
    Authorization header in the /api/auth login flow. localStorage is permitted
    ONLY for non-credential layout prefs (sidebar fold state). All storage
    access is funneled through the lsBool/lsSetBool helpers, and the only keys
    ever used are the layout-pref allowlist below — so the token can't reach it."""
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    # sessionStorage is never used.
    assert "sessionStorage" not in text
    # Single chokepoint: storage is touched in exactly one read + one write
    # (inside the helpers). A second site would bypass the key allowlist.
    assert text.count("localStorage.getItem") == 1
    assert text.count("localStorage.setItem") == 1
    # The only storage keys are non-credential layout prefs — never the token.
    allowed = {"agent-html-drop:annoCollapsed", "agent-html-drop:tocHidden"}
    used = set(re.findall(r'"(agent-html-drop:[\w-]+)"', text))
    assert used <= allowed, "unexpected localStorage keys: %r" % (used - allowed)
    # Belt-and-suspenders: the auth token never reaches a storage write.
    assert "lsSetBool(token" not in text


def test_app_js_handles_401_as_version_mismatch(ui_server):
    """If a 401 ever comes back, it's a version-mismatch (older daemon
    that still required Bearer) — surface a hint, not a token prompt."""
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    assert "r.status === 401" in text or "r.status == 401" in text
    assert "版本" in text or "version" in text.lower()


def test_url_column_uses_ui_font_not_monospace():
    """Regression: 公开 URL 列应该用系统 UI 字体（圆润），不是 monospace。

    URL 是给用户复制粘贴的，不是读代码；monospace + 12px 让整列看起来
    "硬"且偏小。body 已经设了 -apple-system / Segoe UI / system-ui，
    td 默认继承。tdUrl 上不要再写 monospace。
    """
    text = open(os.path.join(ui_mod._UI_DIR, "app.js"), encoding="utf-8").read()
    idx = text.find("var tdUrl = document.createElement")
    assert idx >= 0, "tdUrl 渲染逻辑不见了"
    # 精确检测：只看 tdUrl.style.fontFamily 这一行（注释里出现"monospace"
    # 这个单词不应误判）
    font_lines = [
        ln for ln in text[idx:idx + 800].splitlines()
        if "tdUrl.style.fontFamily" in ln
    ]
    assert not any("monospace" in ln for ln in font_lines), (
        "tdUrl.style.fontFamily 设成了 monospace；URL 列应该继承 body "
        "的圆润 UI 字体。被检测到: {!r}".format(font_lines)
    )


def test_app_js_uses_clipboard_for_copy(ui_server):
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    assert "clipboard" in text