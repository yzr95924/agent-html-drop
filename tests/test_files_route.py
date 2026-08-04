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


def _put(srv_, path, body, *, auth=TOKEN, content_length=None,
         content_sha256=None, content_type="text/html"):
    host, port = srv_.server_address
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        if content_length is None:
            content_length = len(body)
        hdrs = {"Content-Length": str(content_length)}
        if content_type is not None:
            hdrs["Content-Type"] = content_type
        if auth is not None:
            hdrs["Authorization"] = "Bearer " + auth
        if content_sha256 is not None:
            hdrs["Content-SHA256"] = content_sha256
        conn.request("PUT", path, body=body, headers=hdrs)
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


# --- PUT /files/<name> — streaming upload side-channel ---------------------
#
# Lets the agent push HTML bytes via raw HTTP without stuffing the content
# into the MCP tool call (which would burn LLM context). Symmetric to
# GET /files/<name>. Same Bearer as MCP. Streams request body straight to
# tmpfile, atomic-replaces on success, hashes per chunk for sha256.
# See design §7.3 (write path is Bearer-protected) + optimization for
# large-HTML agent uploads.

import hashlib
import json


def test_put_writes_file_and_returns_metadata(http_with_files):
    http, _, docroot = http_with_files
    body = b"<html><body>hello</body></html>"
    status, headers, data = _put(http, "/files/design.html", body)
    assert status == 201
    payload = json.loads(data)
    assert payload["name"] == "design.html"
    assert payload["url"] == "https://notes.example.com/files/design.html"
    assert payload["size"] == len(body)
    assert payload["sha256"] == hashlib.sha256(body).hexdigest()
    assert (docroot / "design.html").read_bytes() == body


def test_put_then_get_round_trips(http_with_files):
    """A file just PUT must be readable by GET /files/<name>."""
    http, _, _ = http_with_files
    body = b"<html><body>round-trip</body></html>"
    status, _, _ = _put(http, "/files/x.html", body)
    assert status == 201
    g_status, _, g_data = _get(http, "/files/x.html")
    assert g_status == 200
    assert g_data == body


def test_put_missing_bearer_returns_401(http_with_files):
    http, _, _ = http_with_files
    status, _, _ = _put(http, "/files/a.html", b"<html>x</html>", auth=None)
    assert status == 401


def test_put_wrong_bearer_returns_401(http_with_files):
    http, _, _ = http_with_files
    status, _, _ = _put(http, "/files/a.html", b"<html>x</html>", auth="wrong")
    assert status == 401


def test_put_invalid_name_returns_400(http_with_files):
    http, _, _ = http_with_files
    status, _, data = _put(http, "/files/bad%20name.html", b"x")
    assert status == 400
    assert b"invalid_name" in data


def test_put_traversal_returns_400(http_with_files):
    http, _, docroot = http_with_files
    status, _, data = _put(http, "/files/..%2Fetc%2Fpasswd.html", b"x")
    assert status == 400


def test_put_missing_content_length_returns_411(http_with_files):
    srv_, _, _ = http_with_files
    host, port = srv_.server_address
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.putrequest("PUT", "/files/x.html", skip_host=False)
        conn.putheader("Authorization", "Bearer " + TOKEN)
        conn.putheader("Content-Type", "text/html")
        # Deliberately omit Content-Length.
        conn.endheaders()
        conn.send(b"<html>x</html>")
        r = conn.getresponse()
        data = r.read()
        assert r.status == 411
    finally:
        conn.close()


def test_put_content_length_exceeds_max_body_returns_413(http_with_files):
    """Content-Length > server.max_body_size is rejected BEFORE reading body."""
    http, _, _ = http_with_files
    # server.max_body_size defaults to 50 MiB; fake a 60 MiB claim with a
    # tiny body — the server should still 413 on the header.
    fake_len = 60 * 1024 * 1024
    status, _, _ = _put(http, "/files/x.html", b"x", content_length=fake_len)
    assert status == 413


def test_put_body_actually_exceeds_max_file_size_returns_413(http_with_files):
    """Body really larger than cfg.max_file_size (1 MiB in fixture) → 413.

    The header lies or the size cap kicks in mid-stream. Either way, the
    file must NOT be written and any tmp must be cleaned up.
    """
    http, _, docroot = http_with_files
    body = b"x" * (2 * 1024 * 1024)  # 2 MiB > 1 MiB cap
    status, _, _ = _put(http, "/files/big.html", body)
    assert status == 413
    assert not (docroot / "big.html").exists()
    # No orphan .tmp left behind.
    leftovers = [p for p in docroot.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_put_conflict_without_force_returns_409(http_with_files):
    http, _, docroot = http_with_files
    (docroot / "design.html").write_bytes(b"first")
    status, _, data = _put(http, "/files/design.html", b"second")
    assert status == 409
    assert b"conflict" in data
    assert (docroot / "design.html").read_bytes() == b"first"


def test_put_force_query_overwrites(http_with_files):
    http, _, docroot = http_with_files
    (docroot / "design.html").write_bytes(b"first")
    status, _, _ = _put(
        http, "/files/design.html?force=true", b"second"
    )
    assert status == 201
    assert (docroot / "design.html").read_bytes() == b"second"


def test_put_sha256_mismatch_returns_400(http_with_files):
    """Content-SHA256 header that doesn't match the body → 400, no file written."""
    http, _, docroot = http_with_files
    body = b"<html>actual</html>"
    wrong = "0" * 64
    status, _, data = _put(
        http, "/files/x.html", body, content_sha256=wrong
    )
    assert status == 400
    assert b"sha256" in data
    assert not (docroot / "x.html").exists()
    leftovers = [p for p in docroot.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_put_sha256_match_succeeds(http_with_files):
    http, _, docroot = http_with_files
    body = b"<html>ok</html>"
    good = hashlib.sha256(body).hexdigest()
    status, _, payload_bytes = _put(
        http, "/files/x.html", body, content_sha256=good
    )
    assert status == 201
    payload = json.loads(payload_bytes)
    assert payload["sha256"] == good
    assert (docroot / "x.html").read_bytes() == body


def test_put_large_file_round_trips(http_with_files):
    """700 KiB body — exercises the streaming path (multi-chunk) without
    tripping the fixture's 1 MiB max_file_size cap."""
    http, _, docroot = http_with_files
    body = b"<html>" + b"y" * (700 * 1024) + b"</html>"
    status, _, _ = _put(http, "/files/big.html", body)
    assert status == 201
    assert (docroot / "big.html").stat().st_size == len(body)
    # Read back via GET to confirm content matches exactly.
    g_status, _, g_data = _get(http, "/files/big.html")
    assert g_status == 200
    assert g_data == body


def test_put_uses_case_insensitive_existing_target(http_with_files):
    """DESIGN.HTML on disk + design.html in PUT URL → overwrite existing."""
    http, _, docroot = http_with_files
    (docroot / "Design.HTML").write_bytes(b"old")
    status, _, _ = _put(
        http, "/files/design.html", b"new", content_length=len(b"new")
    )
    assert status == 409  # existing case-variant detected, no force
    # With force, the existing one is overwritten (no duplicate created).
    status, _, _ = _put(
        http, "/files/design.html?force=true", b"new",
        content_length=len(b"new"),
    )
    assert status == 201
    # DESIGN.HTML is gone (case-preserving overwrite), no design.html added.
    assert not (docroot / "Design.HTML").exists()
    assert (docroot / "design.html").read_bytes() == b"new"
