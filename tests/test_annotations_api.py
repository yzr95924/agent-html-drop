"""Tests for annotation auth + list_files annotation_count extension."""
import http.client
import json
import threading
from http.cookies import SimpleCookie
from pathlib import Path

import pytest

from agent_html_drop.api import register_routes
from agent_html_drop.config import Config
from agent_html_drop.server import make_server, routes
from agent_html_drop.storage import annotations as anno_store


@pytest.fixture
def cfg_factory(tmp_path, monkeypatch):
    """Factory that builds a Config with tmp paths; monkeypatches config.load_config."""
    from agent_html_drop import config as cfg_mod
    from agent_html_drop import _legacy_storage as storage

    def _make(docroot_files=None, token="test-token-abc"):
        docroot = tmp_path / "docroot"
        docroot.mkdir(exist_ok=True)
        if docroot_files:
            for name, content in docroot_files:
                if isinstance(content, str):
                    storage.upload(
                        docroot, name, content, max_size=10_000_000, force=True
                    )
                else:
                    (docroot / name).write_bytes(content)
        cfg = Config(
            host="127.0.0.1",
            port=0,
            docroot=str(docroot),
            public_base_url="https://notes.example.com",
            max_file_size=50 * 1024 * 1024,
            token=token,
            extra_top={},
            extra_auth={},
        )
        monkeypatch.setattr(cfg_mod, "load_config", lambda *args: cfg)
        return cfg

    return _make


@pytest.fixture
def http_server(cfg_factory):
    routes.clear()
    cfg = cfg_factory(docroot_files=[("design.html", "<h1>Design</h1>")])
    srv = make_server("127.0.0.1", 0, quiet=True)
    register_routes(cfg)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, cfg
    finally:
        srv.shutdown()
        srv.server_close()
        routes.clear()


@pytest.fixture
def http_server_insecure(cfg_factory):
    """Like http_server but with allow_insecure_annotations=True (plain-HTTP mode)."""
    routes.clear()
    cfg = cfg_factory(docroot_files=[("design.html", "<h1>Design</h1>")])
    cfg.allow_insecure_annotations = True
    srv = make_server("127.0.0.1", 0, quiet=True)
    register_routes(cfg)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, cfg
    finally:
        srv.shutdown()
        srv.server_close()
        routes.clear()


def test_insecure_mode_auth_sets_cookie_without_secure(http_server_insecure):
    srv, cfg = http_server_insecure
    host, port = srv.server_address
    conn, response = _post(
        host, port, "/api/auth",
        headers={"Authorization": "Bearer " + cfg.token},
    )
    try:
        assert response.status == 204
        sc = response.getheader("Set-Cookie")
        assert "anno_session=" in sc
        assert "Secure" not in sc
        assert "HttpOnly" in sc
    finally:
        response.read()
        conn.close()


def test_insecure_mode_post_annotation_with_http_origin_succeeds(http_server_insecure):
    """Insecure mode: http Origin + matching Host:port → annotation created."""
    from agent_html_drop.auth_anno import ANNO_COOKIE_NAME
    srv, cfg = http_server_insecure
    host, port = srv.server_address
    conn, response = _post(
        host, port, "/api/auth",
        headers={"Authorization": "Bearer " + cfg.token},
    )
    try:
        sc = response.getheader("Set-Cookie")
        cookie = SimpleCookie()
        cookie.load(sc)
        cookie_value = cookie[ANNO_COOKIE_NAME].value
    finally:
        response.read()
        conn.close()
    conn, response = _post(
        host, port, "/api/files/design.html/annotations",
        body=b'{"quote":"q","comment":"c"}',
        headers={
            "Cookie": ANNO_COOKIE_NAME + "=" + cookie_value,
            "Content-Type": "application/json",
            "Origin": "http://{}:{}".format(host, port),
            "Host": "{}:{}".format(host, port),
        },
    )
    try:
        assert response.status == 201
        data = json.loads(response.read())
        assert data["quote"] == "q"
    finally:
        response.read()
        conn.close()


def _post(host, port, path, body=b"", headers=None):
    hdrs = {"Content-Length": str(len(body))}
    if headers:
        hdrs.update(headers)
    conn = http.client.HTTPConnection(host, port, timeout=2)
    conn.request("POST", path, body=body, headers=hdrs)
    return conn, conn.getresponse()


