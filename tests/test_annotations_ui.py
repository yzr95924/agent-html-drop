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