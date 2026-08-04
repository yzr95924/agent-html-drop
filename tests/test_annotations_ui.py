"""DOM shape assertions for the annotation UI. Pure string checks."""
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent / "src" / "agent_html_drop" / "ui"


def test_index_has_anno_toggle_button():
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="anno-toggle"' in html


def test_index_has_token_dialog():
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert '<dialog id="anno-token-dialog"' in html
    assert 'id="anno-token-input"' in html
    assert 'id="anno-token-submit"' in html


def test_index_has_anno_sidebar():
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="anno-sidebar"' in html
    assert 'id="anno-list"' in html


def test_css_has_anno_mode_styles():
    css = (UI_DIR / "style.css").read_text(encoding="utf-8")
    assert "#anno-toggle" in css
    assert "#anno-sidebar" in css
    assert "dialog" in css.lower() or "#anno-token-dialog" in css


def test_app_js_handles_iframe_text_walk():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    # Should walk text nodes and wrap matches.
    assert "createTreeWalker" in js or "TextNode" in js or "nodeType" in js
    assert "data-anno-id" in js


def test_app_js_handles_iframe_same_origin_sandbox():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    # iframe must be allow-same-origin (not full sandbox) so we can DOM-walk.
    assert "allow-same-origin" in js


def test_app_js_marks_invalid_quotes():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "invalid" in js  # .invalid class for missing quote


def test_app_js_does_not_allow_scripts_in_iframe():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    # Ensure we never set allow-scripts (would let Mermaid/MathJax run inside preview).
    assert "allow-scripts" not in js


def test_app_js_probes_session_before_prompting():
    """Refresh / clicking 批注 must GET /api/auth first and skip the token
    dialog when the HttpOnly session cookie is still valid — the cookie is
    JS-unreadable, so the server must be asked. The token dialog is only the
    fallback for when the probe returns non-204."""
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "probeSession" in js
    assert "/api/auth" in js
    # Dialog is the FALLBACK (second arg), not the default action.
    assert "probeSession(enterAnnoMode, openTokenDialog)" in js


# --- F22: iframe selection → POST annotation creation ---

def test_index_has_add_dialog():
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert '<dialog id="anno-add-dialog"' in html
    assert 'id="anno-add-quote"' in html
    assert 'id="anno-add-comment"' in html
    assert 'id="anno-add-submit"' in html


def test_index_has_add_fab():
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="anno-add-fab"' in html


def test_css_has_add_dialog_styles():
    css = (UI_DIR / "style.css").read_text(encoding="utf-8")
    assert "#anno-add-fab" in css
    assert "#anno-add-dialog" in css


def test_app_js_tracks_iframe_selection():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "selectionchange" in js
    assert "getSelection" in js


def test_app_js_posts_new_annotation():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert 'method: "POST"' in js
    assert "quote" in js and "comment" in js
    # CSRF header must ride along on the write call.
    assert "csrfHeaders()" in js


def test_app_js_caps_quote_at_server_limit():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    # storage/annotations.py _MAX_QUOTE_LEN = 200; client mirrors it.
    assert "MAX_QUOTE_LEN = 200" in js


# --- cross-node highlight (document-level text map) ---

def test_app_js_wraps_across_text_nodes():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    # splitText-based range wrap (not the old single-node substring swap).
    assert "splitText" in js
    assert "buildTextMap" in js


def test_app_js_inserts_block_boundary_separator():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    # Synthetic space between text nodes of different block ancestors,
    # mirroring getSelection().toString() at block boundaries.
    assert "BLOCK_RE" in js
    assert "nearestBlock" in js


def test_app_js_unwraps_before_rehighlight():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    # Idempotency: stale marks are unwrapped (and text re-merged) first.
    assert "unwrapMarks" in js
    assert ".normalize()" in js


# --- public-page viewer (anno-viewer.js): read-only mirror of the highlight ---

def test_anno_viewer_is_read_only():
    """The public-page viewer only READS annotations (public GET) — it must
    never call a write route. Writes need the anno session cookie, which only
    the management page's token flow can mint; a public visitor has none."""
    js = (UI_DIR / "anno-viewer.js").read_text(encoding="utf-8")
    assert "/annotations" in js
    assert "buildTextMap" in js  # shares the highlight algorithm
    assert 'method: "POST"' not in js
    assert '"DELETE"' not in js
    assert "PATCH" not in js
    # Never sends a credential — public read only.
    assert "credentials" in js and '"omit"' in js