def _get(host, port, path, headers=None):
    conn = http.client.HTTPConnection(host, port, timeout=2)
    conn.request("GET", path, headers=headers or {})
    return conn, conn.getresponse()


def test_auth_correct_token_sets_cookie(http_server):
    srv, cfg = http_server
    host, port = srv.server_address
    conn, response = _post(
        host,
        port,
        "/api/auth",
        headers={"Authorization": "Bearer " + cfg.token},
    )
    try:
        assert response.status == 204
        set_cookie = response.getheader("Set-Cookie")
        assert set_cookie is not None
        assert "anno_session=" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "Secure" in set_cookie
        assert "SameSite=Lax" in set_cookie
        assert "Max-Age=1800" in set_cookie
    finally:
        response.read()
        conn.close()


def test_auth_wrong_token_returns_401(http_server):
    srv, _ = http_server
    host, port = srv.server_address
    conn, response = _post(
        host, port, "/api/auth", headers={"Authorization": "Bearer WRONG"}
    )
    try:
        assert response.status == 401
    finally:
        response.read()
        conn.close()


def test_auth_missing_header_returns_401(http_server):
    srv, _ = http_server
    host, port = srv.server_address
    conn, response = _post(host, port, "/api/auth")
    try:
        assert response.status == 401
    finally:
        response.read()
        conn.close()


def test_get_api_auth_reports_session_status(http_server):
    """GET /api/auth: 204 with a valid cookie, 401 without — lets the UI
    skip the token dialog after a refresh (the HttpOnly cookie is
    JS-unreadable, so it must ask the server)."""
    from agent_html_drop.auth_anno import ANNO_COOKIE_NAME

    srv, cfg = http_server
    host, port = srv.server_address

    # No cookie → 401.
    conn, response = _get(host, port, "/api/auth")
    try:
        assert response.status == 401
    finally:
        response.read()
        conn.close()

    # Obtain a cookie via POST /api/auth.
    conn, response = _post(
        host, port, "/api/auth", headers={"Authorization": "Bearer " + cfg.token}
    )
    try:
        cookie = SimpleCookie()
        cookie.load(response.getheader("Set-Cookie"))
        cookie_value = cookie[ANNO_COOKIE_NAME].value
    finally:
        response.read()
        conn.close()

    # Same cookie on GET → 204 (status read does NOT reissue the cookie).
    conn, response = _get(
        host,
        port,
        "/api/auth",
        headers={"Cookie": ANNO_COOKIE_NAME + "=" + cookie_value},
    )
    try:
        assert response.status == 204
        assert response.getheader("Set-Cookie") is None
    finally:
        response.read()
        conn.close()


def test_list_files_includes_annotation_count_zero(http_server):
    srv, _ = http_server
    host, port = srv.server_address
    conn, response = _get(host, port, "/api/files")
    try:
        assert response.status == 200
        data = json.loads(response.read())
        assert data["files"][0]["annotation_count"] == 0
    finally:
        conn.close()


def test_list_files_includes_annotation_count_nonzero(http_server):
    """Mutate docroot after server start, then re-fetch /api/files."""
    from agent_html_drop.storage import annotations as anno_store

    srv, cfg = http_server
    anno_store.add(
        Path(cfg.docroot), "design.html", "quote", "comment", "any-token"
    )
    host, port = srv.server_address
    conn, response = _get(host, port, "/api/files")
    try:
        data = json.loads(response.read())
        assert data["files"][0]["annotation_count"] == 1
    finally:
        conn.close()


def _cookie_header(cookie_value):
    return {"Cookie": "anno_session=" + cookie_value}


def _patch(host, port, path, body=b"", headers=None):
    hdrs = {"Content-Length": str(len(body))}
    if headers:
        hdrs.update(headers)
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("PATCH", path, body=body, headers=hdrs)
        return conn.getresponse()
    finally:
        conn.close()


def test_get_annotations_public_returns_list(http_server):
    srv, cfg = http_server
    docroot = Path(cfg.docroot)
    anno_store.add(docroot, "design.html", "q1", "c1", "tok-x")
    anno_store.add(docroot, "design.html", "q2", "c2", "tok-y")
    host, port = srv.server_address
    conn, response = _get(host, port, "/api/files/design.html/annotations")
    try:
        assert response.status == 200
        data = json.loads(response.read())
        assert data["name"] == "design.html"
        assert len(data["annotations"]) == 2
    finally:
        conn.close()


