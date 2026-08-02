# agent-html-drop Annotations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend agent-html-drop with browser-driven HTML annotations — sidebar `<name>.meta` JSON storage, iframe `<mark>` highlights, agent-side read/delete via MCP. Hard boundary: agent writes `.html` (Bearer), browser writes `.html.meta` (session cookie), the two paths never overlap.

**Architecture:**

- `storage/annotations.py` — new module: load/save/delete/list/count annotations on a `<name>.meta` sidecar JSON, atomic write via `.tmp + os.replace`, ULID ids, author = `tk_<sha256(token)[:8]>`
- `api.py` — extend with `POST /api/auth` (token → 30-min cookie), `GET /api/files/<name>/annotations` (public), `POST /api/files/<name>/annotations` (cookie + CSRF), `PATCH/DELETE /api/files/<name>/annotations/<id>` (cookie + CSRF + author match). Extend `list_files` to include `annotation_count`.
- `mcp_handler.py` — add two tools: `list_annotations(name)` and `delete_annotation(name, id)`. No `add_annotation` for agents (N11).
- `ui/{index.html,style.css,app.js}` — header "批注(需 token)" button → modal `<dialog>` → state machine `mode: 'read' | 'anno'`. In anno mode: iframe `getSelection()` → quote, post to backend, inject `<mark data-anno-id>` into iframe DOM on reload.
- `nginx.conf.template` — add `proxy_cookie_path ... SameSite=Lax` line + `limit_req zone=auth limit=10r/s` directive for `/api/auth` and annotation write paths.

**Tech Stack:** Python 3.7+ stdlib only (`http.server`, `secrets`, `hmac`, `json`, `pathlib`, `hashlib`, `os`, `urllib.parse`, `re`, `string` for ULID alphabet). No new runtime deps. `tomli>=1.1` already pulled for V1.

**Companion docs:** Design — [`../design.md`](../../design.md) (V1 + 批注扩展, sections §1/§2/§3/§4/§5/§7.2/§7.3/§8/§9.3/§10/§13). Active living doc — [`../tasks.md`](../../tasks.md) (V1 已验收 T1–T12; T13–T18 = this plan).

## Global Constraints

Verbatim from the spec and `AGENTS.md`. Every task's requirements implicitly include these.

- **Python 3.7+ compat.** No `dict[str,str]`, walrus, or `match`. `from typing import Dict, List, Optional, Tuple`.
- **stdlib only at runtime.** `tomli>=1.1` only when Python <3.11. No new third-party deps.
- **Atomic file writes.** `.tmp + os.replace`. Cleanup on failure.
- **Test isolation.** Tests must NEVER touch `~/.config/agent-html-drop/` or real docroot. `tests/conftest.py` autouse fixture already in place; reuse it.
- **Unknown field passthrough.** Annotation metadata must preserve any unknown keys (e.g. future `reply_to`, `resolved`).
- **Unknown config passthrough.** `Config.extra_*` already extends existing config layer — never drop user fields.
- **Driver-style symmetric boundaries.** Browser side and agent side use disjoint auth (`session cookie` vs `Bearer`), disjoint namespaces (`<name>.meta` vs `<name>.html`).
- **iframe sandbox = `allow-same-origin`** (NOT full empty). Permits same-origin DOM access for `<mark>` injection; **must NOT** include `allow-scripts` (deny HTML-side JS like Mermaid/MathJax from executing in the preview frame).
- **CSRF double defense.** `SameSite=Lax` cookie + server-side `Origin` header check (must match `https://<Host>` if present).
- **nginx `limit_req`.** `zone=auth limit=10r/s burst=20 nodelay` for `/api/auth` and all annotation write paths.
- **Logging.** No token plaintext, no session cookie plaintext, no annotation comment text in logs.
- **Commit per task.** Each task ends with a `git commit`. Conventional commits (`feat:` / `test:` / `docs:` / `chore:`).
- **Coverage target.** Maintain ≥ 90% line coverage on `agent_html_drop` (already at 92% per V1).

## File Layout

| File | Responsibility |
| --- | --- |
| `src/agent_html_drop/storage/annotations.py` (new) | `<name>.meta` sidecar CRUD; ULID; author hash; atomic write |
| `src/agent_html_drop/storage/__init__.py` (new) | Re-export `storage.annotations` so `storage.list_files` etc. keep working |
| `src/agent_html_drop/auth_anno.py` (new) | Token → `author` hash; cookie session sign/verify; Origin header check |
| `src/agent_html_drop/api.py` (modify) | `/api/auth`; annotation REST CRUD; extend `list_files` with `annotation_count` |
| `src/agent_html_drop/mcp_handler.py` (modify) | `list_annotations` + `delete_annotation` tool impls + schemas |
| `src/agent_html_drop/ui/index.html` (modify) | Header anno-mode button; modal `<dialog>` for token; annotation sidebar |
| `src/agent_html_drop/ui/style.css` (modify) | Anno button styles; modal styles; sidebar styles; `<mark>` highlight |
| `src/agent_html_drop/ui/app.js` (modify) | Mode state machine; token submit; iframe selection → quote; `<mark>` injection; annotation sidebar render |
| `src/agent_html_drop/assets/nginx.conf.template` (modify) | `proxy_cookie_path` line; `limit_req` zone + apply |
| `tests/test_agent_html_drop_annotations_storage.py` (new) | `storage/annotations.py` tests |
| `tests/test_agent_html_drop_auth_anno.py` (new) | `auth_anno.py` tests |
| `tests/test_agent_html_drop_annotations_api.py` (new) | Annotation REST endpoint tests + `/api/auth` |
| `tests/test_agent_html_drop_annotations_mcp.py` (new) | MCP `list_annotations` + `delete_annotation` |
| `tests/test_agent_html_drop_annotations_ui.py` (new) | UI strings + DOM shape assertions (no JS execution in tests) |
| `src/agent_html_drop/README.md` (modify) | Add 批注 quick-start; add nginx SameSite/LimitReq snippet |
| `docs/tasks.md` (already updated) | T13–T18 status flows here |
| `scripts/agent-html-drop.sh` (no change) | Daemon lifecycle script unchanged |

---

## Task 1: `storage/annotations.py` skeleton — ULID + author hash

**Files:**
- Create: `src/agent_html_drop/storage/__init__.py`
- Create: `src/agent_html_drop/storage/annotations.py`
- Test: `tests/test_agent_html_drop_annotations_storage.py`

**Interfaces:**
- Consumes: `pathlib.Path`, `secrets`, `hashlib`, `json`
- Produces:
  - `ulid_new() -> str` — 26-char ULID-ish id
  - `author_of_token(token: str) -> str` — `"tk_" + sha256(token)[:8]`
  - `normalize_quote(s: str) -> str` — collapse whitespace for iframe match

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_html_drop_annotations_storage.py
"""Tests for agent_html_drop.storage.annotations — ULID, author hash, quote normalize."""
from agent_html_drop.storage.annotations import ulid_new, author_of_token, normalize_quote


def test_ulid_new_is_26_chars():
    assert len(ulid_new()) == 26


def test_ulid_new_is_uppercase_alphanumeric():
    import re
    assert re.match(r"^[0-9A-Z]{26}$", ulid_new())


def test_ulid_new_is_unique():
    seen = {ulid_new() for _ in range(1000)}
    assert len(seen) == 1000


def test_author_of_token_is_tk_prefix():
    assert author_of_token("any").startswith("tk_")


def test_author_of_token_is_deterministic():
    assert author_of_token("hello") == author_of_token("hello")


def test_author_of_token_is_irreversible_8_hex():
    a = author_of_token("hello")
    suffix = a[len("tk_"):]
    assert len(suffix) == 8
    assert all(c in "0123456789abcdef" for c in suffix)


def test_author_differs_per_token():
    assert author_of_token("a") != author_of_token("b")


def test_normalize_quote_collapses_whitespace():
    assert normalize_quote("  hello\n\n world  ") == "hello world"


def test_normalize_quote_preserves_cn_punct():
    # Chinese full-width punctuation must NOT be touched.
    assert normalize_quote("你好，世界") == "你好，世界"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_html_drop_annotations_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_html_drop.storage'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/agent_html_drop/storage/__init__.py
"""Storage layer: file CRUD + annotations."""
from agent_html_drop.storage import annotations