def test_anno_viewer_derives_filename_from_pathname():
    """The viewer runs on /files/<name>.html and must derive <name> from its
    own URL (location.pathname) — the daemon injects just a bare <script>,
    no per-file data, so there's nothing to leak or mis-sync."""
    js = (UI_DIR / "anno-viewer.js").read_text(encoding="utf-8")
    assert "location.pathname" in js
    assert "/files/" in js
    assert "decodeURIComponent" in js


def test_mark_color_matches_between_preview_and_public_viewer():
    """The preview iframe (app.js) and the public page (anno-viewer.js) must
    highlight annotation <mark>s the SAME color — otherwise the two views of
    the same annotation look inconsistent.

    The shared style lives in /anno-marks.css as the single source of
    truth. The parent (app.js) fetches it and injects the text into the
    iframe <style>; the public viewer (anno-viewer.js) loads it as a
    stylesheet. Either way, both surfaces must end up with the canonical
    ``mark[data-anno-id]`` selector — drift here means the color can
    desync silently.
    """
    marks = (UI_DIR / "anno-marks.css").read_text(encoding="utf-8")
    app = (UI_DIR / "app.js").read_text(encoding="utf-8")
    viewer = (UI_DIR / "anno-viewer.js").read_text(encoding="utf-8")
    # Canonical selector lives in anno-marks.css.
    assert "mark[data-anno-id]" in marks, (
        "anno-marks.css 缺 mark[data-anno-id] 规则——这是 viewer 和管理页 "
        "iframe 共享的高亮样式源头。"
    )
    # Both surfaces must reference it (not hardcode their own copies).
    assert "/anno-marks.css" in app, (
        "app.js 不再加载 anno-marks.css——iframe 高亮会回退到 fetch 失败 "
        "fallback，跟 public 页脱钩。"
    )
    assert "/anno-marks.css" in viewer, (
        "anno-viewer.js 不再加载 anno-marks.css——public 页高亮会丢失。"
    )


# --- popover-first: panel folded by default, click a highlight to read -----


def test_index_has_anno_popover():
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="anno-popover"' in html
    assert 'id="anno-popover-close"' in html


def test_views_default_panel_collapsed_so_it_does_not_cover_text():
    """Both the preview (app.js) and the public page (anno-viewer.js) must
    default their annotation panel to FOLDED, so a reader isn't covered on
    load. Comments are read via the click popover instead. (A returning
    visitor who explicitly opened it still gets their persisted choice.)"""
    app = (UI_DIR / "app.js").read_text(encoding="utf-8")
    viewer = (UI_DIR / "anno-viewer.js").read_text(encoding="utf-8")
    assert "lsBool(LS_ANNO_COLLAPSED, true)" in app, "preview sidebar must default folded"
    assert "lsBool(LS_COLLAPSED, true)" in viewer, "public panel must default folded"


def test_views_show_popover_on_mark_click():
    """Clicking a highlight pops a small comment bubble next to it — the
    primary read UI now that the side panel is folded by default."""
    app = (UI_DIR / "app.js").read_text(encoding="utf-8")
    viewer = (UI_DIR / "anno-viewer.js").read_text(encoding="utf-8")
    # preview: parent wires iframe marks → parent-page popover
    assert "wireIframeMarks" in app and "showPreviewPopover" in app
    # public page: marks → popover in the same document
    assert "showPopover" in viewer and "wireMarks" in viewer


def test_popover_renders_annotation_via_textcontent():
    """Popover content is set with textContent (never innerHTML + annotation
    data) — stored-XSS defense, same rule as the side panels."""
    app = (UI_DIR / "app.js").read_text(encoding="utf-8")
    viewer = (UI_DIR / "anno-viewer.js").read_text(encoding="utf-8")
    assert "$popQuote.textContent" in app and "$popComment.textContent" in app
    assert "$popQuote.textContent" in viewer and "$popComment.textContent" in viewer