def test_post_annotation_without_cookie_returns_401(http_server):
    srv, _ = http_server
    host, port = srv.server_address
    conn, response = _post(
        host,
        port,
        "/api/files/design.html/annotations",
        body=b'{"quote":"q","comment":"c"}',
        headers={"Content-Type": "application/json"},
    )
    try:
        assert response.status == 401
    finally:
        response.read()
        conn.close()


def test_post_annotation_with_cookie_and_origin_creates(http_server):
    """End-to-end: get a cookie via /api/auth, then POST annotation."""
    from agent_html_drop.auth_anno import ANNO_COOKIE_NAME, sign_cookie
    srv, cfg = http_server
    host, port = srv.server_address
    # Step 1: get cookie.
    conn, response = _post(
        host,
        port,
        "/api/auth",
        headers={"Authorization": "Bearer " + cfg.token},
    )
    try:
        assert response.status == 204
        sc = response.getheader("Set-Cookie")
        cookie = SimpleCookie()
        cookie.load(sc)
        cookie_value = cookie[ANNO_COOKIE_NAME].value
    finally:
        response.read()
        conn.close()

    # Step 2: POST annotation with cookie + matching Origin.
    conn, response = _post(
        host,
        port,
        "/api/files/design.html/annotations",
        body=b'{"quote":"sudo mkdir","comment":"change"}',
        headers={
            "Cookie": ANNO_COOKIE_NAME + "=" + cookie_value,
            "Content-Type": "application/json",
            "Origin": "https://notes.example.com",
            "Host": "notes.example.com",
        },
    )
    try:
        assert response.status == 201
        data = json.loads(response.read())
        assert data["quote"] == "sudo mkdir"
        assert data["comment"] == "change"
        assert data["author"].startswith("tk_")
    finally:
        conn.close()


def test_post_annotation_with_wrong_origin_returns_403(http_server):
    from agent_html_drop.auth_anno import ANNO_COOKIE_NAME, sign_cookie
    srv, cfg = http_server
    host, port = srv.server_address
    conn, response = _post(
        host,
        port,
        "/api/auth",
        headers={"Authorization": "Bearer " + cfg.token},
    )
    try:
        sc = response.getheader("Set-Cookie")
        cookie = SimpleCookie()
        cookie.load(sc)
        cookie_value = cookie[ANNO_COOKIE_NAME].value
    finally:
        response.read()
        conn.close()

    conn, response = _post(
        host,
        port,
        "/api/files/design.html/annotations",
        body=b'{"quote":"q","comment":"c"}',
        headers={
            "Cookie": ANNO_COOKIE_NAME + "=" + cookie_value,
            "Content-Type": "application/json",
            "Origin": "https://evil.com",
            "Host": "notes.example.com",
        },
    )
    try:
        assert response.status == 403
    finally:
        response.read()
        conn.close()


def test_patch_annotation_by_author_updates_comment(http_server):
    srv, cfg = http_server
    docroot = Path(cfg.docroot)
    entry = anno_store.add(docroot, "design.html", "q", "old", cfg.token)

    from agent_html_drop.auth_anno import ANNO_COOKIE_NAME, sign_cookie
    cookie_value = sign_cookie(cfg.token)

    host, port = srv.server_address
    response = _patch(
        host,
        port,
        "/api/files/design.html/annotations/" + entry["id"],
        body=b'{"comment":"new"}',
        headers={
            "Cookie": ANNO_COOKIE_NAME + "=" + cookie_value,
            "Content-Type": "application/json",
            "Origin": "https://notes.example.com",
            "Host": "notes.example.com",
        },
    )
    try:
        assert response.status == 200
        data = json.loads(response.read())
        assert data["comment"] == "new"
    finally:
        response.read()


def test_patch_by_other_token_returns_403(http_server):
    srv, cfg = http_server
    docroot = Path(cfg.docroot)
    entry = anno_store.add(docroot, "design.html", "q", "old", "other-token")

    from agent_html_drop.auth_anno import ANNO_COOKIE_NAME, sign_cookie
    cookie_value = sign_cookie(cfg.token)

    host, port = srv.server_address
    response = _patch(
        host,
        port,
        "/api/files/design.html/annotations/" + entry["id"],
        body=b'{"comment":"hijacked"}',
        headers={
            "Cookie": ANNO_COOKIE_NAME + "=" + cookie_value,
            "Content-Type": "application/json",
            "Origin": "https://notes.example.com",
            "Host": "notes.example.com",
        },
    )
    try:
        assert response.status == 403
    finally:
        response.read()