__all__ = ["annotations"]
```

```python
# src/agent_html_drop/storage/annotations.py
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
import string
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
    rand_bytes = secrets.token_bytes(10)
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
    except (OSError, json.JSONDecodeError):
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_html_drop_annotations_storage.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/agent_html_drop/storage/ tests/test_agent_html_drop_annotations_storage.py
git commit -m "feat(agent-html-drop): storage/annotations skeleton — ULID, author hash, normalize_quote"
```

---

## Task 2: `storage/annotations.py` — CRUD on annotations

**Files:**
- Modify: `src/agent_html_drop/storage/annotations.py:90-end`
- Test: `tests/test_agent_html_drop_annotations_storage.py`

**Interfaces:**
- Produces (additions to `annotations` module):
  - `add(docroot, name, quote, comment, token, *, max_quote_len=200, max_comment_len=2000) -> Dict[str, Any]` — returns the new entry
  - `delete(docroot, name, id, token) -> bool` — True if removed; False if not found or not author
  - `list_for(docroot, name) -> List[Dict[str, Any]]`
  - `count(docroot, name) -> int`
  - `get(docroot, name, id) -> Optional[Dict[str, Any]]`

- [ ] **Step 1: Write failing tests (append to existing test file)**

```python
# Append to tests/test_agent_html_drop_annotations_storage.py
import json
from pathlib import Path

import pytest

from agent_html_drop.storage.annotations import (
    add, delete, list_for, count, get, load,
)


@pytest.fixture
def docroot(tmp_path):
    p = tmp_path / "docroot"
    p.mkdir()
    return p


def test_add_writes_meta_file(docroot):
    entry = add(docroot, "design.html", "sudo mkdir", "改成用户级", "tok-abc")
    meta = docroot / "design.html.meta"
    assert meta.exists()
    assert meta.stat().st_mode & 0o777 == 0o644
    assert entry["quote"] == "sudo mkdir"
    assert entry["comment"] == "改成用户级"
    assert entry["author"] == author_of_token("tok-abc")
    assert "id" in entry and len(entry["id"]) == 26
    assert "ts" in entry


def test_add_appends_to_existing(docroot):
    add(docroot, "design.html", "first", "c1", "t1")
    add(docroot, "design.html", "second", "c2", "t2")
    entries = list_for(docroot, "design.html")
    assert len(entries) == 2
    assert [e["quote"] for e in entries] == ["first", "second"]


def test_add_truncates_oversize_quote(docroot):
    long_q = "x" * 500
    entry = add(docroot, "design.html", long_q, "c", "t")
    assert len(entry["quote"]) == 200  # truncated


def test_add_rejects_oversize_comment(docroot):
    import pytest
    with pytest.raises(ValueError):
        add(docroot, "design.html", "q", "x" * 2001, "t")


def test_list_for_empty_returns_empty_list(docroot):
    assert list_for(docroot, "missing.html") == []


def test_count_matches_list_len(docroot):
    add(docroot, "design.html", "a", "x", "t")
    add(docroot, "design.html", "b", "y", "t")
    assert count(docroot, "design.html") == 2


def test_count_missing_file_is_zero(docroot):
    assert count(docroot, "missing.html") == 0


def test_delete_by_author_succeeds(docroot):
    entry = add(docroot, "design.html", "q", "c", "tok-1")
    assert delete(docroot, "design.html", entry["id"], "tok-1") is True
    assert count(docroot, "design.html") == 0


def test_delete_by_other_token_returns_false(docroot):
    entry = add(docroot, "design.html", "q", "c", "tok-1")
    assert delete(docroot, "design.html", entry["id"], "tok-2") is False
    assert count(docroot, "design.html") == 1  # unchanged


def test_delete_missing_id_returns_false(docroot):
    add(docroot, "design.html", "q", "c", "t")
    assert delete(docroot, "design.html", "NONEXISTENT", "t") is False


def test_delete_when_no_meta_returns_false(docroot):
    assert delete(docroot, "missing.html", "any", "t") is False


def test_get_returns_entry(docroot):
    entry = add(docroot, "design.html", "q", "c", "t")
    got = get(docroot, "design.html", entry["id"])
    assert got["quote"] == "q"


def test_get_missing_returns_none(docroot):
    assert get(docroot, "design.html", "anything") is None


def test_save_atomic_no_leftover_tmp(docroot):
    add(docroot, "design.html", "q", "c", "t")
    assert not (docroot / "design.html.meta.tmp").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_html_drop_annotations_storage.py -v -k "add or delete or list_for or count or get"`
Expected: FAIL with `ImportError` or `AttributeError`.

- [ ] **Step 3: Add implementation to `annotations.py`**

Append to `src/agent_html_drop/storage/annotations.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_html_drop_annotations_storage.py -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_html_drop/storage/annotations.py tests/test_agent_html_drop_annotations_storage.py
git commit -m "feat(agent-html-drop): storage/annotations CRUD — add/delete/list/count/get"
```

---

## Task 3: `auth_anno.py` — author hash reuse + cookie sign/verify

**Files:**
- Create: `src/agent_html_drop/auth_anno.py`
- Test: `tests/test_agent_html_drop_auth_anno.py`

**Interfaces:**
- Produces:
  - `sign_cookie(token: str, max_age: int = 1800) -> str` — base64 of `<token>|<expires_unix>|<hmac_sha256(secret, "<token>|<expires_unix>")>`
  - `verify_cookie(value: str) -> Optional[str]` — returns the token if valid + not expired; None otherwise
  - `csrf_check(req_host: str, origin_header: Optional[str]) -> bool` — True if Origin absent OR matches `https://<req_host>`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_html_drop_auth_anno.py
"""Tests for agent_html_drop.auth_anno — cookie sign/verify, CSRF Origin check."""
import time

import pytest

from agent_html_drop.auth_anno import (
    sign_cookie, verify_cookie, csrf_check,
    ANNO_COOKIE_NAME, ANNO_COOKIE_MAX_AGE,
)


def test_sign_cookie_format_is_pipe_separated():
    cookie = sign_cookie("tok-abc")
    parts = cookie.split("|")
    assert len(parts) == 3
    assert parts[0] == "tok-abc"


def test_sign_cookie_roundtrip():
    cookie = sign_cookie("tok-abc", max_age=60)
    assert verify_cookie(cookie) == "tok-abc"


def test_verify_cookie_expired_returns_none():
    cookie = sign_cookie("tok-abc", max_age=1)
    time.sleep(1.2)
    assert verify_cookie(cookie) is None


def test_verify_cookie_tampered_returns_none():
    cookie = sign_cookie("tok-abc")
    tampered = cookie[:-2] + "AA"
    assert verify_cookie(tampered) is None


def test_verify_cookie_garbage_returns_none():
    assert verify_cookie("not-a-cookie") is None
    assert verify_cookie("") is None


def test_anno_cookie_name_constant():
    assert ANNO_COOKIE_NAME == "anno_session"


def test_anno_cookie_max_age_is_30_minutes():
    assert ANNO_COOKIE_MAX_AGE == 1800


def test_csrf_check_no_origin_header_passes():
    assert csrf_check("notes.example.com", None) is True


def test_csrf_check_matching_origin_passes():
    assert csrf_check("notes.example.com", "https://notes.example.com") is True


def test_csrf_check_mismatched_origin_fails():
    assert csrf_check("notes.example.com", "https://evil.com") is False
    assert csrf_check("notes.example.com", "http://notes.example.com") is False  # http downgrade


def test_csrf_check_origin_with_port_matches_hostname_only():
    # Strip port from Host header before comparing.
    assert csrf_check("notes.example.com:443", "https://notes.example.com") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_html_drop_auth_anno.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/agent_html_drop/auth_anno.py
"""Browser-side auth for annotation write paths.

Per design §4 / §7.3 / §9.3:
  - Cookie name: anno_session. TTL: 30 min. HttpOnly + Secure + SameSite=Lax.
  - Token held in cookie value (signed), not in user's localStorage.
  - CSRF: SameSite=Lax cookie + server-side Origin header check.
  - The signing secret is per-config (random at init); stored in config.toml.
"""
import base64
import hashlib
import hmac
import os
import time
from typing import Optional


ANNO_COOKIE_NAME = "anno_session"
ANNO_COOKIE_MAX_AGE = 1800  # 30 minutes


def _sign(secret: bytes, payload: str) -> str:
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _get_secret() -> bytes:
    """Derive the signing secret from config.toml auth.token.

    We reuse the existing Bearer token as the seed: same secret authenticates
    both agent MCP calls and browser anno session cookies. This is deliberate
    per spec A3' (single token).
    """
    from agent_html_drop.config import load_config

    cfg = load_config()
    return hashlib.sha256(b"anno-cookie-v1|" + cfg.token.encode("utf-8")).digest()


