"""HTTP server skeleton + routing + method whitelist + body size limit.

Pure stdlib ``http.server.ThreadingHTTPServer``. Routes are registered
by ``cli.serve`` at startup (one registry, see ``register`` / ``routes``);
handler signature is ``(req, params) -> (status, body, headers)``.

Design §7.1.1 / §7.3 / §8:
  - method whitelist: unmatched method on matched path → 405 + Allow
  - body size limit: ``max_body_size`` bytes; oversize → 413 + close
  - graceful shutdown: SIGINT/SIGTERM → ``server.shutdown()``; existing
    in-flight requests in worker threads finish, then ``serve_forever()``
    returns
"""
import os
import re
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse


# Route signature: handler(req, params) -> (status, body, headers)
Handler = Callable[["Handler", Dict[str, str]], Tuple[int, bytes, Dict[str, str]]]
Route = Tuple[str, "re.Pattern[str]", Handler]

# Module-level route registry. Populated by cli.serve at startup.
routes: List[Route] = []

# Sentinel a handler returns as ``body`` when it has already streamed the
# response itself (headers + chunks written directly to ``wfile``). The
# dispatcher then skips the default bytes-body response. Used by the
# /files/<name> route so large HTML need not be loaded whole into memory.
STREAMED = object()


def register(method: str, pattern: str, handler: Handler) -> None:
    """Register ``handler`` for ``method`` + path regex ``pattern``.

    Path patterns use Python regex with named groups for path params,
    e.g. ``r"^/api/files/(?P<name>[^/]+)$"``. Order matters — first match
    wins.
    """
    routes.append((method.upper(), re.compile(pattern), handler))


class BodyTooLarge(Exception):
    """Raised by ``Handler._read_body`` when the request body exceeds
    the configured cap. The dispatcher catches this and answers 413."""

    def __init__(self, length: int, cap: int) -> None:
        super().__init__(
            "body {} exceeds cap {}".format(length, cap)
        )
        self.length = length
        self.cap = cap


