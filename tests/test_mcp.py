"""Tests for agent_html_drop.mcp_handler — JSON-RPC + 4 tools + auth."""
import http.client
import json
import threading

import pytest

from agent_html_drop import mcp_handler
from agent_html_drop import server as srv
from agent_html_drop.config import Config


TOKEN = "x" * 64
AUTH = "Bearer " + TOKEN


def _rpc(srv_, method, params=None, *, rid=1, auth=AUTH):
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": rid,
        "method": method,
        "params": params or {},
    }).encode("utf-8")
    host, port = srv_.server_address
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        hdrs = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        if auth is not None:
            hdrs["Authorization"] = auth
        conn.request("POST", "/mcp", body=body, headers=hdrs)
        r = conn.getresponse()
        return r.status, json.loads(r.read())
    finally:
        conn.close()


@pytest.fixture
def mcp_server(tmp_path):
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
    # Register both /mcp (for tool calls) and /api/* + /files/* (for the
    # streaming PUT side-channel tested alongside MCP upload_html).
    mcp_handler.register_route(cfg)
    from agent_html_drop import api as api_mod
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


# --- protocol envelope -------------------------------------------------------

def test_invalid_json_returns_400(mcp_server):
    srv_, _, _ = mcp_server
    host, port = srv_.server_address
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("POST", "/mcp", body=b"not json", headers={
            "Content-Type": "application/json",
            "Content-Length": "8",
            "Authorization": AUTH,
        })
        r = conn.getresponse()
        assert r.status == 400
        payload = json.loads(r.read())
        assert payload["error"]["code"] == -32700
    finally:
        conn.close()


def test_missing_jsonrpc_returns_invalid_request(mcp_server):
    """Body without ``jsonrpc: 2.0`` is rejected at HTTP layer (400)."""
    srv_, _, _ = mcp_server
    body = json.dumps({"id": 1, "method": "initialize", "params": {}}).encode("utf-8")
    host, port = srv_.server_address
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("POST", "/mcp", body=body, headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "Authorization": AUTH,
        })
        r = conn.getresponse()
        assert r.status == 400
        payload = json.loads(r.read())
        assert payload["error"]["code"] == -32600
    finally:
        conn.close()


def test_unknown_method_returns_method_not_found(mcp_server):
    http, _, _ = mcp_server
    status, payload = _rpc(http, "nonsense/method", {}, rid=1)
    assert status == 200  # JSON-RPC errors are HTTP 200
    assert payload["error"]["code"] == -32601


# --- auth --------------------------------------------------------------------

def test_missing_bearer_returns_401(mcp_server):
    http, _, _ = mcp_server
    status, payload = _rpc(http, "tools/list", auth=None)
    assert status == 401
    assert payload["error"]["code"] == -32001


def test_wrong_bearer_returns_401(mcp_server):
    http, _, _ = mcp_server
    status, payload = _rpc(http, "tools/list", auth="Bearer wrong")
    assert status == 401
    assert payload["error"]["code"] == -32001


# --- initialize / tools/list -------------------------------------------------

def test_initialize_returns_server_info(mcp_server):
    http, _, _ = mcp_server
    status, payload = _rpc(http, "initialize")
    assert status == 200
    assert payload["result"]["serverInfo"]["name"] == "agent-html-drop"
    assert "version" in payload["result"]["serverInfo"]
    assert payload["result"]["capabilities"]["tools"] == {}


def test_tools_list_returns_six_tools(mcp_server):
    http, _, _ = mcp_server
    status, payload = _rpc(http, "tools/list")
    assert status == 200
    names = sorted(t["name"] for t in payload["result"]["tools"])
    assert names == ["delete_annotation", "delete_html", "get_public_url", "list_annotations", "list_html", "upload_html"]


def test_tools_list_advertises_input_schemas(mcp_server):
    http, _, _ = mcp_server
    status, payload = _rpc(http, "tools/list")
    by_name = {t["name"]: t for t in payload["result"]["tools"]}
    schema = by_name["upload_html"]["inputSchema"]
    # New shape: bytes arrive via PUT /files/<name>, not via this tool.
    assert "name" in schema["properties"]
    assert "sha256" in schema["properties"]
    assert "content" not in schema["properties"]
    assert "force" not in schema["properties"]
    assert schema["required"] == ["name", "sha256"]


def test_notifications_initialized_is_acked(mcp_server):
    http, _, _ = mcp_server
    status, payload = _rpc(http, "notifications/initialized")
    assert status == 200
    assert payload["result"] is None


