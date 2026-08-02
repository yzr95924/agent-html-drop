"""Tests for agent_html_drop.api — /api/* endpoints + auth."""
import http.client
import json
import threading
from pathlib import Path

import pytest

from agent_html_drop import api as api_mod
from agent_html_drop import server as srv
from agent_html_drop.config import Config


TOKEN = "x" * 64
AUTH = "Bearer " + TOKEN


@pytest.fixture
def http_with_api(tmp_path):
    """Spin up server with /api/* routes registered against a tmp docroot."""
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


def _base(http):
    host, port = http.server_address
    return host, port


def _request(srv_, method, path, body=b"", headers=None):
    host, port = _base(srv_)
    hdrs = {"Content-Length": str(len(body))}
    if headers:
        hdrs.update(headers)
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request(method, path, body=body, headers=hdrs)
        r = conn.getresponse()
        data = r.read()
        return r.status, dict(r.getheaders()), data
    finally:
        conn.close()


# --- health ------------------------------------------------------------------

def test_health_no_auth(http_with_api):
    http, _, _ = http_with_api
    status, _, body = _request(http, "GET", "/api/health")
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert "version" in payload


# --- auth (list is public; write paths still require Bearer) -----------------

def test_list_files_no_auth_returns_200(http_with_api):
    """GET /api/files is public — list metadata for a docroot nginx already
    serves unauthenticated at /files/*. No Authorization header needed."""
    http, _, _ = http_with_api
    status, _, body = _request(http, "GET", "/api/files")
    assert status == 200
    payload = json.loads(body)
    assert payload["files"] == []


def test_list_files_ignores_stale_bearer(http_with_api):
    """Sending an old / wrong Bearer must not 401 the read path — list is
    public, header is simply ignored."""
    http, _, _ = http_with_api
    status, _, _ = _request(
        http, "GET", "/api/files", headers={"Authorization": "Bearer wrong"}
    )
    assert status == 200


# --- list_files --------------------------------------------------------------

def test_list_files_returns_existing(http_with_api):
    http, _, docroot = http_with_api
    (docroot / "design.html").write_text("<title>My Design</title>")
    (docroot / "notes.html").write_text("<title>My Notes</title>")
    status, _, body = _request(http, "GET", "/api/files")
    assert status == 200
    payload = json.loads(body)
    names = sorted(f["name"] for f in payload["files"])
    assert names == ["design.html", "notes.html"]
    for f in payload["files"]:
        assert f["url"].startswith("https://notes.example.com/")
        assert f["size"] > 0
        assert f["title"] is not None


def test_list_files_skips_non_html(http_with_api):
    http, _, docroot = http_with_api
    (docroot / "readme.txt").write_text("hi")
    (docroot / "design.html").write_text("x")
    status, _, body = _request(http, "GET", "/api/files")
    payload = json.loads(body)
    assert [f["name"] for f in payload["files"]] == ["design.html"]


# --- delete still requires Bearer ------------------------------------------

def test_delete_without_bearer_returns_401(http_with_api):
    """Write path — Bearer still required, even though list is public."""
    http, _, _ = http_with_api
    status, _, _ = _request(http, "DELETE", "/api/files/design.html")
    assert status == 401


def test_delete_with_wrong_bearer_returns_401(http_with_api):
    http, _, _ = http_with_api
    status, _, _ = _request(
        http, "DELETE", "/api/files/design.html",
        headers={"Authorization": "Bearer wrong"},
    )
    assert status == 401


# --- delete ------------------------------------------------------------------

def test_delete_existing(http_with_api):
    http, _, docroot = http_with_api
    (docroot / "design.html").write_text("x")
    status, _, body = _request(http, "DELETE", "/api/files/design.html",
                                headers={"Authorization": AUTH})
    assert status == 200
    payload = json.loads(body)
    assert payload["deleted"] is True
    assert not (docroot / "design.html").exists()


def test_delete_missing_returns_404(http_with_api):
    http, _, _ = http_with_api
    status, _, body = _request(http, "DELETE", "/api/files/missing.html",
                                headers={"Authorization": AUTH})
    assert status == 404
    assert json.loads(body)["error"] == "not_found"


def test_delete_invalid_name_returns_400(http_with_api):
    """A name with a space fails the regex → 400 invalid_name."""
    http, _, _ = http_with_api
    status, _, body = _request(
        http, "DELETE", "/api/files/bad%20name.html",
        headers={"Authorization": AUTH},
    )
    assert status == 400
    assert json.loads(body)["error"] == "invalid_name"


# --- nginx-config ------------------------------------------------------------

def test_nginx_config_renders(http_with_api):
    http, cfg, _ = http_with_api
    status, headers, body = _request(
        http, "GET", "/api/nginx-config", headers={"Authorization": AUTH}
    )
    assert status == 200
    assert "text/plain" in headers.get("Content-Type", "")
    text = body.decode("utf-8")
    assert cfg.docroot in text
    assert str(cfg.port) in text


def test_nginx_config_requires_bearer(http_with_api):
    http, _, _ = http_with_api
    status, _, _ = _request(http, "GET", "/api/nginx-config")
    assert status == 401