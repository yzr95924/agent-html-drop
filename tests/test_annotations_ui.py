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