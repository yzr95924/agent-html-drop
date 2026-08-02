"""Tests for MCP list_annotations + delete_annotation tools."""
import json
import threading

import pytest

from agent_html_drop.config import Config
from agent_html_drop.mcp_handler import register_route
from agent_html_drop.server import make_server, routes
from agent_html_drop.storage.annotations import add as anno_add


@pytest.fixture
def http_server(tmp_path):
    routes.clear()
    docroot = tmp_path / "docroot"
    docroot.mkdir()
    cfg = Config(
        host="127.0.0.1", port=0,
        docroot=str(docroot),
        public_base_url="https://notes.example.com",
        max_file_size=50 * 1024 * 1024,
        token="mcp-token",
        extra_top={}, extra_auth={},
    )
    register_route(cfg)
    srv = make_server("127.0.0.1", 0, quiet=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv, cfg
    finally:
        srv.shutdown()
        srv.server_close()
        routes.clear()


def _post(host, port, path, body=b"", headers=None):
    hdrs = {"Content-Length": str(len(body))}
    if headers:
        hdrs.update(headers)
    import http.client
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("POST", path, body=body, headers=hdrs)
        return conn.getresponse()
    finally:
        conn.close()


def _rpc(host, port, token, method, params=None):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode("utf-8")
    r = _post(host, port, "/mcp", body=body,
              headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    return json.loads(r.read())


def test_tools_list_includes_annotation_tools(http_server):
    srv, cfg = http_server
    host, port = srv.server_address
    data = _rpc(host, port, cfg.token, "tools/list")
    names = [t["name"] for t in data["result"]["tools"]]
    assert "list_annotations" in names
    assert "delete_annotation" in names


def test_list_annotations_returns_entries(http_server):
    from pathlib import Path
    srv, cfg = http_server
    docroot = Path(cfg.docroot)
    # Fix: create the HTML file first (required after spec compliance fix).
    (docroot / "design.html").write_text("<html><body>design</body></html>", encoding="utf-8")
    anno_add(docroot, "design.html", "q1", "c1", "t1")
    anno_add(docroot, "design.html", "q2", "c2", "t2")
    host, port = srv.server_address
    data = _rpc(host, port, cfg.token, "tools/call",
                {"name": "list_annotations", "arguments": {"name": "design.html"}})
    payload = json.loads(data["result"]["content"][0]["text"])
    assert payload["name"] == "design.html"
    assert len(payload["annotations"]) == 2


def test_delete_annotation_by_agent_succeeds(http_server):
    from pathlib import Path
    srv, cfg = http_server
    docroot = Path(cfg.docroot)
    entry = anno_add(docroot, "design.html", "q", "c", "browser-token")
    host, port = srv.server_address
    data = _rpc(host, port, cfg.token, "tools/call",
                {"name": "delete_annotation",
                 "arguments": {"name": "design.html", "id": entry["id"]}})
    payload = json.loads(data["result"]["content"][0]["text"])
    assert payload["deleted"] is True
    assert anno_store_count(docroot, "design.html") == 0


def test_delete_annotation_not_found_returns_error(http_server):
    srv, cfg = http_server
    host, port = srv.server_address
    data = _rpc(host, port, cfg.token, "tools/call",
                {"name": "delete_annotation",
                 "arguments": {"name": "design.html", "id": "NONEXISTENT"}})
    # Tool-level error (isError=True) with not_found code.
    assert data["result"]["isError"] is True
    assert "not_found" in data["result"]["content"][0]["text"]


def test_agent_no_add_annotation_tool(http_server):
    """N11: agent must NOT have a write-annotation tool."""
    srv, cfg = http_server
    host, port = srv.server_address
    data = _rpc(host, port, cfg.token, "tools/list")
    names = [t["name"] for t in data["result"]["tools"]]
    assert "add_annotation" not in names


def anno_store_count(docroot, name):
    from agent_html_drop.storage.annotations import count
    return count(docroot, name)


# --- Tests for whole-branch review findings (spec compliance fixes) ----------

def test_list_html_includes_annotation_count_zero(http_server):
    """Fix 1: list_html output must include annotation_count per file (0 case)."""
    from pathlib import Path
    srv, cfg = http_server
    docroot = Path(cfg.docroot)
    # Write an HTML file with no annotations
    (docroot / "note.html").write_text("<html><body>hi</body></html>", encoding="utf-8")
    host, port = srv.server_address
    data = _rpc(host, port, cfg.token, "tools/call",
                {"name": "list_html", "arguments": {}})
    payload = json.loads(data["result"]["content"][0]["text"])
    files = payload["files"]
    assert len(files) == 1
    assert files[0]["name"] == "note.html"
    assert "annotation_count" in files[0]
    assert files[0]["annotation_count"] == 0


def test_list_html_includes_annotation_count_with_annotations(http_server):
    """Fix 1: list_html output must include annotation_count (1+ case)."""
    from pathlib import Path
    srv, cfg = http_server
    docroot = Path(cfg.docroot)
    # Write HTML file and add annotations
    (docroot / "design.html").write_text("<html><body>design</body></html>", encoding="utf-8")
    anno_add(docroot, "design.html", "quote1", "comment1", "token1")
    anno_add(docroot, "design.html", "quote2", "comment2", "token2")
    host, port = srv.server_address
    data = _rpc(host, port, cfg.token, "tools/call",
                {"name": "list_html", "arguments": {}})
    payload = json.loads(data["result"]["content"][0]["text"])
    files = payload["files"]
    design_files = [f for f in files if f["name"] == "design.html"]
    assert len(design_files) == 1
    assert "annotation_count" in design_files[0]
    assert design_files[0]["annotation_count"] == 2


def test_list_annotations_missing_file_raises_not_found(http_server):
    """Fix 2: list_annotations must raise NotFound when HTML file doesn't exist."""
    srv, cfg = http_server
    host, port = srv.server_address
    # No HTML file exists at docroot; request list_annotations for nonexistent.html
    data = _rpc(host, port, cfg.token, "tools/call",
                {"name": "list_annotations", "arguments": {"name": "nonexistent.html"}})
    # Tool-level error (isError=True) with not_found code
    assert data["result"]["isError"] is True
    text = data["result"]["content"][0]["text"]
    assert "not_found" in text


def test_list_annotations_invalid_name_returns_error(http_server):
    """Fix 3: list_annotations must validate name via storage.validate_name."""
    srv, cfg = http_server
    host, port = srv.server_address
    # Path traversal attempt
    data = _rpc(host, port, cfg.token, "tools/call",
                {"name": "list_annotations", "arguments": {"name": "../etc/passwd"}})
    assert data["result"]["isError"] is True
    text = data["result"]["content"][0]["text"]
    assert "invalid_name" in text


def test_list_annotations_missing_html_extension_returns_error(http_server):
    """Fix 3: list_annotations must reject names without .html extension."""
    srv, cfg = http_server
    host, port = srv.server_address
    # Name that doesn't end in .html
    data = _rpc(host, port, cfg.token, "tools/call",
                {"name": "list_annotations", "arguments": {"name": "foo"}})
    assert data["result"]["isError"] is True
    text = data["result"]["content"][0]["text"]
    assert "invalid_name" in text


def test_list_annotations_wrong_extension_returns_error(http_server):
    """Fix 3: list_annotations must reject names with wrong extension."""
    srv, cfg = http_server
    host, port = srv.server_address
    # Name with wrong extension
    data = _rpc(host, port, cfg.token, "tools/call",
                {"name": "list_annotations", "arguments": {"name": "bar.html.txt"}})
    assert data["result"]["isError"] is True
    text = data["result"]["content"][0]["text"]
    assert "invalid_name" in text


def test_delete_annotation_invalid_name_returns_error(http_server):
    """Fix 3: delete_annotation must validate name via storage.validate_name."""
    srv, cfg = http_server
    host, port = srv.server_address
    # Path traversal attempt
    data = _rpc(host, port, cfg.token, "tools/call",
                {"name": "delete_annotation",
                 "arguments": {"name": "../etc/passwd", "id": "anyid"}})
    assert data["result"]["isError"] is True
    text = data["result"]["content"][0]["text"]
    assert "invalid_name" in text


def test_delete_annotation_missing_html_extension_returns_error(http_server):
    """Fix 3: delete_annotation must reject names without .html extension."""
    srv, cfg = http_server
    host, port = srv.server_address
    # Name that doesn't end in .html
    data = _rpc(host, port, cfg.token, "tools/call",
                {"name": "delete_annotation",
                 "arguments": {"name": "foo", "id": "anyid"}})
    assert data["result"]["isError"] is True
    text = data["result"]["content"][0]["text"]
    assert "invalid_name" in text


def test_delete_annotation_wrong_extension_returns_error(http_server):
    """Fix 3: delete_annotation must reject names with wrong extension."""
    srv, cfg = http_server
    host, port = srv.server_address
    # Name with wrong extension
    data = _rpc(host, port, cfg.token, "tools/call",
                {"name": "delete_annotation",
                 "arguments": {"name": "bar.html.txt", "id": "anyid"}})
    assert data["result"]["isError"] is True
    text = data["result"]["content"][0]["text"]
    assert "invalid_name" in text
