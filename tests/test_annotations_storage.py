"""Tests for agent_html_drop.storage.annotations — ULID, author hash, quote normalize."""
from agent_html_drop.storage.annotations import load, ulid_new, author_of_token, normalize_quote


# CRUD tests
import json
from pathlib import Path

import pytest

from agent_html_drop.storage.annotations import (
    add, delete, delete_all_for, list_for, count, get, load,
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


# --- delete_all_for: drop a file's whole .meta (used when deleting HTML) ---

def test_delete_all_for_removes_meta(docroot):
    add(docroot, "design.html", "q", "c", "t")
    add(docroot, "design.html", "q2", "c2", "t")
    assert (docroot / "design.html.meta").exists()
    assert delete_all_for(docroot, "design.html") is True
    assert not (docroot / "design.html.meta").exists()
    # All annotations gone, not just one.
    assert count(docroot, "design.html") == 0


def test_delete_all_for_missing_returns_false(docroot):
    # No meta file → False, idempotent (mirrors storage.delete's "missing is
    # not an error" contract so callers can 404-or-ignore uniformly).
    assert delete_all_for(docroot, "never.html") is False


def test_delete_all_for_leaves_html_untouched(docroot):
    # Only the .meta sidecar is removed. Deleting the HTML itself is
    # storage.delete's job — keeping them separate preserves the one-way
    # dependency (storage does not import annotations).
    (docroot / "design.html").write_text("<h1>x</h1>")
    add(docroot, "design.html", "q", "c", "t")
    assert delete_all_for(docroot, "design.html") is True
    assert (docroot / "design.html").exists()
    assert not (docroot / "design.html.meta").exists()


def test_get_returns_entry(docroot):
    entry = add(docroot, "design.html", "q", "c", "t")
    got = get(docroot, "design.html", entry["id"])
    assert got["quote"] == "q"


def test_get_missing_returns_none(docroot):
    assert get(docroot, "design.html", "anything") is None


def test_save_atomic_no_leftover_tmp(docroot):
    add(docroot, "design.html", "q", "c", "t")
    assert not (docroot / "design.html.meta.tmp").exists()
def test_load_non_utf8_meta_returns_empty_doc(tmp_path):
    (tmp_path / "example.meta").write_bytes(b"\xff\xfe\x80")

    assert load(tmp_path, "example") == {"version": 1, "annotations": []}


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