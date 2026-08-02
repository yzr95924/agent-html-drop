"""MCP Streamable HTTP transport + tool dispatcher.

Self-implemented JSON-RPC 2.0 handler (no MCP SDK — design §6 / §10).
Supports the three methods Claude Code actually uses against an MCP
server:

  - ``initialize``              — protocol handshake (returns server info)
  - ``tools/list``              — return the 4 tools' schemas
  - ``tools/call``              — dispatch to upload / list / delete /
                                  get_public_url

Bearer auth on every request (design §7.3). Errors map to JSON-RPC
codes (with custom -32001 for unauthorized).
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

from agent_html_drop import _legacy_storage as storage
from agent_html_drop.auth import check_bearer
from agent_html_drop.config import Config

from ._version import VERSION


JSON = {"Content-Type": "application/json"}
SERVER_INFO = {
    "name": "agent-html-drop",
    "version": VERSION,
}


# --- tool schemas (advertised via tools/list) ------------------------------

TOOL_SCHEMAS = [
    {
        "name": "upload_html",
        "description": (
            "Upload a self-contained HTML file to the nginx docroot. "
            "Returns the public URL. Pass force=true to overwrite an "
            "existing file with the same (case-insensitive) name."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Filename; must match [A-Za-z0-9._-]+\\.html, max 200 chars."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "HTML content (UTF-8 text).",
                },
                "force": {
                    "type": "boolean",
                    "default": False,
                    "description": "Overwrite an existing file with the same name.",
                },
            },
            "required": ["name", "content"],
        },
    },
    {
        "name": "list_html",
        "description": "List all HTML files currently in the docroot.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "delete_html",
        "description": "Delete a single HTML file from the docroot by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_public_url",
        "description": (
            "Return the public URL for a given filename (whether or not the "
            "file exists yet — useful for previewing the URL before upload)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_annotations",
        "description": (
            "List all annotations on a given HTML file. Returns public metadata: "
            "id, quote, comment, author (irreversible token hash), ts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Filename of the HTML."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "delete_annotation",
        "description": (
            "Delete a single annotation by id. Agents can delete any annotation "
            "(privileged deleter for spam cleanup); browser-side delete requires "
            "author match (enforced in REST, not here)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "id": {"type": "string"},
            },
            "required": ["name", "id"],
        },
    },
]


# --- error helpers -----------------------------------------------------------

def _err(code: int, message: str, request_id: Any = None) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _ok(result: Any, request_id: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _tool_result(text: str, is_error: bool = False) -> Dict[str, Any]:
    """Wrap a tool result in MCP's content envelope."""
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def _storage_code(exc: storage.StorageError) -> int:
    """Map a storage exception to an MCP error code."""
    if isinstance(exc, storage.InvalidName):
        return -32602
    if isinstance(exc, storage.Conflict):
        return -32010
    if isinstance(exc, storage.TooLarge):
        return -32011
    if isinstance(exc, storage.DocrootUnwritable):
        return -32012
    if isinstance(exc, storage.NotFound):
        return -32020
    return -32603


def _error_class_name(exc: storage.StorageError) -> str:
    """Convert a storage exception class name to snake_case format."""
    name = exc.__class__.__name__
    # Simple conversion: NotFound → not_found, InvalidName → invalid_name, etc.
    result = ""
    for i, char in enumerate(name):
        if i > 0 and char.isupper():
            result += "_" + char.lower()
        else:
            result += char.lower()
    return result


# --- tool implementations ---------------------------------------------------

def _impl_upload_html(args: Dict[str, Any], cfg: Config) -> Dict[str, Any]:
    name = args.get("name")
    content = args.get("content")
    force = bool(args.get("force", False))

    if not isinstance(name, str) or not isinstance(content, str):
        raise ValueError("name and content must be strings")

    info = storage.upload(
        Path(cfg.docroot),
        name,
        content,
        max_size=cfg.max_file_size,
        force=force,
    )
    payload = {
        "url": cfg.public_base_url.rstrip("/") + "/files/" + info.name,
        "name": info.name,
        "size": info.size,
    }
    return _tool_result(json.dumps(payload))