def sign_cookie(token: str, max_age: int = ANNO_COOKIE_MAX_AGE) -> str:
    """Return a cookie value carrying the token + expiry + HMAC."""
    expires = int(time.time()) + max_age
    payload = "{}|{}".format(token, expires)
    sig = _sign(_get_secret(), payload)
    raw = "{}|{}".format(payload, sig)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def verify_cookie(value: str) -> Optional[str]:
    """Return the token if cookie is valid and not expired, else None."""
    if not value:
        return None
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    parts = raw.split("|")
    if len(parts) != 3:
        return None
    token, expires_s, sig = parts
    expected = _sign(_get_secret(), "{}|{}".format(token, expires_s))
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        expires = int(expires_s)
    except ValueError:
        return None
    if expires < int(time.time()):
        return None
    return token


def csrf_check(req_host: str, origin_header: Optional[str]) -> bool:
    """Allow request if Origin absent (older browsers) OR matches https://<host>.

    `req_host` is the value of the `Host` header (may include :port). We strip
    the port before comparing because Origin never carries the daemon's port.
    """
    if not origin_header:
        return True
    host_only = req_host.split(":", 1)[0]
    expected = "https://" + host_only
    return origin_header == expected


def cookie_set_header(value: str, max_age: int = ANNO_COOKIE_MAX_AGE) -> str:
    """Format the `Set-Cookie` value with all security attrs."""
    return (
        "{name}={value}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age={max_age}"
    ).format(name=ANNO_COOKIE_NAME, value=value, max_age=max_age)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_html_drop_auth_anno.py -v`
Expected: All tests pass.

> **Note:** `auth_anno._get_secret` calls `load_config()` which depends on the
> existing conftest autouse fixture redirecting paths to tmp. Tests must run
> with the existing `tests/conftest.py` active — they do by default.

- [ ] **Step 5: Commit**

```bash
git add src/agent_html_drop/auth_anno.py tests/test_agent_html_drop_auth_anno.py
git commit -m "feat(agent-html-drop): auth_anno — cookie sign/verify, CSRF Origin check"
```

---

## Task 4: `api.py` — `/api/auth` + extend `list_files` with `annotation_count`

**Files:**
- Modify: `src/agent_html_drop/api.py:1-end`
- Test: `tests/test_agent_html_drop_annotations_api.py`

**Interfaces:**
- Produces (modifications to `api.py`):
  - `_make_auth(cfg)` → handler for `POST /api/auth`
  - `_file_info_payload` now includes `annotation_count: int`
  - `register_routes(cfg)` registers `POST /api/auth`

- [ ] **Step 1: Write failing tests (new file)**

```python
# tests/test_agent_html_drop_annotations_api.py
"""Tests for annotation auth + list_files annotation_count extension."""
import http.client
import json
import os
import threading
from http.cookies import SimpleCookie
from pathlib import Path

import pytest

from agent_html_drop.api import register_routes
from agent_html_drop.config import Config
from agent_html_drop.server import make_server, routes


@pytest.fixture
def http_server(cfg_factory):
    routes.clear()
    cfg = cfg_factory(docroot_files=["design.html"])
    srv = make_server("127.0.0.1", 0, quiet=True)
    register_routes(cfg)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv, cfg
    finally:
        srv.shutdown()
        srv.server_close()
        routes.clear()


@pytest.fixture
def cfg_factory(tmp_path, monkeypatch):
    """Factory that builds a Config with tmp paths; monkeypatches config.load_config."""
    from agent_html_drop import config as cfg_mod
    from agent_html_drop.storage import upload as storage_upload

    def _make(docroot_files=None, token="test-token-abc"):
        docroot = tmp_path / "docroot"
        docroot.mkdir(exist_ok=True)
        if docroot_files:
            for name, content in docroot_files:
                if isinstance(content, str):
                    storage_upload(docroot, name, content, max_size=10_000_000, force=True)
                else:  # path
                    (docroot / name).write_bytes(content)
        cfg = Config(
            host="127.0.0.1",
            port=0,
            docroot=str(docroot),
            public_base_url="https://notes.example.com",
            max_file_size=50 * 1024 * 1024,
            token=token,
            extra_top={},
            extra_auth={},
        )
        # Stub load_config for auth_anno._get_secret.
        monkeypatch.setattr(cfg_mod, "load_config", lambda: cfg)
        return cfg

    return _make


def _post(host, port, path, body=b"", headers=None):
    hdrs = {"Content-Length": str(len(body))}
    if headers:
        hdrs.update(headers)
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("POST", path, body=body, headers=hdrs)
        return conn.getresponse()
    finally:
        conn.close()


def _get(host, port, path, headers=None):
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("GET", path, headers=headers or {})
        return conn.getresponse()
    finally:
        conn.close()


def test_auth_correct_token_sets_cookie(http_server):
    srv, cfg = http_server
    host, port = srv.server_address
    r = _post(host, port, "/api/auth",
              body=b"",
              headers={"Authorization": "Bearer " + cfg.token})
    assert r.status == 204
    sc = r.getheader("Set-Cookie")
    assert sc is not None
    assert "anno_session=" in sc
    assert "HttpOnly" in sc
    assert "Secure" in sc
    assert "SameSite=Lax" in sc
    assert "Max-Age=1800" in sc


def test_auth_wrong_token_returns_401(http_server):
    srv, cfg = http_server
    host, port = srv.server_address
    r = _post(host, port, "/api/auth",
              headers={"Authorization": "Bearer WRONG"})
    assert r.status == 401


def test_auth_missing_header_returns_401(http_server):
    srv, _ = http_server
    host, port = srv.server_address
    r = _post(host, port, "/api/auth")
    assert r.status == 401


def test_list_files_includes_annotation_count_zero(http_server):
    srv, _ = http_server
    host, port = srv.server_address
    r = _get(host, port, "/api/files")
    assert r.status == 200
    data = json.loads(r.read())
    assert data["files"][0]["annotation_count"] == 0


def test_list_files_includes_annotation_count_nonzero(http_server):
    """Mutate docroot after server start, then re-fetch /api/files."""
    from agent_html_drop.storage import annotations as anno_store
    srv, cfg = http_server
    anno_store.add(Path(cfg.docroot), "design.html", "quote", "comment", "any-token")
    host, port = srv.server_address
    r = _get(host, port, "/api/files")
    data = json.loads(r.read())
    assert data["files"][0]["annotation_count"] == 1
```

> **Note:** the `test_list_files_includes_annotation_count_nonzero` test mutates
> the docroot after server start, which works because the test reads `cfg.docroot`
> from the same Config object the handler closure captured.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_html_drop_annotations_api.py -v`
Expected: FAIL — `POST /api/auth` returns 404 (route not registered).

- [ ] **Step 3: Modify `api.py`**

Apply the following edits to `src/agent_html_drop/api.py`:

```python
# Top of file: add imports
from agent_html_drop.storage import annotations as anno_store
from agent_html_drop.auth_anno import (
    ANNO_COOKIE_MAX_AGE, ANNO_COOKIE_NAME,
    cookie_set_header, csrf_check, verify_cookie,
)
```

Replace `_file_info_payload`:

```python
def _file_info_payload(f: storage.FileInfo, public_base_url: str, docroot: Path) -> Dict[str, Any]:
    return {
        "name": f.name,
        "size": f.size,
        "mtime": f.mtime,
        "url": public_base_url.rstrip("/") + "/" + f.name,
        "title": f.title,
        "annotation_count": anno_store.count(docroot, f.name),
    }
```

Update `_make_list_files` to pass `docroot`:

```python
def _make_list_files(cfg: Config):
    def handler(req, params, body):
        docroot = Path(cfg.docroot)
        try:
            files = storage.list_files(docroot)
        except storage.StorageError as exc:
            return _storage_error(exc)
        payload = {
            "files": [
                _file_info_payload(f, cfg.public_base_url, docroot)
                for f in files
            ]
        }
        return (200, json.dumps(payload).encode("utf-8"), JSON)
    return handler
```

Add new handler:

