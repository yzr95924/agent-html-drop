"""JSON API endpoints used by the management page in the browser.

Three groups (design §7.3 / §8 / §15.3.1):

  HTML management (Bearer-protected, except /api/health):
    GET    /api/files                           list docroot
    DELETE /api/files/<name>                    delete
    GET    /api/nginx-config                    rendered reverse-proxy snippet
    GET    /api/health                          liveness probe (no auth)
    POST   /api/auth                            Bearer → annotation session cookie
    GET    /api/auth                            session cookie valid? (204/401)

  Annotation REST (cookie + CSRF, except GET is public):
    GET    /api/files/<name>/annotations        list (no auth)
    POST   /api/files/<name>/annotations        add (cookie + CSRF)
    PATCH  /api/files/<name>/annotations/<id>   edit own (cookie + CSRF + author)
    DELETE /api/files/<name>/annotations/<id>   delete own (cookie + CSRF + author)

  Container-mode public HTML (design §15.3.1; classic mode serves via nginx):
    GET    /files/<name>                        stream public HTML file

Each handler is a closure over ``cfg`` (built by ``register_routes``).
Storage exceptions map to HTTP status codes per design §7.3.
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from agent_html_drop import nginx_config as nginx_mod
from agent_html_drop import server as srv
from agent_html_drop import _legacy_storage as storage
from agent_html_drop.auth import check_bearer
from agent_html_drop.auth_anno import (
    ANNO_COOKIE_NAME,
    cookie_set_header,
    csrf_check,
    sign_cookie,
    verify_cookie,
)
from agent_html_drop.config import Config
from agent_html_drop.storage import annotations as anno_store

from ._version import VERSION


JSON = {"Content-Type": "application/json"}
TEXT = {"Content-Type": "text/plain; charset=utf-8"}

# Uniform 404 for the public /files/<name> route — missing / invalid name /
# traversal all look the same to avoid leaking which names are valid.
_NOT_FOUND = (404, b"not found\n", TEXT)


# --- helpers -----------------------------------------------------------------

def _unauthorized() -> Tuple[int, bytes, Dict[str, str]]:
    return (
        401,
        b'{"error":"unauthorized"}',
        JSON,
    )


def _require_bearer(req, cfg: Config):
    """Return None on success, or an error response tuple."""
    if not check_bearer(req.headers.get("Authorization"), cfg.token):
        return _unauthorized()
    return None


def _storage_error(exc: storage.StorageError):
    """Map a storage exception to an HTTP response."""
    if isinstance(exc, storage.InvalidName):
        return (400, _err("invalid_name", str(exc)), JSON)
    if isinstance(exc, storage.Conflict):
        return (409, _err("conflict", str(exc)), JSON)
    if isinstance(exc, storage.TooLarge):
        return (413, _err("too_large", str(exc)), JSON)
    if isinstance(exc, storage.NotFound):
        return (404, _err("not_found", str(exc)), JSON)
    if isinstance(exc, storage.DocrootUnwritable):
        return (500, _err("docroot_unwritable", str(exc)), JSON)
    # Unknown storage error → 500.
    return (500, _err("storage_error", str(exc)), JSON)


def _err(code: str, msg: str) -> bytes:
    return json.dumps({"error": code, "message": msg}).encode("utf-8")


def _file_info_payload(
    f: storage.FileInfo, public_base_url: str, docroot: Path
) -> Dict[str, Any]:
    return {
        "name": f.name,
        "size": f.size,
        "mtime": f.mtime,
        "url": public_base_url.rstrip("/") + "/files/" + f.name,
        "title": f.title,
        "annotation_count": anno_store.count(docroot, f.name),
    }


# --- handlers ----------------------------------------------------------------

def _validate_anno_name(name: str) -> bool:
    """Validate annotation lookup name (same rules as storage layer).

    Returns True if ``name`` is a legal upload filename, False otherwise.
    Defers to ``storage.validate_name`` so the regex / length cap stay
    in one place.
    """
    try:
        storage.validate_name(name)
        return True
    except storage.InvalidName:
        return False


def _anno_session_token(req) -> "Optional[str]":
    """Extract the token from the anno_session cookie, if valid."""
    cookie_header = req.headers.get("Cookie")
    if not cookie_header:
        return None
    from http.cookies import SimpleCookie as _SC
    sc = _SC()
    try:
        sc.load(cookie_header)
    except Exception:
        return None
    morsel = sc.get(ANNO_COOKIE_NAME)
    if morsel is None:
        return None
    return verify_cookie(morsel.value)


def _make_get_annotations(cfg: Config):
    """GET /api/files/<name>/annotations — public, no auth."""
    def handler(req, params, body):
        docroot = Path(cfg.docroot)
        name = params.get("name", "")
        if not _validate_anno_name(name):
            return (400, _err("invalid_name", "name failed validation"), JSON)
        entries = anno_store.list_for(docroot, name)
        return (
            200,
            json.dumps({
                "name": name,
                "annotations": entries,
            }, ensure_ascii=False).encode("utf-8"),
            JSON,
        )
    return handler


def _make_post_annotation(cfg: Config):
    """POST /api/files/<name>/annotations — cookie + CSRF."""
    def handler(req, params, body):
        token = _anno_session_token(req)
        if not token:
            return (401, _err("unauthorized", "no valid anno session"), JSON)
        if not csrf_check(
            req.headers.get("Host", ""),
            req.headers.get("Origin"),
            allow_insecure=cfg.allow_insecure_annotations,
        ):
            return (403, _err("csrf", "origin mismatch"), JSON)
        name = params.get("name", "")
        if not _validate_anno_name(name):
            return (400, _err("invalid_name", "name failed validation"), JSON)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return (400, _err("invalid_body", "body must be JSON"), JSON)
        if not isinstance(payload, dict):
            return (400, _err("invalid_args", "body must be a JSON object"), JSON)
        quote = payload.get("quote")
        comment = payload.get("comment")
        if not isinstance(quote, str) or not isinstance(comment, str):
            return (400, _err("invalid_args", "quote and comment must be strings"), JSON)
        try:
            entry = anno_store.add(Path(cfg.docroot), name, quote, comment, token)
        except (ValueError, TypeError) as exc:
            return (400, _err("invalid_args", str(exc)), JSON)
        return (201, json.dumps(entry, ensure_ascii=False).encode("utf-8"), JSON)
    return handler


def _author_of(token: str) -> str:
    return anno_store.author_of_token(token)


def _make_patch_annotation(cfg: Config):
    """PATCH /api/files/<name>/annotations/<id> — cookie + CSRF + author."""
    def handler(req, params, body):
        token = _anno_session_token(req)
        if not token:
            return (401, _err("unauthorized", "no valid anno session"), JSON)
        if not csrf_check(
            req.headers.get("Host", ""),
            req.headers.get("Origin"),
            allow_insecure=cfg.allow_insecure_annotations,
        ):
            return (403, _err("csrf", "origin mismatch"), JSON)
        name = params.get("name", "")
        id_ = params.get("id", "")
        if not _validate_anno_name(name):
            return (400, _err("invalid_name", "name failed validation"), JSON)
        docroot = Path(cfg.docroot)
        existing = anno_store.get(docroot, name, id_)
        if existing is None:
            return (404, _err("not_found", "annotation not found"), JSON)
        if existing["author"] != _author_of(token):
            return (403, _err("forbidden", "not your annotation"), JSON)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return (400, _err("invalid_body", "body must be JSON"), JSON)
        if not isinstance(payload, dict):
            return (400, _err("invalid_args", "body must be a JSON object"), JSON)
        comment = payload.get("comment")
        if not isinstance(comment, str):
            return (400, _err("invalid_args", "comment must be a string"), JSON)
        existing["comment"] = comment[:2000]
        # Save by replacing the entry in-place: load → mutate → save.
        doc = anno_store.load(docroot, name)
        for i, e in enumerate(doc["annotations"]):
            if e.get("id") == id_:
                doc["annotations"][i] = existing
                break
        anno_store.save(docroot, name, doc)
        return (200, json.dumps(existing, ensure_ascii=False).encode("utf-8"), JSON)
    return handler


def _make_delete_annotation(cfg: Config):
    """DELETE /api/files/<name>/annotations/<id> — cookie + CSRF + author."""
    def handler(req, params, body):
        token = _anno_session_token(req)
        if not token:
            return (401, _err("unauthorized", "no valid anno session"), JSON)
        if not csrf_check(
            req.headers.get("Host", ""),
            req.headers.get("Origin"),
            allow_insecure=cfg.allow_insecure_annotations,
        ):
            return (403, _err("csrf", "origin mismatch"), JSON)
        name = params.get("name", "")
        id_ = params.get("id", "")
        if not _validate_anno_name(name):
            return (400, _err("invalid_name", "name failed validation"), JSON)
        ok = anno_store.delete(Path(cfg.docroot), name, id_, token)
        if not ok:
            # Indistinguishable: id not found OR author mismatch → 403.
            return (403, _err("forbidden", "cannot delete this annotation"), JSON)
        return (200, json.dumps({"deleted": True}).encode("utf-8"), JSON)
    return handler

def _make_list_files(cfg: Config):
    def handler(req, params, body):
        # No auth: list_html returns public metadata (name/size/mtime/title/url)
        # of files in a docroot that nginx already serves unauthenticated at
        # /files/*. Single-user trust model + nginx reverse proxy in front.
        # Write paths (DELETE /api/files/<name>, POST /mcp) still require
        # Bearer — the management page does not expose those.
        docroot = Path(cfg.docroot)
        try:
            files = storage.list_files(docroot)
        except storage.StorageError as exc:
            return _storage_error(exc)
        payload = {
            "files": [
                _file_info_payload(f, cfg.public_base_url, docroot) for f in files
            ]
        }
        return (200, json.dumps(payload).encode("utf-8"), JSON)
    return handler


def _make_auth(cfg: Config):
    """Exchange a valid Bearer token for an annotation session cookie."""
    max_age = cfg.anno_session_max_age

    def handler(req, params, body):
        if not check_bearer(req.headers.get("Authorization"), cfg.token):
            return _unauthorized()
        cookie_value = sign_cookie(cfg.token, max_age=max_age)
        return (
            204,
            b"",
            {
                "Set-Cookie": cookie_set_header(
                    cookie_value,
                    max_age,
                    secure=not cfg.allow_insecure_annotations,
                )
            },
        )
    return handler


def _make_auth_status(cfg: Config):
    """GET /api/auth — is there a valid annotation session cookie?

    The cookie is HttpOnly (JS can't read it), so the UI can't tell from
    ``document.cookie`` whether it's still logged in after a refresh. This
    endpoint lets it ask the server: 204 = valid session (skip the token
    dialog), 401 = no/expired session (prompt for the token).
    """

    def handler(req, params, body):
        if _anno_session_token(req):
            return (204, b"", {})
        return (401, _err("unauthorized", "no valid anno session"), JSON)
    return handler


def _make_delete_file(cfg: Config):
    def handler(req, params, body):
        err = _require_bearer(req, cfg)
        if err:
            return err
        name = params.get("name", "")
        docroot = Path(cfg.docroot)
        try:
            deleted = storage.delete(docroot, name)
        except storage.StorageError as exc:
            return _storage_error(exc)
        if not deleted:
            return (404, _err("not_found", "file does not exist: {}".format(name)), JSON)
        return (200, json.dumps({"deleted": True}).encode("utf-8"), JSON)
    return handler


def _make_nginx_config(cfg: Config):
    def handler(req, params, body):
        err = _require_bearer(req, cfg)
        if err:
            return err
        text = nginx_mod.render(
            port=cfg.port,
            public_base_url=cfg.public_base_url,
        )
        return (200, text.encode("utf-8"), TEXT)
    return handler


def _health_handler(req, params, body):
    """No auth — health probes must be reachable without a token."""
    payload = {"status": "ok", "version": VERSION}
    return (200, json.dumps(payload).encode("utf-8"), JSON)


# <script> tag injected into annotated public pages so the read-only
# annotation viewer (ui/anno-viewer.js) loads on the public URL itself,
# letting visitors see highlights + comments without the management page.
_ANNO_VIEWER_TAG = '<script src="/anno-viewer.js" defer></script>'


def _inject_viewer(html: str) -> str:
    """Insert the public annotation-viewer <script> once, as late as the
    document allows (``</body>`` → ``</html>`` → append). Idempotent — a
    page that already references the viewer is returned unchanged."""
    if "anno-viewer.js" in html:
        return html
    lowered = html.lower()
    idx = lowered.find("</body>")
    if idx < 0:
        idx = lowered.find("</html>")
    if idx < 0:
        return html + _ANNO_VIEWER_TAG
    return html[:idx] + _ANNO_VIEWER_TAG + html[idx:]


def _make_get_file(cfg: Config):
    """GET /files/<name> — daemon-served public HTML (design §15.3.1).

    Streaming (``Handler.send_file``) + path-traversal-safe
    (``validate_name`` + resolve-under-docroot). Missing / invalid name /
    traversal → uniform 404 (no info leak on a public route). No auth —
    "push = public" trust model (§9.3), same as classic mode's nginx
    direct-read of /files/*.
    """
    docroot = Path(cfg.docroot)

    def handler(req, params, body):
        name = params.get("name", "")
        try:
            storage.validate_name(name)
        except storage.InvalidName:
            return _NOT_FOUND
        # Defense-in-depth: a symlink inside docroot could point outside.
        base = docroot.resolve()
        try:
            target = (docroot / name).resolve()
            target.relative_to(base)  # raises ValueError if outside docroot
        except (ValueError, OSError):
            return _NOT_FOUND
        if not target.is_file():
            return _NOT_FOUND
        # Public annotation viewer: when this file has annotations, inject a
        # read-only <script src="/anno-viewer.js"> so visitors of the public
        # URL see highlights + comments instead of bare HTML. Files without
        # annotations stream unchanged (no per-request overhead, no viewer).
        if anno_store.count(docroot, name) > 0:
            try:
                text = target.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                # Binary / undecodable — serve raw, skip the viewer.
                req.send_file(str(target), "text/html; charset=utf-8")
                return (200, srv.STREAMED, {})
            injected = _inject_viewer(text).encode("utf-8")
            return (200, injected, {"Content-Type": "text/html; charset=utf-8"})
        req.send_file(str(target), "text/html; charset=utf-8")
        return (200, srv.STREAMED, {})

    return handler


# --- registration ------------------------------------------------------------

def register_routes(cfg: Config) -> None:
    """Register all /api/* and /health routes on the server registry."""
    srv.register("GET", r"^/api/files$", _make_list_files(cfg))
    srv.register("DELETE", r"^/api/files/(?P<name>[^/]+)$", _make_delete_file(cfg))
    srv.register("GET", r"^/api/nginx-config$", _make_nginx_config(cfg))
    srv.register("GET", r"^/api/health$", _health_handler)
    srv.register("POST", r"^/api/auth$", _make_auth(cfg))
    srv.register("GET", r"^/api/auth$", _make_auth_status(cfg))
    # Annotation REST endpoints.
    srv.register("GET",
                 r"^/api/files/(?P<name>[^/]+)/annotations$",
                 _make_get_annotations(cfg))
    srv.register("POST",
                 r"^/api/files/(?P<name>[^/]+)/annotations$",
                 _make_post_annotation(cfg))
    srv.register("PATCH",
                 r"^/api/files/(?P<name>[^/]+)/annotations/(?P<id>[A-Za-z0-9_-]+)$",
                 _make_patch_annotation(cfg))
    srv.register("DELETE",
                 r"^/api/files/(?P<name>[^/]+)/annotations/(?P<id>[A-Za-z0-9_-]+)$",
                 _make_delete_annotation(cfg))
    # Public HTML serving (container mode §15.3.1; classic mode uses nginx
    # direct-read). Streaming + path-traversal-safe; see _make_get_file.
    srv.register("GET", r"^/files/(?P<name>[^/]+)$", _make_get_file(cfg))