def test_delete_annotation_by_author_succeeds(http_server):
    srv, cfg = http_server
    docroot = Path(cfg.docroot)
    entry = anno_store.add(docroot, "design.html", "q", "c", cfg.token)

    from agent_html_drop.auth_anno import ANNO_COOKIE_NAME, sign_cookie
    cookie_value = sign_cookie(cfg.token)

    host, port = srv.server_address
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request(
            "DELETE",
            "/api/files/design.html/annotations/" + entry["id"],
            headers={
                "Cookie": ANNO_COOKIE_NAME + "=" + cookie_value,
                "Origin": "https://notes.example.com",
                "Host": "notes.example.com",
            },
        )
        response = conn.getresponse()
        try:
            assert response.status == 200
            assert json.loads(response.read()) == {"deleted": True}
            assert anno_store.count(docroot, "design.html") == 0
        finally:
            response.read()
    finally:
        conn.close()


def test_post_annotation_with_json_null_returns_400(http_server):
    """POST with body `null` → 400 invalid_args (must be JSON object)."""
    from agent_html_drop.auth_anno import ANNO_COOKIE_NAME
    srv, cfg = http_server
    host, port = srv.server_address
    # Step 1: get cookie.
    conn, response = _post(
        host,
        port,
        "/api/auth",
        headers={"Authorization": "Bearer " + cfg.token},
    )
    try:
        assert response.status == 204
        sc = response.getheader("Set-Cookie")
        cookie = SimpleCookie()
        cookie.load(sc)
        cookie_value = cookie[ANNO_COOKIE_NAME].value
    finally:
        response.read()
        conn.close()

    # Step 2: POST null.
    conn, response = _post(
        host,
        port,
        "/api/files/design.html/annotations",
        body=b'null',
        headers={
            "Cookie": ANNO_COOKIE_NAME + "=" + cookie_value,
            "Content-Type": "application/json",
            "Origin": "https://notes.example.com",
            "Host": "notes.example.com",
        },
    )
    try:
        assert response.status == 400
        data = json.loads(response.read())
        assert data["error"] == "invalid_args"
    finally:
        conn.close()


def test_post_annotation_with_json_array_returns_400(http_server):
    """POST with body `[1,2,3]` → 400 invalid_args (must be JSON object)."""
    from agent_html_drop.auth_anno import ANNO_COOKIE_NAME
    srv, cfg = http_server
    host, port = srv.server_address
    # Step 1: get cookie.
    conn, response = _post(
        host,
        port,
        "/api/auth",
        headers={"Authorization": "Bearer " + cfg.token},
    )
    try:
        assert response.status == 204
        sc = response.getheader("Set-Cookie")
        cookie = SimpleCookie()
        cookie.load(sc)
        cookie_value = cookie[ANNO_COOKIE_NAME].value
    finally:
        response.read()
        conn.close()

    # Step 2: POST array.
    conn, response = _post(
        host,
        port,
        "/api/files/design.html/annotations",
        body=b'[1,2,3]',
        headers={
            "Cookie": ANNO_COOKIE_NAME + "=" + cookie_value,
            "Content-Type": "application/json",
            "Origin": "https://notes.example.com",
            "Host": "notes.example.com",
        },
    )
    try:
        assert response.status == 400
        data = json.loads(response.read())
        assert data["error"] == "invalid_args"
    finally:
        conn.close()


def test_patch_annotation_with_json_string_returns_400(http_server):
    """PATCH with body `"a string"` → 400 invalid_args (must be JSON object)."""
    from agent_html_drop.auth_anno import ANNO_COOKIE_NAME, sign_cookie
    srv, cfg = http_server
    docroot = Path(cfg.docroot)
    entry = anno_store.add(docroot, "design.html", "q", "old", cfg.token)
    cookie_value = sign_cookie(cfg.token)

    host, port = srv.server_address
    response = _patch(
        host,
        port,
        "/api/files/design.html/annotations/" + entry["id"],
        body=b'"a string"',
        headers={
            "Cookie": ANNO_COOKIE_NAME + "=" + cookie_value,
            "Content-Type": "application/json",
            "Origin": "https://notes.example.com",
            "Host": "notes.example.com",
        },
    )
    try:
        assert response.status == 400
        data = json.loads(response.read())
        assert data["error"] == "invalid_args"
    finally:
        response.read()