```python
def _make_auth(cfg: Config):
    """POST /api/auth — exchange Bearer token for an anno session cookie."""
    def handler(req, params, body):
        from agent_html_drop.auth import check_bearer
        if not check_bearer(req.headers.get("Authorization"), cfg.token):
            return _unauthorized()
        cookie_value = sign_cookie_for_token(cfg.token)  # helper defined below
        return (
            204,
            b"",
            {"Set-Cookie": cookie_set_header(cookie_value, ANNO_COOKIE_MAX_AGE)},
        )
    return handler


def sign_cookie_for_token(token: str) -> str:
    """Sign a fresh cookie for the given token. Used by /api/auth."""
    from agent_html_drop.auth_anno import sign_cookie
    return sign_cookie(token, max_age=ANNO_COOKIE_MAX_AGE)
```

Update `register_routes`:

```python
def register_routes(cfg: Config) -> None:
    """Register all /api/* and /health routes on the server registry."""
    srv.register("GET", r"^/api/files$", _make_list_files(cfg))
    srv.register("DELETE", r"^/api/files/(?P<name>[^/]+)$", _make_delete_file(cfg))
    srv.register("GET", r"^/api/nginx-config$", _make_nginx_config(cfg))
    srv.register("GET", r"^/api/health$", _health_handler)
    # New: token → cookie exchange.
    srv.register("POST", r"^/api/auth$", _make_auth(cfg))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_html_drop_annotations_api.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_html_drop/api.py tests/test_agent_html_drop_annotations_api.py
git commit -m "feat(agent-html-drop): /api/auth + annotation_count in list_files"
```

---

## Task 5: `api.py` — annotation REST CRUD (GET/POST/PATCH/DELETE)

**Files:**
- Modify: `src/agent_html_drop/api.py`
- Test: `tests/test_agent_html_drop_annotations_api.py` (extend)

**Interfaces:**
- Produces:
  - `_make_get_annotations(cfg)` → `GET /api/files/<name>/annotations` (公开)
  - `_make_post_annotation(cfg)` → `POST /api/files/<name>/annotations` (cookie + CSRF)
  - `_make_patch_annotation(cfg)` → `PATCH /api/files/<name>/annotations/<id>` (cookie + CSRF + author)
  - `_make_delete_annotation(cfg)` → `DELETE /api/files/<name>/annotations/<id>` (cookie + CSRF + author)

- [ ] **Step 1: Write failing tests (append)**

```python
# Append to tests/test_agent_html_drop_annotations_api.py
from agent_html_drop.storage.annotations import add as anno_add, count as anno_store_count
import http.client


def _cookie_header(cookie_value):
    return {"Cookie": ANNO_COOKIE_NAME + "=" + cookie_value}


def _patch(host, port, path, body=b"", headers=None):
    hdrs = {"Content-Length": str(len(body))}
    if headers:
        hdrs.update(headers)
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("PATCH", path, body=body, headers=hdrs)
        return conn.getresponse()
    finally:
        conn.close()


def test_get_annotations_public_returns_list(http_server):
    srv, cfg = http_server
    docroot = Path(cfg.docroot)
    anno_add(docroot, "design.html", "q1", "c1", "tok-x")
    anno_add(docroot, "design.html", "q2", "c2", "tok-y")
    host, port = srv.server_address
    r = _get(host, port, "/api/files/design.html/annotations")
    assert r.status == 200
    data = json.loads(r.read())
    assert data["name"] == "design.html"
    assert len(data["annotations"]) == 2


def test_post_annotation_without_cookie_returns_401(http_server):
    srv, _ = http_server
    host, port = srv.server_address
    r = _post(host, port, "/api/files/design.html/annotations",
              body=b'{"quote":"q","comment":"c"}',
              headers={"Content-Type": "application/json"})
    assert r.status == 401


def test_post_annotation_with_cookie_and_origin_creates(http_server, cfg_factory):
    """End-to-end: get a cookie via /api/auth, then POST annotation."""
    from agent_html_drop.auth_anno import sign_cookie, ANNO_COOKIE_NAME
    srv, cfg = http_server
    host, port = srv.server_address
    # Step 1: get cookie.
    r = _post(host, port, "/api/auth",
              headers={"Authorization": "Bearer " + cfg.token})
    assert r.status == 204
    sc = r.getheader("Set-Cookie")
    cookie = SimpleCookie()
    cookie.load(sc)
    cookie_value = cookie[ANNO_COOKIE_NAME].value

    # Step 2: POST annotation with cookie + matching Origin.
    r = _post(host, port, "/api/files/design.html/annotations",
              body=b'{"quote":"sudo mkdir","comment":"change"}',
              headers={
                  "Cookie": ANNO_COOKIE_NAME + "=" + cookie_value,
                  "Content-Type": "application/json",
                  "Origin": "https://notes.example.com",
                  "Host": "notes.example.com",
              })
    assert r.status == 201
    data = json.loads(r.read())
    assert data["quote"] == "sudo mkdir"
    assert data["comment"] == "change"
    assert data["author"].startswith("tk_")


def test_post_annotation_with_wrong_origin_returns_403(http_server, cfg_factory):
    from agent_html_drop.auth_anno import sign_cookie, ANNO_COOKIE_NAME
    srv, cfg = http_server
    host, port = srv.server_address
    r = _post(host, port, "/api/auth",
              headers={"Authorization": "Bearer " + cfg.token})
    sc = r.getheader("Set-Cookie")
    cookie = SimpleCookie()
    cookie.load(sc)
    cookie_value = cookie[ANNO_COOKIE_NAME].value

    r = _post(host, port, "/api/files/design.html/annotations",
              body=b'{"quote":"q","comment":"c"}',
              headers={
                  "Cookie": ANNO_COOKIE_NAME + "=" + cookie_value,
                  "Origin": "https://evil.com",
                  "Host": "notes.example.com",
              })
    assert r.status == 403


def test_patch_annotation_by_author_updates_comment(http_server, cfg_factory):
    from agent_html_drop.storage.annotations import author_of_token
    srv, cfg = http_server
    docroot = Path(cfg.docroot)
    entry = anno_add(docroot, "design.html", "q", "old", cfg.token)

    from agent_html_drop.auth_anno import sign_cookie, ANNO_COOKIE_NAME
    cookie_value = sign_cookie(cfg.token)

    host, port = srv.server_address
    r = _patch(host, port, "/api/files/design.html/annotations/" + entry["id"],
               body=b'{"comment":"new"}',
               headers={
                   "Cookie": ANNO_COOKIE_NAME + "=" + cookie_value,
                   "Content-Type": "application/json",
                   "Origin": "https://notes.example.com",
                   "Host": "notes.example.com",
               })
    assert r.status == 200
    data = json.loads(r.read())
    assert data["comment"] == "new"


def test_patch_by_other_token_returns_403(http_server, cfg_factory):
    srv, cfg = http_server
    docroot = Path(cfg.docroot)
    entry = anno_add(docroot, "design.html", "q", "old", "other-token")

    from agent_html_drop.auth_anno import sign_cookie, ANNO_COOKIE_NAME
    cookie_value = sign_cookie(cfg.token)

    host, port = srv.server_address
    r = _patch(host, port, "/api/files/design.html/annotations/" + entry["id"],
               body=b'{"comment":"hijacked"}',
               headers={
                   "Cookie": ANNO_COOKIE_NAME + "=" + cookie_value,
                   "Content-Type": "application/json",
                   "Origin": "https://notes.example.com",
                   "Host": "notes.example.com",
               })
    assert r.status == 403


def test_delete_annotation_by_author_succeeds(http_server, cfg_factory):
    srv, cfg = http_server
    docroot = Path(cfg.docroot)
    entry = anno_add(docroot, "design.html", "q", "c", cfg.token)

    from agent_html_drop.auth_anno import sign_cookie, ANNO_COOKIE_NAME
    cookie_value = sign_cookie(cfg.token)

    host, port = srv.server_address
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("DELETE",
                     "/api/files/design.html/annotations/" + entry["id"],
                     headers={
                         "Cookie": ANNO_COOKIE_NAME + "=" + cookie_value,
                         "Origin": "https://notes.example.com",
                         "Host": "notes.example.com",
                     })
        r = conn.getresponse()
    finally:
        conn.close()
    assert r.status == 200
    assert json.loads(r.read()) == {"deleted": True}
    assert anno_store.count(docroot, "design.html") == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_html_drop_annotations_api.py -v -k "post or patch or delete or get_annotations"`
Expected: FAIL with 404 (routes not registered).

- [ ] **Step 3: Implement the four new handlers**

Append to `src/agent_html_drop/api.py`:

