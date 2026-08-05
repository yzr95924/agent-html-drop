"""Annotations on HTML files: <name>.meta sidecar JSON files.

Per design §7.2:
  - One `<name>.meta` file per `<name>.html` in docroot.
  - Atomic write via .tmp + os.replace (same rule as storage.upload).
  - ULID ids (no external dep — base32 of os.urandom).
  - author = "tk_" + sha256(token)[:8], irreversible, same token → same author.
  - quote normalization for iframe substring matching: collapse whitespace only.
"""
import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


# 26-char Crockford-base32-ish ULID: 10-char time (48-bit sec → 10 base32-ish
# chars from [0-9A-Z]) + 16-char random. Use uppercase A-Z0-9 minus I/L/O/U
# to keep it URL-safe and OCR-friendly.
_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_LEN_TIME = 10
_ULID_LEN_RANDOM = 16

_META_VERSION = 1


def ulid_new() -> str:
    """Return a fresh 26-char ULID-ish id, lexicographically sortable by time."""
    now_ms = int(time.time() * 1000)
    time_part = ""
    for _ in range(_ULID_LEN_TIME):
        time_part = _ULID_ALPHABET[now_ms % 32] + time_part
        now_ms //= 32
    rand_bytes = secrets.token_bytes(16)
    rand_part = "".join(_ULID_ALPHABET[b % 32] for b in rand_bytes)
    return time_part + rand_part


def author_of_token(token: str) -> str:
    """Return a stable, irreversible identifier for this token."""
    h = hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]
    return "tk_" + h


_WS_RE = re.compile(r"\s+")


def normalize_quote(s: str) -> str:
    """Collapse whitespace runs to single space, strip ends.

    Preserves Chinese/CJK punctuation and word characters; only ASCII
    whitespace runs are folded. This lets iframe text matching tolerate
    HTML re-rendering that may collapse newlines.
    """
    return _WS_RE.sub(" ", s).strip()


def _empty_doc() -> Dict[str, Any]:
    return {"version": _META_VERSION, "annotations": []}


def load(docroot: Path, name: str) -> Dict[str, Any]:
    """Read `<name>.meta` from docroot. Returns empty doc if file missing."""
    p = docroot / (name + ".meta")
    if not p.exists():
        return _empty_doc()
    try:
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        # Corrupt meta → treat as empty (do NOT raise; agents may rely on
        # graceful read even after partial writes).
        return _empty_doc()
    if not isinstance(data, dict):
        return _empty_doc()
    if "annotations" not in data or not isinstance(data["annotations"], list):
        data["annotations"] = []
    if "version" not in data:
        data["version"] = _META_VERSION
    return data


def save(docroot: Path, name: str, doc: Dict[str, Any]) -> None:
    """Atomic write of doc to `<name>.meta`."""
    p = docroot / (name + ".meta")
    tmp = p.with_name(p.name + ".tmp")
    payload = json.dumps(doc, ensure_ascii=False, sort_keys=True).encode("utf-8")
    try:
        with open(tmp, "wb") as f:
            f.write(payload)
        os.chmod(tmp, 0o644)
        os.replace(tmp, p)
    except BaseException:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


_MAX_QUOTE_LEN = 200
_MAX_COMMENT_LEN = 2000


def add(
    docroot: Path,
    name: str,
    quote: str,
    comment: str,
    token: str,
    *,
    max_quote_len: int = _MAX_QUOTE_LEN,
    max_comment_len: int = _MAX_COMMENT_LEN,
) -> Dict[str, Any]:
    """Append a new annotation. Atomic write of `<name>.meta`."""
    if not isinstance(quote, str) or not isinstance(comment, str):
        raise TypeError("quote and comment must be strings")
    if len(comment) > max_comment_len:
        raise ValueError(
            "comment length {} exceeds max {}".format(len(comment), max_comment_len)
        )
    if not isinstance(token, str) or not token:
        raise ValueError("token must be a non-empty string")
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a non-empty string")

    # Truncate quote silently (caps iframe match ambiguity).
    q = quote[:max_quote_len]
    entry = {
        "id": ulid_new(),
        "quote": q,
        "comment": comment,
        "author": author_of_token(token),
        "ts": int(time.time()),
    }
    doc = load(docroot, name)
    doc["annotations"].append(entry)
    save(docroot, name, doc)
    return entry


def list_for(docroot: Path, name: str) -> List[Dict[str, Any]]:
    """Return all annotations for `<name>`, oldest first."""
    return list(load(docroot, name)["annotations"])


def count(docroot: Path, name: str) -> int:
    """Number of annotations for `<name>` (0 if no meta file)."""
    return len(load(docroot, name)["annotations"])


def get(docroot: Path, name: str, id: str) -> Optional[Dict[str, Any]]:  # noqa: A002 — design uses `id`
    for entry in load(docroot, name)["annotations"]:
        if entry.get("id") == id:
            return entry
    return None


def delete(docroot: Path, name: str, id: str, token: str) -> bool:  # noqa: A002
    """Delete annotation by id, but only if author matches token's hash.

    Returns True if deleted, False if id not found OR author mismatch
    (indistinguishable to caller — caller decides whether to surface as 404
    vs 403; we return False in both cases per spec §8).
    """
    if not isinstance(token, str) or not token:
        return False
    doc = load(docroot, name)
    target_author = author_of_token(token)
    new_entries = []
    removed = False
    for entry in doc["annotations"]:
        if entry.get("id") == id and entry.get("author") == target_author:
            removed = True
            continue
        new_entries.append(entry)
    if removed:
        doc["annotations"] = new_entries
        save(docroot, name, doc)
    return removed


def delete_all_for(docroot: Path, name: str) -> bool:
    """Delete the entire ``<name>.meta`` sidecar. Returns True if it existed.

    Used when an HTML file is deleted (``DELETE /api/files/<name>`` and MCP
    ``delete_html``) so its annotations don't outlive the document as
    orphans. Idempotent: a missing ``.meta`` returns False, not an error —
    mirroring ``storage.delete``'s "missing is not an error" contract, so
    callers can map the result to 404-or-ignore uniformly.

    Only the ``.meta`` sidecar is touched. Deleting the HTML itself is
    ``storage.delete``'s job; keeping the two separate preserves the
    one-way dependency (``_legacy_storage`` does not import annotations).
    Like ``load``/``save``, the name is trusted to already be validated by
    the caller — the ``.meta`` filename is ``name + ".meta"`` and name has
    passed the upload-name regex upstream.
    """
    p = docroot / (name + ".meta")
    if not p.exists():
        return False
    try:
        p.unlink()
    except OSError:
        return False
    return True
