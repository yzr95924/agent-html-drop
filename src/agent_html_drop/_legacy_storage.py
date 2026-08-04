"""docroot file CRUD: atomic writes, name validation, path-traversal guard.

Stateless module — callers pass ``docroot`` / ``max_file_size`` per
call. Keeps storage testable without a daemon, and keeps the dependency
direction one-way (mcp/api depend on storage, never the other way).

Filenames are validated against
``^[A-Za-z0-9._-]+\\.html$`` (case-insensitive ``.html`` suffix) — see
``validate_name``. Length cap 200 chars (per design §4). Path traversal
is double-defended: regex blocks ``/`` and ``..``, plus a ``resolve()``-
based check catches symlinks pointing outside the docroot.
"""
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Tuple


# Filename policy (matches docs/design.md §4).
# IGNORECASE: `.html`, `.HTML`, `.Html` all valid. Character class
# `[A-Za-z0-9._-]` already covers the body.
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.html$", re.IGNORECASE)
_MAX_NAME_LEN = 200

# `<title>...</title>` — greedy across the body, allowing newlines.
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)


class StorageError(Exception):
    """Base for storage-level errors."""


class InvalidName(StorageError):
    """Filename violates the name regex or length cap."""


class Conflict(StorageError):
    """File already exists; pass force=True to overwrite."""


class TooLarge(StorageError):
    """Content exceeds max_file_size."""


class Sha256Mismatch(StorageError):
    """Body hash doesn't match the Content-SHA256 header the client sent."""


class DocrootUnwritable(StorageError):
    """The docroot does not exist, is not a directory, or is not writable."""


class NotFound(StorageError):
    """File does not exist (delete / read)."""


@dataclass
class FileInfo:
    name: str
    size: int
    mtime: int          # unix seconds
    title: Optional[str]


# Storage exception class → (HTTP status, wire error code). Single source
# of truth for how storage exceptions surface on both /api (HTTP) and
# /mcp (JSON-RPC tool envelope).  ``api._storage_error`` reads it via
# the type table; ``mcp_handler`` reads ``http_status()`` to pick the
# wire code and reuses the same string for the envelope's ``error``
# field so the two surfaces never drift.
_STORAGE_HTTP: Dict[type, Tuple[int, str]] = {
    InvalidName: (400, "invalid_name"),
    Conflict: (409, "conflict"),
    TooLarge: (413, "too_large"),
    Sha256Mismatch: (400, "sha256_mismatch"),
    NotFound: (404, "not_found"),
    DocrootUnwritable: (500, "docroot_unwritable"),
}


def http_status(exc: "StorageError") -> Tuple[int, str]:
    """Return ``(http_status, error_code)`` for a storage exception.

    Falls back to ``(500, "storage_error")`` for unknown subclasses —
    forward-compatible if new exceptions are added later without being
    registered here.
    """
    return _STORAGE_HTTP.get(type(exc), (500, "storage_error"))


def validate_name(name: Any) -> None:
    """Raise ``InvalidName`` if ``name`` is not a legal upload filename.

    Legal: ``^[A-Za-z0-9._-]+\\.html$`` (case-insensitive suffix), length
    <= 200 chars, non-empty string.
    """
    if not isinstance(name, str):
        raise InvalidName("name must be a string, got: {!r}".format(type(name)))
    if not name:
        raise InvalidName("name must be a non-empty string")
    if len(name) > _MAX_NAME_LEN:
        raise InvalidName(
            "name length {} exceeds max {}".format(len(name), _MAX_NAME_LEN)
        )
    if not _NAME_RE.match(name):
        raise InvalidName(
            "name {!r} does not match {}".format(name, _NAME_RE.pattern)
        )


def _is_relative_to(p: Path, base: Path) -> bool:
    """``Path.is_relative_to`` shim for Python <3.9 (we target 3.7+)."""
    try:
        p.relative_to(base)
        return True
    except ValueError:
        return False


def _resolve_within(docroot: Path, name: str) -> Path:
    """Resolve ``docroot / name`` and confirm the result is inside docroot.

    Defense-in-depth: regex blocks ``/`` and ``..``, but symlinks inside
    docroot could still point outside — ``resolve()`` follows them and
    the relative check catches it.
    """
    if not docroot.exists() or not docroot.is_dir():
        raise DocrootUnwritable(
            "docroot does not exist or is not a directory: {}".format(docroot)
        )
    if not os.access(str(docroot), os.W_OK):
        raise DocrootUnwritable("docroot is not writable: {}".format(docroot))
    base = docroot.resolve()
    target = (docroot / name).resolve()
    if not _is_relative_to(target, base):
        raise InvalidName(
            "name {!r} resolves outside docroot: {}".format(name, target)
        )
    return target