```python
def _anno_path_meta(name: str) -> str:
    return r"^/api/files/(?P<name>[^/]+)/annotations$"


def _anno_path_item(name: str, id: str) -> str:
    return r"^/api/files/(?P<name>[^/]+)/annotations/(?P<id>[A-Za-z0-9_-]+)$"


def _make_get_annotations(cfg: Config):
    """GET /api/files/<name>/annotations — public, no auth."""
    def handler(req, params, body):
        docroot = Path(cfg.docroot)
        name = params.get("name", "")
        if not _validate_anno_name(name):
            return _err(400, "invalid_name", "name failed validation"), JSON  # type: ignore
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


def _validate_anno_name(name: str) -> bool:
    """Same regex as storage.validate_name but for annotation lookups."""
    import re as _re
    return bool(name) and bool(_re.match(r"^[A-Za-z0-9._-]+\.html$", name, _re.IGNORECASE))


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


def _make_post_annotation(cfg: Config):
    """POST /api/files/<name>/annotations — cookie + CSRF."""
    def handler(req, params, body):
        token = _anno_session_token(req)
        if not token:
            return (401, _err("unauthorized", "no valid anno session"), JSON)
        if not csrf_check(req.headers.get("Host", ""), req.headers.get("Origin")):
            return (403, _err("csrf", "origin mismatch"), JSON)
        name = params.get("name", "")
        if not _validate_anno_name(name):
            return (400, _err("invalid_name", "name failed validation"), JSON)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return (400, _err("invalid_body", "body must be JSON"), JSON)
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


def _make_patch_annotation(cfg: Config):
    """PATCH /api/files/<name>/annotations/<id> — cookie + CSRF + author."""
    def handler(req, params, body):
        token = _anno_session_token(req)
        if not token:
            return (401, _err("unauthorized", "no valid anno session"), JSON)
        if not csrf_check(req.headers.get("Host", ""), req.headers.get("Origin")):
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
        if not csrf_check(req.headers.get("Host", ""), req.headers.get("Origin")):
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


def _author_of(token: str) -> str:
    from agent_html_drop.auth_anno import author_of_token
    return author_of_token(token)
```

Update `register_routes` to register the four new routes:

```python
def register_routes(cfg: Config) -> None:
    srv.register("GET", r"^/api/files$", _make_list_files(cfg))
    srv.register("DELETE", r"^/api/files/(?P<name>[^/]+)$", _make_delete_file(cfg))
    srv.register("GET", r"^/api/nginx-config$", _make_nginx_config(cfg))
    srv.register("GET", r"^/api/health$", _health_handler)
    srv.register("POST", r"^/api/auth$", _make_auth(cfg))
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_html_drop_annotations_api.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_html_drop/api.py tests/test_agent_html_drop_annotations_api.py
git commit -m "feat(agent-html-drop): annotation REST CRUD (GET/POST/PATCH/DELETE)"
```

---

## Task 6: `mcp_handler.py` — `list_annotations` + `delete_annotation` tools

**Files:**
- Modify: `src/agent_html_drop/mcp_handler.py`
- Test: `tests/test_agent_html_drop_annotations_mcp.py` (new)

**Interfaces:**
- Produces (additions to `TOOL_SCHEMAS` and `_TOOL_DISPATCH`):
  - `list_annotations(name) -> {name, annotations: [...]}`
  - `delete_annotation(name, id) -> {deleted: bool}` — agent-side deletion **does not** require author match (N11: agent has the token, is the privileged deleter of spam).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_html_drop_annotations_mcp.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_html_drop_annotations_mcp.py -v`
Expected: FAIL — `tools/list` lacks `list_annotations`/`delete_annotation`.

- [ ] **Step 3: Add tools to `mcp_handler.py`**

Append to `TOOL_SCHEMAS`:

```python
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
```

Append to `_TOOL_DISPATCH`:

```python
def _impl_list_annotations(args: Dict[str, Any], cfg: Config) -> Dict[str, Any]:
    from agent_html_drop.storage import annotations as anno_store
    name = args.get("name")
    if not isinstance(name, str):
        raise ValueError("name must be a string")
    entries = anno_store.list_for(Path(cfg.docroot), name)
    return _tool_result(json.dumps({"name": name, "annotations": entries}, ensure_ascii=False))


def _impl_delete_annotation(args: Dict[str, Any], cfg: Config) -> Dict[str, Any]:
    from agent_html_drop.storage import annotations as anno_store
    name = args.get("name")
    id_ = args.get("id")
    if not isinstance(name, str) or not isinstance(id_, str):
        raise ValueError("name and id must be strings")
    doc = anno_store.load(Path(cfg.docroot), name)
    before = len(doc["annotations"])
    doc["annotations"] = [e for e in doc["annotations"] if e.get("id") != id_]
    if len(doc["annotations"]) == before:
        raise storage.NotFound("annotation not found: {}".format(id_))
    anno_store.save(Path(cfg.docroot), name, doc)
    return _tool_result(json.dumps({"deleted": True}))


_TOOL_DISPATCH["list_annotations"] = _impl_list_annotations
_TOOL_DISPATCH["delete_annotation"] = _impl_delete_annotation
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_html_drop_annotations_mcp.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_html_drop/mcp_handler.py tests/test_agent_html_drop_annotations_mcp.py
git commit -m "feat(agent-html-drop): MCP list_annotations + delete_annotation tools"
```

---

## Task 7: `ui/index.html` + `style.css` — header button + modal `<dialog>` + sidebar

**Files:**
- Modify: `src/agent_html_drop/ui/index.html`
- Modify: `src/agent_html_drop/ui/style.css`
- Test: `tests/test_agent_html_drop_annotations_ui.py` (new) — string assertions only, no JS execution

**Interfaces:**
- DOM additions to `index.html`:
  - `<header>` gets a `<button id="anno-toggle">批注(需 token)</button>` and `<span id="anno-mode-hint">` (hidden by default)
  - `<dialog id="anno-token-dialog">` with `<input>` + submit button
  - `<aside id="anno-sidebar">` (hidden by default in read mode) showing annotations list

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_html_drop_annotations_ui.py
"""DOM shape assertions for the annotation UI. Pure string checks."""
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent / "src" / "agent_html_drop" / "ui"


def test_index_has_anno_toggle_button():
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="anno-toggle"' in html


def test_index_has_token_dialog():
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert '<dialog id="anno-token-dialog"' in html
    assert 'id="anno-token-input"' in html
    assert 'id="anno-token-submit"' in html


def test_index_has_anno_sidebar():
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="anno-sidebar"' in html
    assert 'id="anno-list"' in html


def test_index_has_no_inline_token_storage():
    """F19: token must NOT be persisted to localStorage in any visible script tag."""
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    # Inline script tags load /app.js; this rule covers the index.html itself
    # (which should be empty of <script> tags per existing V1).
    assert "<script" not in html


def test_app_js_declares_mode_state():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert 'mode' in js  # state machine variable
    assert "anno" in js  # either 'anno' or 'read' literals


def test_app_js_calls_anno_endpoints():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "/api/auth" in js
    assert "/api/files" in js


def test_app_js_does_not_embed_token_literal_in_cleartext():
    """No `Bearer ${...}` patterns with literal tokens leaked in code."""
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    # The page never has the token in JS source — token comes from user input.
    assert "tk_" not in js or "tk_".index("tk_") > 0  # tolerate library references


def test_css_has_anno_mode_styles():
    css = (UI_DIR / "style.css").read_text(encoding="utf-8")
    assert "#anno-toggle" in css
    assert "#anno-sidebar" in css
    assert "dialog" in css.lower() or "#anno-token-dialog" in css
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_html_drop_annotations_ui.py -v`
Expected: FAIL — DOM elements missing.

- [ ] **Step 3: Update `ui/index.html`**

Read the current `src/agent_html_drop/ui/index.html`, then make the following insertions (do not rewrite the file):

```html
<!-- Inside <header>, after existing <span class="hint">浏览模式 ...</span>: -->
<button id="anno-toggle" type="button" aria-label="进入批注模式">批注(需 token)</button>
<span id="anno-mode-hint" class="hint" hidden>批注模式 · <a href="#" id="anno-exit">退出</a></span>

<!-- Before the existing <table id="file-table"> or wherever layout fits: -->
<dialog id="anno-token-dialog" aria-labelledby="anno-token-title">
  <form method="dialog" id="anno-token-form">
    <h2 id="anno-token-title">进入批注模式</h2>
    <p>粘贴 agent-html-drop token(在 server 端跑 <code>agent-html-drop token show</code> 获取)</p>
    <input id="anno-token-input" type="password" autocomplete="off" />
    <menu>
      <button type="button" id="anno-token-cancel">取消</button>
      <button type="submit" id="anno-token-submit">进入</button>
    </menu>
    <p id="anno-token-error" class="error" hidden></p>
  </form>
</dialog>

<!-- Sidebar (rendered when in anno mode AND a file is previewed): -->
<aside id="anno-sidebar" aria-label="批注" hidden>
  <header>
    <h3 id="anno-sidebar-title">批注</h3>
    <button id="anno-sidebar-refresh" type="button" aria-label="刷新">↻</button>
  </header>
  <ul id="anno-list"></ul>
  <p id="anno-empty" hidden>暂无批注</p>
</aside>
```