# --- tools/call: upload_html (verify-not-write) ------------------------------
#
# upload_html is now a metadata-only confirmation step. The actual
# bytes arrive via PUT /files/<name> (the streaming side-channel);
# upload_html only checks the file is on disk and its sha256 matches
# what the agent saw locally, then returns the public URL.

import hashlib


def test_upload_html_success(mcp_server):
    """File on disk + matching sha256 → URL returned, no write."""
    import http.client
    http, cfg, docroot = mcp_server
    body = b"<html><body>hi</body></html>"
    (docroot / "design.html").write_bytes(body)
    sha = hashlib.sha256(body).hexdigest()
    status, payload = _rpc(http, "tools/call", {
        "name": "upload_html",
        "arguments": {"name": "design.html", "sha256": sha},
    })
    assert status == 200
    assert payload["result"]["isError"] is False
    inner = json.loads(payload["result"]["content"][0]["text"])
    assert inner["url"] == "https://notes.example.com/files/design.html"
    assert inner["name"] == "design.html"
    assert inner["size"] == len(body)
    assert inner["sha256"] == sha
    # File untouched (no overwrite happens here).
    assert (docroot / "design.html").read_bytes() == body


def test_upload_html_after_put_round_trip(mcp_server):
    """Real flow: PUT bytes, then call upload_html with that sha256."""
    srv_, cfg, docroot = mcp_server
    body = b"<html><body>round-trip</body></html>"
    # PUT first
    host, port = srv_.server_address
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("PUT", "/files/design.html?force=true", body=body, headers={
            "Content-Length": str(len(body)),
            "Authorization": "Bearer " + TOKEN,
        })
        r = conn.getresponse()
        assert r.status == 201
        r.read()
    finally:
        conn.close()
    # Then call upload_html to register it in agent context
    sha = hashlib.sha256(body).hexdigest()
    status, payload = _rpc(srv_, "tools/call", {
        "name": "upload_html",
        "arguments": {"name": "design.html", "sha256": sha},
    })
    assert payload["result"]["isError"] is False
    inner = json.loads(payload["result"]["content"][0]["text"])
    assert inner["sha256"] == sha
    assert inner["url"].endswith("/files/design.html")


def test_upload_html_file_missing_returns_not_found(mcp_server):
    http, _, _ = mcp_server
    status, payload = _rpc(http, "tools/call", {
        "name": "upload_html",
        "arguments": {
            "name": "nope.html",
            "sha256": "0" * 64,
        },
    })
    assert payload["result"]["isError"] is True
    inner = json.loads(payload["result"]["content"][0]["text"])
    assert inner["error"] == "not_found"


def test_upload_html_sha256_mismatch(mcp_server):
    http, _, docroot = mcp_server
    (docroot / "x.html").write_bytes(b"<html>actual</html>")
    status, payload = _rpc(http, "tools/call", {
        "name": "upload_html",
        "arguments": {"name": "x.html", "sha256": "0" * 64},
    })
    assert payload["result"]["isError"] is True
    inner = json.loads(payload["result"]["content"][0]["text"])
    assert inner["error"] == "invalid_args"
    assert "sha256 mismatch" in inner["message"]


def test_upload_html_invalid_name(mcp_server):
    http, _, _ = mcp_server
    status, payload = _rpc(http, "tools/call", {
        "name": "upload_html",
        "arguments": {"name": "bad name.html", "sha256": "0" * 64},
    })
    assert payload["result"]["isError"] is True
    inner = json.loads(payload["result"]["content"][0]["text"])
    assert inner["error"] == "invalid_name"


def test_upload_html_case_insensitive_existing(mcp_server):
    """design.html URL but Design.HTML on disk → found, URL reflects on-disk case."""
    http, _, docroot = mcp_server
    body = b"<html>case</html>"
    (docroot / "Design.HTML").write_bytes(body)
    sha = hashlib.sha256(body).hexdigest()
    status, payload = _rpc(http, "tools/call", {
        "name": "upload_html",
        "arguments": {"name": "design.html", "sha256": sha},
    })
    assert payload["result"]["isError"] is False
    inner = json.loads(payload["result"]["content"][0]["text"])
    # Name reflects actual on-disk casing (case-insensitive lookup).
    assert inner["name"] == "Design.HTML"
    assert inner["sha256"] == sha


