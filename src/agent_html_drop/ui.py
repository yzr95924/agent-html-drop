"""Serve the bundled management page (HTML + CSS + JS).

The page itself is **not** Bearer-protected — it contains no secrets,
just an empty shell + JS that fetches ``/api/files`` with the user's
pasted token. All sensitive operations happen at the ``/api/*`` layer,
which still requires Bearer. (Deviates from design §7.3 literal wording
for UX; the security boundary is unchanged because no data is exposed
without auth.)

Routes:

  - ``GET /``               → ``ui/index.html``
  - ``GET /style.css``      → ``ui/style.css``
  - ``GET /app.js``         → ``ui/app.js``
  - ``GET /anno-viewer.js`` → ``ui/anno-viewer.js`` (public-page annotation viewer)
  - ``GET /anno-marks.css`` → ``ui/anno-marks.css`` (shared <mark> highlight)
"""
import os

from agent_html_drop import server as srv


_HERE = os.path.dirname(__file__)
_UI_DIR = os.path.join(_HERE, "ui")

_FILES = {
    "/": "index.html",
    "/style.css": "style.css",
    "/app.js": "app.js",
    "/anno-viewer.js": "anno-viewer.js",
    "/anno-marks.css": "anno-marks.css",
}

_TEXT_HTML = {"Content-Type": "text/html; charset=utf-8"}
_TEXT_CSS = {"Content-Type": "text/css; charset=utf-8"}
_TEXT_JS = {"Content-Type": "application/javascript; charset=utf-8"}

_CONTENT_TYPE_FOR = {
    "index.html": _TEXT_HTML,
    "style.css": _TEXT_CSS,
    "app.js": _TEXT_JS,
    "anno-viewer.js": _TEXT_JS,
    "anno-marks.css": _TEXT_CSS,
}


def _serve(filename):
    def handler(req, params, body):
        path = os.path.join(_UI_DIR, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            return (404, b"not found", {"Content-Type": "text/plain"})
        return (200, text.encode("utf-8"), _CONTENT_TYPE_FOR[filename])
    return handler


def register_routes() -> None:
    """Register the UI static-file routes on the server registry."""
    for url_path, filename in _FILES.items():
        pattern = "^" + url_path.rstrip("/") + "/?$"
        # For "/", rstrip + "/" + $ would be "^/$" — perfect.
        # For "/style.css", rstrip + "/" + $ would be "^/style.css/?$" — fine.
        srv.register("GET", pattern, _serve(filename))