- [ ] **Step 4: Update `ui/style.css`**

Append to `src/agent_html_drop/ui/style.css`:

```css
/* --- annotation mode --- */
#anno-toggle {
  /* matches existing button styling */
  background: var(--accent);
  color: var(--bg);
  border: 0;
  border-radius: 4px;
  padding: 4px 12px;
  font-size: 13px;
  cursor: pointer;
}

#anno-toggle:hover { opacity: 0.85; }

#anno-mode-hint { color: var(--accent); }

#anno-token-dialog {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 20px;
  min-width: 320px;
  background: var(--bg);
  color: var(--fg);
}

#anno-token-dialog::backdrop { background: rgba(0,0,0,0.4); }

#anno-token-input {
  display: block;
  width: 100%;
  padding: 6px;
  margin: 8px 0;
  font-family: ui-monospace, monospace;
  font-size: 13px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg);
  color: var(--fg);
}

#anno-token-dialog menu {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin: 8px 0 0;
  padding: 0;
}

#anno-token-dialog button {
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg);
  color: var(--fg);
  cursor: pointer;
}

#anno-token-dialog button[type="submit"] {
  background: var(--accent);
  color: var(--bg);
  border-color: var(--accent);
}

#anno-token-dialog .error {
  color: var(--danger);
  margin-top: 8px;
  font-size: 12px;
}

#anno-sidebar {
  position: fixed;
  right: 0;
  top: 0;
  width: 280px;
  height: 100vh;
  background: var(--bg);
  border-left: 1px solid var(--border);
  padding: 12px;
  overflow-y: auto;
  font-size: 13px;
}

#anno-sidebar header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

#anno-sidebar h3 { margin: 0; font-size: 14px; }

#anno-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

#anno-list li {
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  margin-bottom: 8px;
}

#anno-list li .quote {
  font-style: italic;
  color: var(--fg-dim);
  font-size: 12px;
}

#anno-list li.invalid .quote::after {
  content: " ⚠️ 引用已变更";
  color: var(--danger);
}

#anno-list li .meta {
  font-size: 11px;
  color: var(--fg-dim);
  margin-top: 4px;
}

#anno-list li button {
  font-size: 11px;
  padding: 2px 6px;
  margin-right: 4px;
  background: var(--bg);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: 3px;
  cursor: pointer;
}

#anno-list li button.danger {
  color: var(--danger);
  border-color: var(--danger);
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_agent_html_drop_annotations_ui.py -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/agent_html_drop/ui/ tests/test_agent_html_drop_annotations_ui.py
git commit -m "feat(agent-html-drop): anno-mode toggle, token dialog, sidebar DOM + CSS"
```

---

## Task 8: `ui/app.js` — mode state machine + token submit + iframe selection + `<mark>` injection

**Files:**
- Modify: `src/agent_html_drop/ui/app.js`
- Test: `tests/test_agent_html_drop_annotations_ui.py` (extend) + manual smoke (Task 10)

**Interfaces:**
- DOM contract:
  - Click `#anno-toggle` → open `#anno-token-dialog`
  - Submit dialog → POST `/api/auth` with Bearer → on success: cookie set by server, mode = "anno", show `#anno-mode-hint`, hide `#anno-toggle`
  - Click `#anno-exit` → clear cookie client-side (call a new endpoint? OR just reload the page) → mode = "read"
  - In anno mode + file previewed: fetch `/api/files/<name>/annotations` → render `#anno-list`
  - On iframe load: scan text nodes in iframe, find quote, wrap with `<mark data-anno-id="...">`. Quotes not found → mark entry `.invalid`.

- [ ] **Step 1: Write failing tests (extend existing)**

```python
# Append to tests/test_agent_html_drop_annotations_ui.py
def test_app_js_handles_iframe_text_walk():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    # Should walk text nodes and wrap matches.
    assert "createTreeWalker" in js or "TextNode" in js or "nodeType" in js
    assert "data-anno-id" in js


def test_app_js_handles_iframe_same_origin_sandbox():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    # iframe must be allow-same-origin (not full sandbox) so we can DOM-walk.
    assert "allow-same-origin" in js


def test_app_js_marks_invalid_quotes():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "invalid" in js  # .invalid class for missing quote


def test_app_js_does_not_allow_scripts_in_iframe():
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    # Ensure we never set allow-scripts (would let Mermaid/MathJax run inside preview).
    assert "allow-scripts" not in js
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_html_drop_annotations_ui.py -v -k "iframe or invalid or allow"`
Expected: FAIL — `data-anno-id`, `allow-same-origin`, `invalid` not yet in app.js.

- [ ] **Step 3: Implement `app.js` anno-mode logic**

Open `src/agent_html_drop/ui/app.js`. **Preserve all existing read-mode logic verbatim** (loadFiles, preview, copyUrl, fallbackCopy, table onclick handler, etc.). Append the following state machine + anno-mode module:

