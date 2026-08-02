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
