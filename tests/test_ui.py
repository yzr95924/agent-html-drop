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
    ONLY for non-credential layout prefs (sidebar fold state, reading
    progress). All storage access must be funneled through the
    ls* helpers (lsBool / lsSetBool / lsStr / lsSetStr / lsNumber /
    lsSetNumber) — direct localStorage.* calls bypass the key allowlist."""
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    # sessionStorage is never used.
    assert "sessionStorage" not in text
    # All raw localStorage access lives inside the ls* helpers — anything
    # outside those would bypass the allowlist and could write the token.
    # Find every direct call and confirm each is inside an ls* function.
    direct_calls = re.findall(r"localStorage\.(?:getItem|setItem)", text)
    # Each helper has exactly one read + one write (getItem + setItem).
    # 3 helpers × 2 = 6 calls in the helper bodies is the expected total.
    assert len(direct_calls) == 6, (
        "expected 6 raw localStorage calls (3 helpers × get+set); "
        "found {}. Direct calls outside helpers are a security smell "
        "(could bypass key allowlist).".format(len(direct_calls))
    )
    # The only storage keys are non-credential prefs — never the token.
    allowed = {
        "agent-html-drop:annoCollapsed",
        "agent-html-drop:tocHidden",
        "agent-html-drop:lastFile",
        "agent-html-drop:lastScroll",
    }
    used = set(re.findall(r'"(agent-html-drop:[\w-]+)"', text))
    assert used <= allowed, "unexpected localStorage keys: %r" % (used - allowed)
    # Belt-and-suspenders: the auth token never reaches a storage write.
    assert "lsSetBool(token" not in text
    assert "lsSetStr(token" not in text
    assert "lsSetNumber(token" not in text


def test_app_js_handles_401_as_version_mismatch(ui_server):
    """If a 401 ever comes back, it's a version-mismatch (older daemon
    that still required Bearer) — surface a hint, not a token prompt."""
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    assert "r.status === 401" in text or "r.status == 401" in text
    assert "版本" in text or "version" in text.lower()


def test_url_column_uses_ui_font_not_monospace():
    """Regression (historical): the old "公开 URL" column must NOT set
    monospace on tdUrl — URLs are for copy-paste, not code reading.
    The column has since been removed (replaced by per-row 复制 URL
    button), so the absence of the tdUrl renderer is the *correct*
    current shape. We just guard that nothing reintroduces a URL column
    with monospace styling."""
    text = open(os.path.join(ui_mod._UI_DIR, "app.js"), encoding="utf-8").read()
    # The old variable name must not reappear (would mean a URL column
    # came back, which would crowd the table).
    assert "tdUrl" not in text, (
        "tdUrl 渲染逻辑回来了——表里已经不该再有公开 URL 列；"
        "如果是要还原，确认不要设 monospace 字体。"
    )
    # Belt-and-suspenders: no row should hardcode monospace either.
    # (Comments mention the word "monospace" as a guard, so check
    # actual .style.fontFamily assignments.)
    bad = [
        ln for ln in text.splitlines()
        if ".style.fontFamily" in ln and "monospace" in ln
    ]
    assert not bad, (
        "某行设了 monospace 字体：{}".format(bad)
    )


def test_app_js_uses_clipboard_for_copy(ui_server):
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    assert "clipboard" in text


# --- new affordances --------------------------------------------------------

def test_serves_anno_marks_css(ui_server):
    """anno-marks.css is the shared <mark> highlight style — both the
    management page's iframe injection and the public-page viewer load
    it via fetch / link, so they can't drift on color."""
    status, headers, body = _get(ui_server, "/anno-marks.css")
    assert status == 200
    assert "text/css" in headers.get("Content-Type", "")
    assert b"mark[data-anno-id]" in body


def test_index_has_relative_time_helper(ui_server):
    """fmtTimeRel must exist so the file table can show 3 分钟前 / 2 天前
    instead of bare timestamps. fmtTimeAbs is its tooltip source."""
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    assert "fmtTimeRel" in text
    assert "fmtTimeAbs" in text
    # And the absolute one must backfill when rel is too coarse (> 30 days).
    assert "fmtTimeAbs(unix)" in text or "fmtTimeAbs(f.mtime)" in text


def test_index_has_load_error_placeholder(ui_server):
    """When GET /api/files fails, the table area must show an inline
    error card — toasts are transient, but "list never loaded" is state."""
    _, _, body = _get(ui_server, "/")
    text = body.decode("utf-8")
    assert 'id="load-error"' in text


def test_table_rows_are_keyboard_activatable(ui_server):
    """Whole-row click preview is the primary action; it must work
    from keyboard (Enter/Space) too, not just mouse."""
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    assert 'tr[data-name]' in text
    assert 'tr.setAttribute("tabindex"' in text or "tr.setAttribute('tabindex'" in text
    assert '"Enter"' in text or "'Enter'" in text