```javascript
/* === annotation mode (extension) ============================== */

// --- state ---------------------------------------------------------
var mode = "read"; // "read" | "anno"
var annoCurrentFile = null;
var annoEntries = [];

// --- DOM refs (anno-specific) --------------------------------------
var $annoToggle = document.getElementById("anno-toggle");
var $annoModeHint = document.getElementById("anno-mode-hint");
var $annoExit = document.getElementById("anno-exit");
var $annoDialog = document.getElementById("anno-token-dialog");
var $annoForm = document.getElementById("anno-token-form");
var $annoInput = document.getElementById("anno-token-input");
var $annoCancel = document.getElementById("anno-token-cancel");
var $annoError = document.getElementById("anno-token-error");
var $annoSidebar = document.getElementById("anno-sidebar");
var $annoList = document.getElementById("anno-list");
var $annoEmpty = document.getElementById("anno-empty");
var $annoSidebarRefresh = document.getElementById("anno-sidebar-refresh");
var $annoSidebarTitle = document.getElementById("anno-sidebar-title");

// --- helpers -------------------------------------------------------

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
  });
}

function normalize(s) {
  return String(s).replace(/\s+/g, " ").trim();
}

// Build a same-origin URL for the same host as the page (so Origin
// header matches the iframe's actual host when daemon lives behind nginx).
function originFor() {
  return window.location.origin;
}

function csrfHeaders(extra) {
  var h = { "Content-Type": "application/json", "Origin": originFor() };
  if (extra) for (var k in extra) h[k] = extra[k];
  return h;
}

function credentials() {
  return "include";
}

function setMode(newMode) {
  mode = newMode;
  if (mode === "anno") {
    $annoToggle.hidden = true;
    $annoModeHint.hidden = false;
    $annoSidebar.hidden = false;
  } else {
    $annoToggle.hidden = false;
    $annoModeHint.hidden = true;
    $annoSidebar.hidden = true;
    clearAnnoList();
  }
}

function showAnnoError(msg) {
  $annoError.textContent = msg;
  $annoError.hidden = false;
}
function clearAnnoError() {
  $annoError.textContent = "";
  $annoError.hidden = true;
}

// --- auth flow -----------------------------------------------------

$annoToggle.onclick = function () {
  clearAnnoError();
  $annoInput.value = "";
  if (typeof $annoDialog.showModal === "function") {
    $annoDialog.showModal();
  } else {
    $annoDialog.setAttribute("open", "");
  }
  $annoInput.focus();
};

$annoCancel.onclick = function () { $annoDialog.close(); };

$annoForm.onsubmit = function (e) {
  e.preventDefault();
  clearAnnoError();
  var token = $annoInput.value.trim();
  if (!token) {
    showAnnoError("请输入 token");
    return;
  }
  fetch("/api/auth", {
    method: "POST",
    credentials: credentials(),
    headers: { "Authorization": "Bearer " + token },
  }).then(function (r) {
    if (r.status === 204) {
      $annoDialog.close();
      setMode("anno");
      // If a file is currently previewed, refresh annotations.
      if (annoCurrentFile) refreshAnnoList();
    } else if (r.status === 401) {
      showAnnoError("token 错误,联系 owner 获取");
    } else {
      showAnnoError("server 错误 " + r.status);
    }
  }).catch(function () {
    showAnnoError("网络错误,稍后重试");
  });
};

$annoExit.onclick = function (e) {
  e.preventDefault();
  // No "logout" endpoint; simplest: ask server to forget by sending empty
  // Authorization on a no-op fetch won't work. Instead, client just
  // transitions back to read mode; server-side cookie expires naturally.
  setMode("read");
};

$annoSidebarRefresh.onclick = function () { refreshAnnoList(); };

// --- annotations: list / render -----------------------------------

function refreshAnnoList() {
  if (!annoCurrentFile) return;
  fetch("/api/files/" + encodeURIComponent(annoCurrentFile) + "/annotations", {
    credentials: credentials(),
  }).then(function (r) { return r.json(); })
    .then(function (data) {
      annoEntries = (data && data.annotations) || [];
      renderAnnoList();
      highlightIframe();
    })
    .catch(function () {
      annoEntries = [];
      renderAnnoList();
    });
}

function renderAnnoList() {
  $annoList.innerHTML = "";
  $annoSidebarTitle.textContent = "批注 · " + annoCurrentFile;
  if (!annoEntries.length) {
    $annoEmpty.hidden = false;
    return;
  }
  $annoEmpty.hidden = true;
  annoEntries.forEach(function (e) {
    var li = document.createElement("li");
    li.setAttribute("data-anno-id", e.id);
    var quote = document.createElement("div");
    quote.className = "quote";
    quote.textContent = '"' + e.quote + '"';
    li.appendChild(quote);
    var comment = document.createElement("div");
    comment.className = "comment";
    comment.textContent = e.comment;
    li.appendChild(comment);
    var meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = e.author + " · " + new Date(e.ts * 1000).toISOString().slice(0, 16).replace("T", " ");
    li.appendChild(meta);
    // Actions: only in anno mode.
    var actions = document.createElement("div");
    actions.className = "actions";
    var delBtn = document.createElement("button");
    delBtn.className = "danger";
    delBtn.textContent = "删除";
    delBtn.onclick = function () { deleteAnno(e.id); };
    actions.appendChild(delBtn);
    li.appendChild(actions);
    $annoList.appendChild(li);
  });
}

function clearAnnoList() {
  $annoList.innerHTML = "";
  annoEntries = [];
  annoCurrentFile = null;
}

function deleteAnno(id) {
  if (!annoCurrentFile) return;
  if (!window.confirm("删除这条批注?")) return;
  fetch(
    "/api/files/" + encodeURIComponent(annoCurrentFile) + "/annotations/" + id,
    {
      method: "DELETE",
      credentials: credentials(),
      headers: { "Origin": originFor() },
    }
  ).then(function (r) {
    if (r.status === 200) refreshAnnoList();
    else toast("删除失败 " + r.status, true);
  });
}

// --- iframe `<mark>` injection ------------------------------------

function highlightIframe() {
  if (!$previewFrame || !$previewFrame.contentDocument) return;
  var doc = $previewFrame.contentDocument;
  annoEntries.forEach(function (e) {
    var found = false;
    var walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT, null, false);
    var node;
    while ((node = walker.nextNode())) {
      if (normalize(node.nodeValue).indexOf(normalize(e.quote)) !== -1) {
        wrapTextMatch(node, normalize(e.quote), e.id);
        found = true;
      }
    }
    if (!found) {
      var li = $annoList.querySelector('li[data-anno-id="' + cssEscape(e.id) + '"]');
      if (li) li.classList.add("invalid");
    }
  });
}

function wrapTextMatch(textNode, normalizedQuote, annoId) {
  // Walk back to find the literal substring in the actual nodeValue (preserving
  // surrounding whitespace). Strategy: find the first index where
  // normalize(nodeValue.substring(i, i + normalizedQuote.length)) == normalizedQuote.
  var s = textNode.nodeValue;
  var i = findNormalizedMatch(s, normalizedQuote);
  if (i < 0) return;
  var matchedText = s.substr(i, normalizedQuote.length + slack(s, i, normalizedQuote.length));
  var before = s.slice(0, i);
  var after = s.slice(i + matchedText.length);
  var mark = textNode.ownerDocument.createElement("mark");
  mark.setAttribute("data-anno-id", annoId);
  mark.appendChild(textNode.ownerDocument.createTextNode(matchedText));
  var parent = textNode.parentNode;
  parent.insertBefore(textNode.ownerDocument.createTextNode(before), textNode);
  parent.insertBefore(mark, textNode);
  parent.insertBefore(textNode.ownerDocument.createTextNode(after), textNode);
  parent.removeChild(textNode);
}

function findNormalizedMatch(s, normalizedQuote) {
  // Brute-force linear scan; acceptable for small/medium pages.
  for (var i = 0; i <= s.length - normalizedQuote.length; i++) {
    if (normalize(s.substr(i, normalizedQuote.length)) === normalizedQuote) {
      return i;
    }
  }
  return -1;
}

function slack(s, i, baseLen) {
  // How many extra chars can we safely include beyond the normalized length
  // so we don't cut a word? Extend forward while the next char is whitespace.
  var extra = 0;
  while (i + baseLen + extra < s.length && /\s/.test(s.charAt(i + baseLen + extra))) {
    extra++;
  }
  return extra;
}

function cssEscape(s) {
  return String(s).replace(/(["\\])/g, "\\$1");
}

// --- hook into existing preview() (defined earlier in app.js) ---
//
// Rather than monkey-patch `preview`, listen for iframe load events. When
// the preview section becomes visible and the iframe fires load, we capture
// the current file from the preview name label and refresh annotations.

// Mark current file from previewName label (which V1's preview() fills with
// "(" + name + ")"). Cheaper than re-parsing iframe.src.
$previewFrame.addEventListener("load", function () {
  var m = $previewName.textContent.match(/^\((.+)\)$/);
  if (m) annoCurrentFile = m[1];
  if (mode === "anno") refreshAnnoList();
});

// When preview is hidden, clear current file.
var previewHiddenObserver = new MutationObserver(function () {
  if ($previewSection.hidden) {
    annoCurrentFile = null;
    clearAnnoList();
  }
});
previewHiddenObserver.observe($previewSection, { attributes: true, attributeFilter: ["hidden"] });
```

> **Important:** This block requires that `preview`, `$previewFrame`, `$previewSection` are already declared elsewhere in `app.js` (they are — see current V1 implementation). Place this whole block **at the end** of `app.js`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_html_drop_annotations_ui.py -v`
Expected: All pass (DOM strings + app.js content checks).

- [ ] **Step 5: Manual smoke (not in CI)**

```bash
# Start daemon with a known token, upload a test file, open browser.
agent-html-drop init   # if not already
agent-html-drop serve &
# In another terminal, upload:
python3 -c "
import json, urllib.request
body = json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call',
                   'params':{'name':'upload_html',
                             'arguments':{'name':'design.html',
                                           'content':'<!doctype html><html><body><p>sudo mkdir -p /var/www</p></body></html>'}}}).encode()
req = urllib.request.Request('http://127.0.0.1:8765/mcp', data=body,
                              headers={'Authorization':'Bearer <token>','Content-Type':'application/json'})
