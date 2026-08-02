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
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional


# Filename policy (matches agent-html-drop-design.md §4).
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


def _parse_title(content: str) -> Optional[str]:
    """Best-effort ``<title>...</title>`` extraction. Returns None on miss."""
    m = _TITLE_RE.search(content)
    if not m:
        return None
    title = m.group(1).strip()
    return title or None