def _impl_list_html(args: Dict[str, Any], cfg: Config) -> Dict[str, Any]:
    from agent_html_drop.storage import annotations as anno_store
    docroot = Path(cfg.docroot)
    files = storage.list_files(docroot)
    payload = {
        "files": [
            {
                "name": f.name,
                "size": f.size,
                "mtime": f.mtime,
                "url": cfg.public_base_url.rstrip("/") + "/files/" + f.name,
                "title": f.title,
                "annotation_count": anno_store.count(docroot, f.name),
            }
            for f in files
        ]
    }
    return _tool_result(json.dumps(payload))


def _impl_delete_html(args: Dict[str, Any], cfg: Config) -> Dict[str, Any]:
    name = args.get("name")
    if not isinstance(name, str):
        raise ValueError("name must be a string")
    deleted = storage.delete(Path(cfg.docroot), name)
    if not deleted:
        # Match the API's behavior: 404 / -32020.
        raise storage.NotFound("file does not exist: {}".format(name))
    return _tool_result(json.dumps({"deleted": True}))


def _impl_get_public_url(args: Dict[str, Any], cfg: Config) -> Dict[str, Any]:
    name = args.get("name")
    if not isinstance(name, str):
        raise ValueError("name must be a string")
    # No filesystem check — this tool is meant to preview URL pre-upload.
    url = cfg.public_base_url.rstrip("/") + "/files/" + name
    return _tool_result(json.dumps({"url": url}))


def _impl_list_annotations(args: Dict[str, Any], cfg: Config) -> Dict[str, Any]:
    from agent_html_drop.storage import annotations as anno_store
    name = args.get("name")
    if not isinstance(name, str):
        raise ValueError("name must be a string")
    storage.validate_name(name)
    docroot = Path(cfg.docroot)
    if not (docroot / name).exists():
        raise storage.NotFound("file does not exist: {}".format(name))
    entries = anno_store.list_for(docroot, name)
    return _tool_result(json.dumps({"name": name, "annotations": entries}, ensure_ascii=False))


def _impl_delete_annotation(args: Dict[str, Any], cfg: Config) -> Dict[str, Any]:
    from agent_html_drop.storage import annotations as anno_store
    name = args.get("name")
    id_ = args.get("id")
    if not isinstance(name, str) or not isinstance(id_, str):
        raise ValueError("name and id must be strings")
    storage.validate_name(name)
    docroot = Path(cfg.docroot)
    doc = anno_store.load(docroot, name)
    before = len(doc["annotations"])
    doc["annotations"] = [e for e in doc["annotations"] if e.get("id") != id_]
    if len(doc["annotations"]) == before:
        raise storage.NotFound("annotation not found: {}".format(id_))
    anno_store.save(docroot, name, doc)
    return _tool_result(json.dumps({"deleted": True}))


_TOOL_DISPATCH = {
    "upload_html": _impl_upload_html,
    "list_html": _impl_list_html,
    "delete_html": _impl_delete_html,
    "get_public_url": _impl_get_public_url,
}

_TOOL_DISPATCH["list_annotations"] = _impl_list_annotations
_TOOL_DISPATCH["delete_annotation"] = _impl_delete_annotation


# --- JSON-RPC dispatch ------------------------------------------------------

