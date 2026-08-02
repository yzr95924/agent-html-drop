"""End-to-end smoke for the annotation flow.

Covers:
  - S36 (browser enters anno mode via /api/auth)
  - S37 (browser posts annotation, gets 201)
  - S39 (agent calls list_annotations and sees the entry)
  - S40 (agent calls delete_annotation and the entry is gone)
"""
import json
import threading

import pytest

from agent_html_drop.api import register_routes
from agent_html_drop.config import Config
from agent_html_drop.mcp_handler import register_route as register_mcp
from agent_html_drop.server import make_server, routes


@pytest.fixture
def live_server(tmp_path):
    routes.clear()
    docroot = tmp_path / "docroot"
    docroot.mkdir()
    # Pre-populate with a test HTML.
    (docroot / "design.html").write_text(
        "<!doctype html><html><body><p>sudo mkdir -p /var/www</p></body></html>",
        encoding="utf-8",
    )
    cfg = Config(
        host="127.0.0.1", port=0, docroot=str(docroot),
        public_base_url="https://notes.example.com",
        max_file_size=50 * 1024 * 1024, token="smoke-token",
        extra_top={}, extra_auth={},
    )
    from agent_html_drop import config as cfg_mod
    import agent_html_drop.auth_anno
    # Patch load_config for auth_anno._get_secret.
    original_load_config = cfg_mod.load_config
    cfg_mod.load_config = lambda *_args, **_kwargs: cfg  # type: ignore
    register_routes(cfg)
    register_mcp(cfg)
    srv = make_server("127.0.0.1", 0, quiet=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv, cfg
    finally:
        srv.shutdown()
        srv.server_close()
        cfg_mod.load_config = original_load_config
        routes.clear()


def _http(method, host, port, path, body=b"", headers=None):
    import http.client
    hdrs = {"Content-Length": str(len(body))}
    if headers:
        hdrs.update(headers)
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request(method, path, body=body, headers=hdrs)
        return conn.getresponse()
    finally:
        conn.close()


def test_full_annotation_roundtrip(live_server):
    srv, cfg = live_server
    host, port = srv.server_address

    # 1. Browser auth → cookie.
    r = _http("POST", host, port, "/api/auth",
              headers={"Authorization": "Bearer " + cfg.token})
    assert r.status == 204
    from http.cookies import SimpleCookie
    sc = SimpleCookie()
    sc.load(r.getheader("Set-Cookie"))
    cookie_value = sc["anno_session"].value

    # 2. Browser posts annotation.
    r = _http("POST", host, port, "/api/files/design.html/annotations",
              body=json.dumps({"quote": "sudo mkdir", "comment": "use user dir"}).encode("utf-8"),
              headers={
                  "Cookie": "anno_session=" + cookie_value,
                  "Origin": "https://notes.example.com",
                  "Host": "notes.example.com",
                  "Content-Type": "application/json",
              })
    assert r.status == 201
    anno = json.loads(r.read())
    assert anno["author"].startswith("tk_")

    # 3. Agent lists annotations via MCP.
    r = _http("POST", host, port, "/mcp",
              body=json.dumps({
                  "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": "list_annotations",
                             "arguments": {"name": "design.html"}},
              }).encode("utf-8"),
              headers={"Authorization": "Bearer " + cfg.token,
                       "Content-Type": "application/json"})
    payload = json.loads(json.loads(r.read())["result"]["content"][0]["text"])
    assert len(payload["annotations"]) == 1
    assert payload["annotations"][0]["quote"] == "sudo mkdir"

    # 4. Agent deletes via MCP.
    r = _http("POST", host, port, "/mcp",
              body=json.dumps({
                  "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": "delete_annotation",
                             "arguments": {"name": "design.html", "id": anno["id"]}},
              }).encode("utf-8"),
              headers={"Authorization": "Bearer " + cfg.token,
                       "Content-Type": "application/json"})
    payload = json.loads(json.loads(r.read())["result"]["content"][0]["text"])
    assert payload["deleted"] is True

    # 5. Confirm gone.
    r = _http("GET", host, port, "/api/files/design.html/annotations")
    payload = json.loads(r.read())
    assert payload["annotations"] == []