def test_upload_html_unknown_tool(mcp_server):
    http, _, _ = mcp_server
    status, payload = _rpc(http, "tools/call", {
        "name": "nonsense_tool",
        "arguments": {},
    })
    assert status == 200
    assert payload["result"]["isError"] is True
    inner = json.loads(payload["result"]["content"][0]["text"])
    assert inner["error"] == "unknown_tool"


# --- tools/call: list_html ---------------------------------------------------

def test_list_html_empty(mcp_server):
    http, _, _ = mcp_server
    status, payload = _rpc(http, "tools/call", {"name": "list_html", "arguments": {}})
    inner = json.loads(payload["result"]["content"][0]["text"])
    assert inner["files"] == []


def test_list_html_with_files(mcp_server):
    http, _, docroot = mcp_server
    (docroot / "a.html").write_text("<title>A</title>")
    (docroot / "b.html").write_text("<title>B</title>")
    status, payload = _rpc(http, "tools/call", {"name": "list_html", "arguments": {}})
    inner = json.loads(payload["result"]["content"][0]["text"])
    names = sorted(f["name"] for f in inner["files"])
    assert names == ["a.html", "b.html"]
    for f in inner["files"]:
        assert f["url"].startswith("https://notes.example.com/files/")


# --- tools/call: delete_html -------------------------------------------------

def test_delete_html_success(mcp_server):
    http, _, docroot = mcp_server
    (docroot / "design.html").write_text("x")
    status, payload = _rpc(http, "tools/call", {
        "name": "delete_html",
        "arguments": {"name": "design.html"},
    })
    assert payload["result"]["isError"] is False
    inner = json.loads(payload["result"]["content"][0]["text"])
    assert inner["deleted"] is True
    assert not (docroot / "design.html").exists()


def test_delete_html_missing(mcp_server):
    http, _, _ = mcp_server
    status, payload = _rpc(http, "tools/call", {
        "name": "delete_html",
        "arguments": {"name": "missing.html"},
    })
    assert payload["result"]["isError"] is True
    inner = json.loads(payload["result"]["content"][0]["text"])
    assert inner["error"] == "not_found"


def test_delete_html_cascades_annotation_meta(mcp_server):
    """delete_html must also drop the .meta sidecar — annotations must not
    outlive the document as orphans (regression: it used to leave .meta
    behind, so list_annotations on a deleted file still returned stale
    entries until the meta was manually removed)."""
    from agent_html_drop.storage import annotations as anno_store
    http, _, docroot = mcp_server
    (docroot / "design.html").write_text("x")
    anno_store.add(docroot, "design.html", "q", "c", "tok")
    assert (docroot / "design.html.meta").exists()
    status, payload = _rpc(http, "tools/call", {
        "name": "delete_html",
        "arguments": {"name": "design.html"},
    })
    assert payload["result"]["isError"] is False
    assert not (docroot / "design.html").exists()
    assert not (docroot / "design.html.meta").exists()  # cascaded


# --- tools/call: get_public_url ----------------------------------------------

def test_get_public_url(mcp_server):
    http, _, _ = mcp_server
    status, payload = _rpc(http, "tools/call", {
        "name": "get_public_url",
        "arguments": {"name": "design.html"},
    })
    inner = json.loads(payload["result"]["content"][0]["text"])
    assert inner["url"] == "https://notes.example.com/files/design.html"


def test_get_public_url_does_not_require_file_existence(mcp_server):
    http, _, docroot = mcp_server
    assert not (docroot / "future.html").exists()
    status, payload = _rpc(http, "tools/call", {
        "name": "get_public_url",
        "arguments": {"name": "future.html"},
    })
    assert payload["result"]["isError"] is False


# --- arguments validation ----------------------------------------------------

def test_upload_html_missing_required_arg(mcp_server):
    http, _, _ = mcp_server
    status, payload = _rpc(http, "tools/call", {
        "name": "upload_html",
        "arguments": {"name": "design.html"},  # no sha256
    })
    assert payload["result"]["isError"] is True
    inner = json.loads(payload["result"]["content"][0]["text"])
    assert inner["error"] == "invalid_args"


def test_tools_call_missing_name(mcp_server):
    http, _, _ = mcp_server
    status, payload = _rpc(http, "tools/call", {"arguments": {}})
    assert payload["error"]["code"] == -32602


def test_tools_call_params_must_be_object(mcp_server):
    http, _, _ = mcp_server
    # params = array, not object
    status, payload = _rpc(http, "tools/call", params=["bad"])
    assert payload["error"]["code"] == -32602