def handle(req, params, body: bytes, cfg: Config) -> Tuple[int, bytes, Dict[str, str]]:
    """Handle a single ``POST /mcp`` request. Returns an HTTP response tuple."""
    # 1. Parse body.
    try:
        msg = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return (
            400,
            json.dumps(_err(-32700, "parse error: invalid JSON")).encode("utf-8"),
            JSON,
        )

    if not isinstance(msg, dict):
        return (
            400,
            json.dumps(_err(-32600, "invalid request: not an object")).encode("utf-8"),
            JSON,
        )

    request_id = msg.get("id")
    method = msg.get("method")
    rpc_params = msg.get("params", {})

    if msg.get("jsonrpc") != "2.0":
        return (
            400,
            json.dumps(_err(-32600, "invalid request: jsonrpc must be '2.0'", request_id)).encode("utf-8"),
            JSON,
        )
    if not isinstance(method, str):
        return (
            400,
            json.dumps(_err(-32600, "invalid request: method must be a string", request_id)).encode("utf-8"),
            JSON,
        )

    # 2. Auth (design §7.3 — every MCP request requires Bearer).
    if not check_bearer(req.headers.get("Authorization"), cfg.token):
        return (
            401,
            json.dumps(_err(-32001, "unauthorized", request_id)).encode("utf-8"),
            JSON,
        )

    # 3. Dispatch.
    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "serverInfo": SERVER_INFO,
                "capabilities": {"tools": {}},
            }
            return (
                200,
                json.dumps(_ok(result, request_id)).encode("utf-8"),
                JSON,
            )

        if method == "notifications/initialized":
            # Client → server notification; no response body needed but
            # we still acknowledge with 204 + null id (JSON-RPC 2.0 §4.1).
            return (
                200,
                json.dumps(_ok(None, request_id)).encode("utf-8"),
                JSON,
            )

        if method == "tools/list":
            return (
                200,
                json.dumps(_ok({"tools": TOOL_SCHEMAS}, request_id)).encode("utf-8"),
                JSON,
            )

        if method == "tools/call":
            if not isinstance(rpc_params, dict):
                return (
                    400,
                    json.dumps(_err(-32602, "params must be an object", request_id)).encode("utf-8"),
                    JSON,
                )
            tool_name = rpc_params.get("name")
            arguments = rpc_params.get("arguments", {})
            if not isinstance(tool_name, str):
                return (
                    400,
                    json.dumps(_err(-32602, "params.name must be a string", request_id)).encode("utf-8"),
                    JSON,
                )
            impl = _TOOL_DISPATCH.get(tool_name)
            if impl is None:
                return (
                    200,
                    json.dumps(_ok(_tool_result(
                        json.dumps({"error": "unknown_tool", "name": tool_name}),
                        is_error=True,
                    ), request_id)).encode("utf-8"),
                    JSON,
                )
            try:
                result = impl(arguments, cfg)
            except storage.StorageError as exc:
                code = _storage_code(exc)
                # Surface as a tool-level error (isError=True) so the
                # agent sees a structured failure inside result.content,
                # not a JSON-RPC error (which Claude Code treats as a
                # protocol-level failure).
                err_payload = {
                    "error": _error_class_name(exc),
                    "message": str(exc),
                }
                return (
                    200,
                    json.dumps(_ok(_tool_result(
                        json.dumps(err_payload), is_error=True
                    ), request_id)).encode("utf-8"),
                    JSON,
                )
            except ValueError as exc:
                return (
                    200,
                    json.dumps(_ok(_tool_result(
                        json.dumps({"error": "invalid_args", "message": str(exc)}),
                        is_error=True,
                    ), request_id)).encode("utf-8"),
                    JSON,
                )
            return (
                200,
                json.dumps(_ok(result, request_id)).encode("utf-8"),
                JSON,
            )

        # Unknown method.
        return (
            200,
            json.dumps(_err(-32601, "method not found: {}".format(method), request_id)).encode("utf-8"),
            JSON,
        )
    except Exception as exc:
        # Unexpected internal error.
        sys.stderr.write(
            "agent-html-drop: mcp_handler internal error: {!r}\n".format(exc)
        )
        return (
            500,
            json.dumps(_err(-32603, "internal error", request_id)).encode("utf-8"),
            JSON,
        )


def make_handler(cfg: Config):
    """Return a closure matching the server's Handler signature."""
    def _h(req, params, body):
        return handle(req, params, body, cfg)
    return _h


def register_route(cfg: Config) -> None:
    """Register ``POST /mcp`` on the server registry."""
    from agent_html_drop import server as srv
    srv.register("POST", r"^/mcp$", make_handler(cfg))