def _existing_case_insensitive(docroot: Path, name: str) -> Optional[Path]:
    """Return any file under docroot whose name matches ``name`` ignoring case.

    Lets us treat ``DESIGN.HTML`` and ``design.html`` as the same logical
    file across case-sensitive (Linux ext4) and case-insensitive (macOS
    HFS+/APFS) filesystems. Returns the on-disk entry (preserving the
    first-upload's casing) or None.
    """
    needle = name.lower()
    for entry in docroot.iterdir():
        if entry.is_file() and entry.name.lower() == needle:
            return entry
    return None


def upload(
    docroot: Path,
    name: str,
    content: str,
    *,
    max_size: int,
    force: bool = False,
) -> FileInfo:
    """Atomic write of ``content`` (UTF-8) to ``docroot/name``.

    Returns ``FileInfo`` for the newly written file. Raises:

      - ``InvalidName``         bad filename
      - ``DocrootUnwritable``   docroot missing / not a dir / not writable
      - ``TooLarge``            encoded content exceeds max_size
      - ``Conflict``            file exists and force=False

    Atomicity: writes ``<name>.tmp``, chmods 0644, ``os.replace`` to the
    final path. On any failure inside the write, the tmp is cleaned up.
    """
    validate_name(name)

    content_bytes = content.encode("utf-8")
    if len(content_bytes) > max_size:
        raise TooLarge(
            "content size {} exceeds max_file_size {}".format(
                len(content_bytes), max_size
            )
        )

    target = _resolve_within(docroot, name)

    # Case-insensitive conflict check: DESIGN.HTML and design.html are
    # the same logical file. If a case-variant exists, we'll overwrite
    # that one (preserving its on-disk casing) instead of writing a
    # second file with a different case.
    existing = _existing_case_insensitive(docroot, name)
    if existing is not None and not force:
        raise Conflict(
            "file exists (case-insensitive match: {!r}); pass force=True to overwrite".format(existing.name)
        )
    write_target = existing if existing is not None else target

    tmp = write_target.with_name(write_target.name + ".tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(content_bytes)
        os.chmod(tmp, 0o644)
        os.replace(tmp, write_target)
    except BaseException:
        # Don't leave a half-written .tmp behind.
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise

    st = write_target.stat()
    return FileInfo(
        name=write_target.name,
        size=st.st_size,
        mtime=int(st.st_mtime),
        title=_parse_title(content),
    )


def upload_stream(
    docroot: Path,
    name: str,
    source: BinaryIO,
    *,
    max_size: int,
    content_length: Optional[int] = None,
    force: bool = False,
    expected_sha256: Optional[str] = None,
    chunk_size: int = 65536,
) -> FileInfo:
    """Atomic streaming write from ``source`` to ``docroot/name``.

    Reads ``source`` in ``chunk_size`` byte chunks, writes each chunk to
    a sibling ``.tmp``, hashes incrementally, and atomically replaces the
    target on success. The full payload is never held in memory — this
    is the path used by the PUT /files/<name> HTTP route so a 50 MiB
    HTML upload doesn't buffer whole into RAM before hitting disk.

    ``content_length`` (when provided) bounds the read: the function
    stops once exactly that many bytes have been consumed from
    ``source``. This matters because, for sockets, EOF (zero-byte
    ``read``) only fires when the peer closes the connection — if we
    read past the declared length, the second ``read`` would block
    until the client times out. Callers that know the body's length
    (HTTP handlers reading ``Content-Length``) MUST pass it.

    Mirrors :func:`upload`'s semantics where applicable:

      - name validation, conflict (case-insensitive), docroot writability
      - 0644 mode on the final file
      - ``.tmp`` cleaned up on every error path (so retries don't pile up)

    Adds:

      - mid-stream ``max_size`` enforcement (raises ``TooLarge`` once the
        running total exceeds the cap, not after the full upload)
      - optional ``expected_sha256`` (hex, lower/upper ok) — when
        provided, the body hash must match; mismatch raises
        ``Sha256Mismatch`` and deletes the tmpfile. Used by the PUT
        handler when the client passes ``Content-SHA256`` for end-to-end
        integrity.

    Returns ``FileInfo`` for the newly written file.
    """
    validate_name(name)
    target = _resolve_within(docroot, name)

    existing = _existing_case_insensitive(docroot, name)
    if existing is not None and not force:
        raise Conflict(
            "file exists (case-insensitive match: {!r}); pass force=True to overwrite".format(existing.name)
        )
    write_target = existing if existing is not None else target

    tmp = write_target.with_name(write_target.name + ".tmp")
    hasher = hashlib.sha256()
    bytes_written = 0
    try:
        with open(tmp, "wb") as out:
            while True:
                # Bound the read: respect content_length when known so
                # we don't sit blocked on the socket waiting for an EOF
                # that won't come until the peer closes (which on
                # HTTP/1.1 keep-alive only happens after we reply).
                want = chunk_size
                if content_length is not None:
                    remaining = content_length - bytes_written
                    if remaining <= 0:
                        break
                    if want > remaining:
                        want = remaining
                chunk = source.read(want)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_size:
                    raise TooLarge(
                        "content exceeds max_file_size {}".format(max_size)
                    )
                out.write(chunk)
                hasher.update(chunk)
        os.chmod(tmp, 0o644)
        # Final check: if the caller declared a content_length, the
        # tmpfile must contain exactly that many bytes (catches a
        # client that short-sent the body).
        actual = tmp.stat().st_size
        if content_length is not None and actual != content_length:
            raise TooLarge(
                "body short: got {} bytes, declared {}".format(actual, content_length)
            )
        if expected_sha256 is not None:
            actual_hex = hasher.hexdigest()
            if actual_hex.lower() != expected_sha256.lower():
                raise Sha256Mismatch(
                    "sha256 mismatch: expected={}, actual={}".format(
                        expected_sha256, actual_hex
                    )
                )
        os.replace(tmp, write_target)
    except BaseException:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise

    st = write_target.stat()
    # Title parse is best-effort on the streamed bytes; only meaningful
    # if the caller hands us a seekable TextIO. We don't try to decode
    # raw binary here — list_html does that lazily.
    return FileInfo(
        name=write_target.name,
        size=st.st_size,
        mtime=int(st.st_mtime),
        title=None,
    )


def list_files(docroot: Path) -> List[FileInfo]:
    """List all ``*.html`` files directly under ``docroot``.

    Symlinks and non-html files are ignored. Title parsing is best-effort
    (binary or non-UTF-8 files yield ``title=None``).
    """
    if not docroot.exists() or not docroot.is_dir():
        return []

    out: List[FileInfo] = []
    for entry in sorted(docroot.iterdir(), key=lambda p: p.name):
        if not entry.is_file():
            continue
        # Only consider names that look like our naming convention; skip
        # any other files the user may have placed here.
        if not _NAME_RE.match(entry.name):
            continue
        st = entry.stat()
        title = None
        try:
            title = _parse_title(entry.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):
            # Binary or unreadable — leave title as None.
            pass
        out.append(
            FileInfo(
                name=entry.name,
                size=st.st_size,
                mtime=int(st.st_mtime),
                title=title,
            )
        )
    return out


def delete(docroot: Path, name: str) -> bool:
    """Delete ``docroot/name``. Returns True on success.

    Raises ``InvalidName`` for bad names, ``DocrootUnwritable`` if
    docroot is unusable. Missing file is **not** an error here — returns
    False — so the caller can decide between 404 and idempotent.
    """
    validate_name(name)
    target = _resolve_within(docroot, name)
    if not target.exists():
        return False
    target.unlink()
    return True


# 64 KiB chunk — same default as ``upload_stream`` so callers don't pick
# conflicting sizes between hash and write paths.
_SHA256_CHUNK = 65536


def sha256_file(path: Path, *, max_size: Optional[int] = None) -> str:
    """Stream ``path`` through SHA256 in fixed chunks.

    ``max_size`` (optional) aborts with ``TooLarge`` once bytes-read
    exceeds it — guards against a corrupt oversized file pinning the
    worker during MCP verification.
    """
    h = hashlib.sha256()
    bytes_read = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_SHA256_CHUNK)
            if not chunk:
                break
            h.update(chunk)
            bytes_read += len(chunk)
            if max_size is not None and bytes_read > max_size:
                raise TooLarge(
                    "file exceeds max_size {}".format(max_size)
                )
    return h.hexdigest()


def _parse_title(content: str) -> Optional[str]:
    """Best-effort ``<title>...</title>`` extraction. Returns None on miss."""
    m = _TITLE_RE.search(content)
    if not m:
        return None
    title = m.group(1).strip()
    return title or None