print(urllib.request.urlopen(req).read())
"
# Open http://127.0.0.1:8765/ in browser. Click "批注(需 token)".
# Submit token → 批注模式 → select "sudo mkdir" text → expect highlight in iframe.
```

- [ ] **Step 6: Commit**

```bash
git add src/agent_html_drop/ui/app.js tests/test_agent_html_drop_annotations_ui.py
git commit -m "feat(agent-html-drop): anno-mode state machine, iframe <mark> injection, sidebar render"
```

---

## Task 9: `nginx.conf.template` — `SameSite=Lax` + `limit_req`

**Files:**
- Modify: `src/agent_html_drop/assets/nginx.conf.template`
- Test: `tests/test_agent_html_drop_nginx.py` (extend — assert template contains directives)

**Interfaces:**
- Adds:
  - `proxy_cookie_path / "/; HttpOnly; Secure; SameSite=Lax";` (belt-and-suspenders — daemon also sets these attrs)
  - `limit_req_zone $binary_remote_addr zone=auth:10m rate=10r/s;` (outside server block)
  - `limit_req zone=auth burst=20 nodelay;` inside `location /api/auth` and `location ~ ^/api/files/[^/]+/annotations`
  - Comment block explaining the why

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/test_agent_html_drop_nginx.py
def test_nginx_template_sets_samesite_lax():
    from pathlib import Path
    from agent_html_drop.nginx_config import render
    cfg = Config(
        host="127.0.0.1", port=8765,
        docroot="/var/www/notes",
        public_base_url="https://notes.example.com",
        max_file_size=50 * 1024 * 1024,
        token="t", extra_top={}, extra_auth={},
    )
    text = render(docroot=cfg.docroot, port=cfg.port, public_base_url=cfg.public_base_url)
    assert "proxy_cookie_path" in text
    assert "SameSite=Lax" in text


def test_nginx_template_includes_limit_req():
    from agent_html_drop.nginx_config import render
    from agent_html_drop.config import Config
    cfg = Config(
        host="127.0.0.1", port=8765, docroot="/var/www/notes",
        public_base_url="https://notes.example.com",
        max_file_size=50 * 1024 * 1024,
        token="t", extra_top={}, extra_auth={},
    )
    text = render(docroot=cfg.docroot, port=cfg.port, public_base_url=cfg.public_base_url)
    assert "limit_req_zone" in text
    assert "rate=10r/s" in text


def test_nginx_template_applies_limit_req_to_auth():
    from agent_html_drop.nginx_config import render
    from agent_html_drop.config import Config
    cfg = Config(
        host="127.0.0.1", port=8765, docroot="/var/www/notes",
        public_base_url="https://notes.example.com",
        max_file_size=50 * 1024 * 1024,
        token="t", extra_top={}, extra_auth={},
    )
    text = render(docroot=cfg.docroot, port=cfg.port, public_base_url=cfg.public_base_url)
    # The /api/auth location block must apply the limit_req zone.
    auth_block = text.split("location = /api/auth", 1)[1].split("}", 1)[0]
    assert "limit_req zone=auth" in auth_block


def test_nginx_template_applies_limit_req_to_annotations():
    from agent_html_drop.nginx_config import render
    from agent_html_drop.config import Config
    cfg = Config(
        host="127.0.0.1", port=8765, docroot="/var/www/notes",
        public_base_url="https://notes.example.com",
        max_file_size=50 * 1024 * 1024,
        token="t", extra_top={}, extra_auth={},
    )
    text = render(docroot=cfg.docroot, port=cfg.port, public_base_url=cfg.public_base_url)
    assert "location ~ ^/api/files/[^/]+/annotations" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_html_drop_nginx.py -v -k "samesite or limit_req"`
Expected: FAIL — directives missing from template.

- [ ] **Step 3: Update `assets/nginx.conf.template`**

Open the existing template, then add inside the `server { ... }` block (after the existing `location /mcp` block):

```nginx
# --- annotation security (design §9.3) ---
# SameSite=Lax cookie — daemon already sets it on /api/auth responses;
# this directive is belt-and-suspenders for any future proxied cookies.
proxy_cookie_path / "/; HttpOnly; Secure; SameSite=Lax";

# Rate-limit /api/auth and the annotation write paths to deter brute-force
# token guessing (token is 256-bit random so math is impossible; this is a
# cheap defense against script kiddies hammering the endpoint).
limit_req_zone $binary_remote_addr zone=auth:10m rate=10r/s;

location = /api/auth {
    limit_req zone=auth burst=20 nodelay;
    proxy_pass http://127.0.0.1:8765;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location ~ ^/api/files/[^/]+/annotations$ {
    limit_req zone=auth burst=20 nodelay;
    proxy_pass http://127.0.0.1:8765;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location ~ ^/api/files/[^/]+/annotations/[A-Za-z0-9_-]+$ {
    limit_req zone=auth burst=20 nodelay;
    proxy_pass http://127.0.0.1:8765;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_html_drop_nginx.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_html_drop/assets/ tests/test_agent_html_drop_nginx.py
git commit -m "feat(agent-html-drop): nginx template — SameSite=Lax + limit_req on auth/annotations"
```

---

## Task 10: README + E2E smoke for annotations

**Files:**
- Modify: `src/agent_html_drop/README.md`
- Create: `tests/test_agent_html_drop_annotations_smoke.py`

**Interfaces:**
- README gets a "批注" quick-start section.
- Smoke test exercises: upload → enter anno mode → POST annotation → iframe render → MCP `list_annotations` → MCP `delete_annotation`.

- [ ] **Step 1: Write failing smoke test**

```python
# tests/test_agent_html_drop_annotations_smoke.py
"""End-to-end smoke for the annotation flow.

Covers:
  - S36 (browser enters anno mode via /api/auth)
  - S37 (browser posts annotation, gets 201)
  - S39 (agent calls list_annotations and sees the entry)
  - S40 (agent calls delete_annotation and the entry is gone)
"""
import json
import threading
from pathlib import Path

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
    cfg_mod.load_config = lambda: cfg  # type: ignore
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
```

- [ ] **Step 2: Run smoke test to verify it passes**

Run: `pytest tests/test_agent_html_drop_annotations_smoke.py -v`
Expected: PASS.

- [ ] **Step 3: Update `src/agent_html_drop/README.md`**

Add after the existing "## 局限性" section (or wherever fits):

```markdown
## 批注(可选)

管理页支持浏览器侧批注：选中 iframe 中的文本，填评论，提交。批注不影响原始 HTML
文件(`.html` 与 `.meta` 严格分离)，所以可以放心反复修改设计稿，批注留档。

启用方式：

1. 进入批注模式：管理页右上角 **"批注(需 token)"** 按钮 → 弹框 → 粘贴 token
   （在 server 端跑 `agent-html-drop token show` 获取）→ 进入。
2. 选中文本 → 弹出评论输入框 → 提交。批注高亮（`<mark>`）自动注入到 iframe。
3. 退出批注模式：点 "退出" 链接。cookie 30 分钟自动过期。

agent 视角：

- `list_annotations(name)` —— 读取某文件的全部批注（结构化字段）
- `delete_annotation(name, id)` —— 删除某条（用于清理 spam / 已解决）
- **不开放** `add_annotation` 给 agent（写批注由浏览器发起）

安全模型：

- 浏览器写批注走短期 session cookie（30 分钟，HttpOnly / Secure / SameSite=Lax）
- agent 改 HTML 走原有 Bearer token
- 两条路径**互不重叠**，agent 无批注写接口，浏览器无 HTML 写接口
- nginx 模板默认带 `limit_req` 防 `/api/auth` 暴力穷举
```

- [ ] **Step 4: Run all tests to verify nothing regressed**

Run: `pytest -q`
Expected: All pass (including V1 + new annotation tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_agent_html_drop_annotations_smoke.py src/agent_html_drop/README.md
git commit -m "feat(agent-html-drop): anno smoke test + README 批注 section"
```

---

## Self-Review Notes

**Spec coverage:**

| Spec section | Covered by task |
| --- | --- |
| §1 A3 / A3' (single token) | Task 3 (auth_anno uses same token) |
| §2 N8 / N10 / N11 | Task 4 / 5 / 6 (no persistent cookie; agent-only delete) |
| §3 F19–F25 | Tasks 7 / 8 / 5 (header button + token dialog + iframe + REST) |
| §4 author hash / cookie TTL / CSRF / nginx limits / sandbox | Tasks 3 / 8 / 9 |
| §5 S36–S40 | Task 10 (full roundtrip smoke) |
| §7.2 .meta schema | Task 2 (annotations.py CRUD) |
| §7.3 /api/auth + REST CRUD + MCP tools | Tasks 4 / 5 / 6 |
| §8 quote 失配 / cookie 过期 / Origin 不匹配 | Tasks 5 (tests cover) / 8 (`.invalid` class) |
| §9.3 SameSite=Lax + Origin check + limit_req | Tasks 3 / 9 |
| §10 否决 J / K | Implicit: agent has no add tool (Task 6 test verifies) |
| §13 Q8–Q11 | Defaults baked into Tasks 7 / 3 / 9 |

**No placeholders:** every step has code or a specific command.

**Type/name consistency:** ULID alphabet / `author_of_token` / `verify_cookie` names match across Tasks 1/2/3/5/6.

**Done when:** all 10 task commits land on `master`; `pytest -q` is green; manual browser smoke (Task 8 step 5) shows highlighted quote after entering anno mode and submitting an annotation.