class Handler(BaseHTTPRequestHandler):
    """Per-request handler. Configuration is class-level (set by cli.serve)."""

    # Class-level config — set by cli before serve() runs.
    max_body_size: int = 50 * 1024 * 1024
    quiet: bool = False  # tests set True to silence stderr noise

    # -- dispatch ---------------------------------------------------------

    def do_GET(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PATCH(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()

    def _dispatch(self) -> None:
        method = self.command.upper()
        parsed = urlparse(self.path)
        path = parsed.path

        # Find a route. We also collect all methods that match the path
        # so 405 can emit a useful Allow header.
        matched: Optional[Tuple[Handler, Dict[str, str]]] = None
        path_matches_any: bool = False
        path_methods: List[str] = []
        for m, pat, h in routes:
            m_pat = pat.match(path)
            if not m_pat:
                continue
            path_matches_any = True
            path_methods.append(m)
            if m == method and matched is None:
                matched = (h, m_pat.groupdict())

        if matched is None:
            if path_matches_any:
                self._respond(
                    405,
                    b"method not allowed\n",
                    {"Allow": ", ".join(sorted(set(path_methods)))},
                )
            else:
                self._respond(
                    404,
                    b"not found\n",
                    {"Content-Type": "text/plain"},
                )
            return

        handler, params = matched

        # Read body (with size cap).
        try:
            body = self._read_body()
        except BodyTooLarge as e:
            self._respond(
                413,
                "body too large: {} > {}\n".format(e.length, e.cap).encode("utf-8"),
                {"Content-Type": "text/plain"},
            )
            return

        # Dispatch.
        try:
            status, resp_body, headers = handler(self, params, body)
        except Exception as exc:
            # Don't leak internals; log to stderr; 500 to client.
            sys.stderr.write(
                "agent-html-drop: handler error for {} {}: {!r}\n".format(method, path, exc)
            )
            self._respond(
                500,
                b"internal error\n",
                {"Content-Type": "text/plain"},
            )
            return

        # A handler may stream the body itself (e.g. GET /files/<name>) by
        # sending its own headers + chunks and returning STREAMED as the
        # body — skip the default bytes response in that case.
        if resp_body is STREAMED:
            return
        self._respond(status, resp_body, headers)

    # -- body -------------------------------------------------------------

    def _read_body(self) -> bytes:
        """Read the request body up to ``max_body_size``. Raises ``BodyTooLarge``."""
        length_str = self.headers.get("Content-Length", "0")
        try:
            length = int(length_str)
        except ValueError:
            length = 0
        if length > self.max_body_size:
            raise BodyTooLarge(length, self.max_body_size)
        if length <= 0:
            return b""
        return self.rfile.read(length)

    # -- response ---------------------------------------------------------

    def _respond(
        self,
        status: int,
        body: bytes,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.send_response(status)
        hdrs = dict(headers or {})
        hdrs.setdefault("Content-Length", str(len(body)))
        # Tell well-behaved clients we don't speak anything other than GET/POST/DELETE.
        hdrs.setdefault("Allow", "GET, POST, PATCH, DELETE")
        for k, v in hdrs.items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def send_file(self, path: str, content_type: str) -> None:
        """Stream a file to the client in chunks (used by /files/<name>).

        Sends 200 + Content-Type + Content-Length (from stat), then writes
        the body in 64 KiB chunks so a large HTML file never has to be
        loaded whole into memory. The caller then returns ``STREAMED`` so
        the dispatcher skips the default bytes-body response.
        """
        size = os.stat(path).st_size
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)

    # -- logging ----------------------------------------------------------

    def log_message(self, format: str, *args) -> None:  # noqa: A002 — stdlib name
        """Stdlib's noisy single-line access log; gated by ``quiet``."""
        if self.quiet:
            return
        sys.stderr.write(
            "{} - {}\n".format(self.log_date_time_string(), format % args)
        )


# --- entry point ------------------------------------------------------------

class _Server(ThreadingHTTPServer):
    """``ThreadingHTTPServer`` with a real accept backlog.

    stdlib defaults ``request_queue_size = 5``, smaller than a browser's
    per-origin connection pool (6+). One page load fires a burst of 4+
    requests (``/``, ``style.css``, ``app.js``, ``/api/files``); SYNs beyond
    the backlog get dropped and the client sees ``ERR_CONNECTION_TIMED_OUT``.
    """

    request_queue_size = 128


def make_server(host: str, port: int, *, quiet: bool = False) -> ThreadingHTTPServer:
    """Build a ``ThreadingHTTPServer`` bound to ``(host, port)``.

    Use ``port=0`` to let the kernel assign an ephemeral port
    (essential for tests — never grab 8765 in CI).
    """
    srv = _Server((host, port), Handler)
    srv.RequestHandlerClass.quiet = quiet
    return srv


def install_signal_shutdown(server: ThreadingHTTPServer, *, grace_seconds: int = 5) -> None:
    """Wire SIGINT/SIGTERM to ``server.shutdown()`` for graceful exit.

    A SIGALRM watchdog (default 5s) hard-exits if ``serve_forever`` hasn't
    returned by then. This guards against Python 3.12+ ``shutdown()`` not
    waking ``serve_forever`` immediately on every platform.

    The watchdog arms ONLY once a shutdown signal fires — never at install
    time. (Arming eagerly caused the daemon to self-exit 5s after start,
    which made Docker ``restart: unless-stopped`` loop forever.) Call
    ``cancel_shutdown_watchdog()`` from the main thread once
    ``serve_forever`` returns cleanly, so a stale alarm can't fire later.
    """
    def _shutdown(*_):
        # shutdown() must run off the main thread (signal-handler thread is
        # the main thread); calling it here would self-deadlock against
        # serve_forever. Arm the watchdog at the same moment so a hung
        # shutdown still has an escape hatch.
        signal.alarm(grace_seconds)
        threading.Thread(target=server.shutdown, daemon=True).start()

    def _hard_exit(*_):
        # Best-effort: close the listening socket so serve_forever wakes,
        # then exit. If it still hangs, os._exit is the escape hatch.
        try:
            server.server_close()
        finally:
            os._exit(0)  # noqa: hard exit by design after grace

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGALRM, _hard_exit)


def cancel_shutdown_watchdog() -> None:
    """Cancel any pending SIGALRM. Call from the main thread after
    ``serve_forever`` returns cleanly, so the watchdog can only fire when
    a real shutdown is in progress.
    """
    signal.alarm(0)