def test_anno_count_renders_in_table(ui_server):
    """The new 批注 column must surface annotation_count from the API,
    not just sit empty. Wired as a clickable link so users can jump
    to the annotated file from the list."""
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    assert "annotation_count" in text
    assert "anno-count" in text


def test_anno_marks_css_color_is_canonical():
    """Both app.js and anno-viewer.js used to hardcode the same rgba —
    a "keep in sync" comment was the only thing keeping them aligned.
    Now anno-marks.css is the single source of truth; this test asserts
    the canonical color values stay in place (so reviewers notice if
    someone re-hardcodes elsewhere)."""
    text = open(os.path.join(ui_mod._UI_DIR, "anno-marks.css"), encoding="utf-8").read()
    assert "rgba(255, 196, 0, 0.32)" in text, (
        "anno-marks.css 的 mark 默认色变了——检查 app.js / anno-viewer.js "
        "是否还依赖旧值。"
    )


# --- reading comfort ------------------------------------------------------

def test_iframe_preview_container_has_dark_paper_lift(ui_server):
    """The preview iframe sits on the management page chrome (dark
    #0f1115). Without a contrast lift on the *container*, the iframe
    border disappears and the article feels disconnected — bad for
    long reading sessions. The container should be a few shades
    brighter than the chrome so the article reads as 'a sheet of
    paper on a dark desk', not 'another window'."""
    text = open(os.path.join(ui_mod._UI_DIR, "style.css"), encoding="utf-8").read()
    assert "#preview-frame" in text
    # Background must differ from the chrome background.
    chrome_bg = re.search(r"--bg:\s*([^;]+);", text).group(1).strip()
    assert f"background: {chrome_bg};" not in text, (
        f"preview-frame 用了和 chrome 一样的背景 {chrome_bg}——"
        "iframe 会跟页面糊在一起。"
    )
    # And must be applied to the *container*, not just left as the
    # browser default (white) — that's the failure mode this guard
    # is for (the old rule had `background: white` which clashed
    # with the dark chrome).
    bg = re.search(r"#preview-frame\s*\{[^}]*background:\s*([^;]+);", text)
    assert bg is not None, "#preview-frame 缺 background 声明"
    assert bg.group(1).strip().lower() not in {"white", "#fff", "#ffffff"}, (
        "preview-frame 还是白底——长时间阅读亮底会刺眼。"
    )


def test_preview_auto_scrolls_into_view(ui_server):
    """Clicking a filename reveals the iframe but, on a viewport
    where the file table fills the fold, the iframe is offscreen.
    preview() must scrollIntoView so the transition is meaningful."""
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    assert "scrollIntoView" in text


def test_keyboard_pgup_pgdn_forwards_to_iframe(ui_server):
    """Reading sessions on a long article need PgUp/PgDn to scroll
    the iframe content. The iframe is its own scroll context, so
    parent-doc keys can't reach it — we forward explicitly."""
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    assert '"PageDown"' in text or "'PageDown'" in text
    assert "scrollBy" in text


def test_annotation_nav_buttons_exist(ui_server):
    """Multiple annotations in one file → user needs prev/next to walk
    through them in document order without manually finding each <mark>."""
    _, _, body = _get(ui_server, "/")
    text = body.decode("utf-8")
    assert 'id="anno-popover-prev"' in text
    assert 'id="anno-popover-next"' in text
    assert 'id="anno-popover-counter"' in text


def test_reading_progress_persists_via_ls_str(ui_server):
    """The last-opened file is remembered so a reload puts the user
    back where they were. Persisted via the same ls* allowlist as
    other layout prefs (file name + scroll position are non-credential)."""
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    assert "agent-html-drop:lastFile" in text
    assert "agent-html-drop:lastScroll" in text
    # preview() must restore lastFile on loadFiles completion.
    assert "preview(last)" in text


# --- version chip --------------------------------------------------------

def test_index_has_version_chip_placeholder(ui_server):
    """The header shows a small version chip (e.g. "v0.2.3") populated
    at runtime from /api/health, so the user always sees the actual
    running daemon version — not whatever the static HTML was last
    served from. Placeholder text is set in markup; app.js fills it."""
    _, _, body = _get(ui_server, "/")
    text = body.decode("utf-8")
    assert 'id="version-tag"' in text
    # Must be inside the header so it's visible at the top of the page.
    assert text.find('id="version-tag"') < text.find("</header>"), (
        "version-tag 应该在 header 里,而不是散落在页面其他地方。"
    )


def test_app_js_populates_version_from_health(ui_server):
    """app.js must fetch /api/health on startup and put the version
    string into #version-tag. Silent on failure (the chip just stays
    as the placeholder)."""
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    assert "/api/health" in text
    assert 'getElementById("version-tag")' in text \
        or "getElementById('version-tag')" in text
    # Version format: "v" + the JSON's `version` field.
    assert 'j.version' in text