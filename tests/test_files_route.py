"""Tests for GET /files/<name> — daemon-served public HTML (container mode).

Design §15.3.1: the daemon serves /files/<name> itself (streaming, path-
traversal-safe) so the container is self-contained behind a pure reverse
proxy. Classic mode keeps nginx direct-read; this route lets the daemon
serve /files/ too. Public, no auth — same "push = public" trust model as
nginx direct-read (§9.3).
"""
import http.client
import threading

import pytest

from agent_html_drop import api as api_mod
from agent_html_drop import server as srv
from agent_html_drop.config import Config


TOKEN = "x" * 64


@pytest.fixture
def http_with_files(tmp_path):
    """Server with /api/* + /files/ routes against a tmp docroot."""
    docroot = tmp_path / "notes"
    docroot.mkdir()
    cfg = Config(
        docroot=str(docroot),
        public_base_url="https://notes.example.com",
        port=8765,
        max_file_size=1024 * 1024,
        token=TOKEN,
    )
    srv.routes.clear()
    api_mod.register_routes(cfg)
    http = srv.make_server("127.0.0.1", 0, quiet=True)
    t = threading.Thread(target=http.serve_forever, daemon=True)
    t.start()
    try:
        yield http, cfg, docroot
    finally:
        http.shutdown()
        http.server_close()
        srv.routes.clear()


def _get(srv_, path):
    host, port = srv_.server_address
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("GET", path)
        r = conn.getresponse()
        data = r.read()
        return r.status, dict(r.getheaders()), data
    finally:
        conn.close()


# --- serving existing files ------------------------------------------------

def test_files_serves_existing_html(http_with_files):
    http, _, docroot = http_with_files
    body = b"<html><body>hello</body></html>"
    (docroot / "design.html").write_bytes(body)
    status, headers, data = _get(http, "/files/design.html")
    assert status == 200
    assert "text/html" in headers.get("Content-Type", "")
    assert data == body


def test_files_content_type_is_text_html(http_with_files):
    http, _, docroot = http_with_files
    (docroot / "a.html").write_bytes(b"<html></html>")
    _, headers, _ = _get(http, "/files/a.html")
    ct = headers.get("Content-Type", "")
    assert ct.startswith("text/html")


def test_files_serves_html_suffix_case_insensitive(http_with_files):
    """validate_name is case-insensitive on .html (design §4)."""
    http, _, docroot = http_with_files
    body = b"<html></html>"
    (docroot / "Design.HTML").write_bytes(body)
    status, _, data = _get(http, "/files/Design.HTML")
    assert status == 200
    assert data == body


# --- missing / invalid / traversal → uniform 404 (no info leak) ------------

def test_files_missing_returns_404(http_with_files):
    http, _, _ = http_with_files
    status, _, _ = _get(http, "/files/missing.html")
    assert status == 404


def test_files_invalid_name_returns_404(http_with_files):
    """Non-.html names 404 on this public route (no validation leak)."""
    http, _, docroot = http_with_files
    (docroot / "readme.txt").write_text("hi")
    status, _, _ = _get(http, "/files/readme.txt")
    assert status == 404


def test_files_rejects_traversal(http_with_files):
    """Path traversal must not escape docroot — 404, never 200."""
    http, _, _ = http_with_files
    status, _, _ = _get(http, "/files/../../etc/passwd")
    assert status == 404


def test_files_rejects_slash_in_name(http_with_files):
    """A name containing '/' can't reach a subpath — 404."""
    http, _, docroot = http_with_files
    (docroot / "real.html").write_bytes(b"x")
    status, _, _ = _get(http, "/files/sub/real.html")
    assert status == 404


# --- streaming (large file round-trips intact) -----------------------------

def test_files_streams_large_file(http_with_files):
    """A file larger than the read buffer round-trips intact — exercises
    the chunked streaming path rather than a whole-file load."""
    http, _, docroot = http_with_files
    body = b"<html>" + b"x" * (2 * 1024 * 1024) + b"</html>"
    (docroot / "big.html").write_bytes(body)
    status, headers, data = _get(http, "/files/big.html")
    assert status == 200
    assert int(headers.get("Content-Length", 0)) == len(body)
    assert data == body


# --- annotation viewer injection --------------------------------------------
# A public URL with annotations gets a read-only viewer <script>; a clean
# file streams unchanged. See api._inject_viewer + ui/anno-viewer.js.

def test_files_injects_viewer_when_annotated(http_with_files):
    """A file WITH annotations has the viewer <script> injected before
    </body> so the public URL renders highlights + comments."""
    from agent_html_drop.storage import annotations as anno_store
    http, _, docroot = http_with_files
    (docroot / "design.html").write_text(
        "<html><body><p>hello world</p></body></html>", encoding="utf-8"
    )
    anno_store.add(docroot, "design.html", "hello world", "a note", "tok")
    status, headers, data = _get(http, "/files/design.html")
    assert status == 200
    text = data.decode("utf-8")
    assert '<script src="/anno-viewer.js"' in text
    # Original content preserved, and the tag lands before </body>.
    assert "hello world" in text
    assert text.index('<script src="/anno-viewer.js"') < text.lower().index("</body>")
    # Content-Length matches the (now larger) body exactly — no off-by-one.
    assert int(headers.get("Content-Length", 0)) == len(data)


def test_files_no_viewer_when_unannotated(http_with_files):
    """A file WITHOUT annotations streams unchanged — zero viewer overhead."""
    http, _, docroot = http_with_files
    body = b"<html><body>hello</body></html>"
    (docroot / "plain.html").write_bytes(body)
    status, _, data = _get(http, "/files/plain.html")
    assert status == 200
    assert data == body
    assert b"anno-viewer.js" not in data


def test_files_inject_viewer_idempotent(http_with_files):
    """A file that already references the viewer is not double-injected."""
    from agent_html_drop.storage import annotations as anno_store
    http, _, docroot = http_with_files
    raw = (
        '<html><body><p>x</p>'
        '<script src="/anno-viewer.js" defer></script>'
        "</body></html>"
    )
    (docroot / "a.html").write_text(raw, encoding="utf-8")
    anno_store.add(docroot, "a.html", "x", "n", "tok")
    _, _, data = _get(http, "/files/a.html")
    assert data.decode("utf-8").count("anno-viewer.js") == 1


def test_files_viewer_injected_without_body_tag(http_with_files):
    """No </body> → tag goes before </html>; neither → appended."""
    from agent_html_drop.storage import annotations as anno_store
    http, _, docroot = http_with_files
    (docroot / "b.html").write_text("<html><p>hi</p></html>", encoding="utf-8")
    anno_store.add(docroot, "b.html", "hi", "n", "tok")
    _, _, data = _get(http, "/files/b.html")
    text = data.decode("utf-8")
    assert '<script src="/anno-viewer.js"' in text
    assert text.count('<script src="/anno-viewer.js"') == 1
