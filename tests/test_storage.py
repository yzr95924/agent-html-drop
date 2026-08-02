"""Tests for agent_html_drop.storage — file CRUD, atomic write, name validation."""
from pathlib import Path

import pytest

from agent_html_drop._legacy_storage import (
    Conflict,
    DocrootUnwritable,
    FileInfo,
    InvalidName,
    NotFound,  # noqa: F401 — exported, may be used by callers
    StorageError,
    TooLarge,
    delete,
    list_files,
    upload,
    validate_name,
)


# --- validate_name -----------------------------------------------------------

def test_validate_name_accepts_basic_html():
    validate_name("design.html")  # no raise


def test_validate_name_accepts_dashed_and_dotted():
    validate_name("meeting-2026-08-01.html")
    validate_name("draft.v2.html")


def test_validate_name_accepts_underscores():
    validate_name("draft_v2.html")


def test_validate_name_accepts_uppercase_suffix():
    validate_name("DESIGN.HTML")  # suffix matched case-insensitively


def test_validate_name_accepts_exactly_max_length():
    # 195 chars + ".html" (5) = 200.
    validate_name("a" * 195 + ".html")


def test_validate_name_rejects_over_max_length():
    with pytest.raises(InvalidName, match="exceeds max"):
        validate_name("a" * 196 + ".html")


def test_validate_name_rejects_empty():
    with pytest.raises(InvalidName, match="non-empty"):
        validate_name("")


def test_validate_name_rejects_non_string():
    with pytest.raises(InvalidName, match="must be a string"):
        validate_name(123)


def test_validate_name_rejects_path_traversal():
    with pytest.raises(InvalidName):
        validate_name("../etc/passwd.html")


def test_validate_name_rejects_slash():
    with pytest.raises(InvalidName):
        validate_name("sub/dir.html")


def test_validate_name_rejects_non_html_suffix():
    with pytest.raises(InvalidName):
        validate_name("notes.md")


def test_validate_name_rejects_no_suffix():
    with pytest.raises(InvalidName):
        validate_name("design")


def test_validate_name_rejects_special_chars():
    with pytest.raises(InvalidName):
        validate_name("design page.html")
    with pytest.raises(InvalidName):
        validate_name("中文.html")
    with pytest.raises(InvalidName):
        validate_name("design\npage.html")


# --- upload ------------------------------------------------------------------

def test_upload_writes_file_atomically(tmp_path):
    docroot = tmp_path / "notes"
    docroot.mkdir()
    info = upload(docroot, "design.html", "<html><title>x</title></html>",
                  max_size=10_000)
    assert (docroot / "design.html").exists()
    assert (docroot / "design.html").read_text() == "<html><title>x</title></html>"
    assert info.name == "design.html"
    assert info.size > 0
    # No tmp left behind
    assert not (docroot / "design.html.tmp").exists()


def test_upload_returns_title(tmp_path):
    docroot = tmp_path / "notes"
    docroot.mkdir()
    info = upload(docroot, "design.html", "<html><head><title>My Doc</title>",
                  max_size=10_000)
    assert info.title == "My Doc"


def test_upload_returns_none_title_when_missing(tmp_path):
    docroot = tmp_path / "notes"
    docroot.mkdir()
    info = upload(docroot, "design.html", "<html><body>x</body></html>",
                  max_size=10_000)
    assert info.title is None


def test_upload_chmod_0644(tmp_path):
    docroot = tmp_path / "notes"
    docroot.mkdir()
    upload(docroot, "design.html", "<html></html>", max_size=10_000)
    mode = (docroot / "design.html").stat().st_mode
    assert mode & 0o777 == 0o644


def test_upload_rejects_invalid_name(tmp_path):
    docroot = tmp_path / "notes"
    docroot.mkdir()
    with pytest.raises(InvalidName):
        upload(docroot, "../escape.html", "x", max_size=10_000)


def test_upload_rejects_missing_docroot(tmp_path):
    with pytest.raises(DocrootUnwritable):
        upload(tmp_path / "nope", "design.html", "x", max_size=10_000)


def test_upload_rejects_non_dir_docroot(tmp_path):
    f = tmp_path / "afile"
    f.write_text("x")
    with pytest.raises(DocrootUnwritable):
        upload(f, "design.html", "x", max_size=10_000)


def test_upload_rejects_too_large(tmp_path):
    docroot = tmp_path / "notes"
    docroot.mkdir()
    big = "x" * 11  # exceeds max_size=10
    with pytest.raises(TooLarge, match="exceeds max_file_size"):
        upload(docroot, "design.html", big, max_size=10)


def test_upload_rejects_conflict_without_force(tmp_path):
    docroot = tmp_path / "notes"
    docroot.mkdir()
    upload(docroot, "design.html", "first", max_size=10_000)
    with pytest.raises(Conflict):
        upload(docroot, "design.html", "second", max_size=10_000)


def test_upload_force_overwrites(tmp_path):
    docroot = tmp_path / "notes"
    docroot.mkdir()
    upload(docroot, "design.html", "first", max_size=10_000)
    info = upload(docroot, "design.html", "second", max_size=10_000, force=True)
    assert (docroot / "design.html").read_text() == "second"
    assert info.size == len("second")


def test_upload_case_insensitive_conflict(tmp_path):
    """DESIGN.HTML and design.html are the same file."""
    docroot = tmp_path / "notes"
    docroot.mkdir()
    upload(docroot, "DESIGN.HTML", "first", max_size=10_000)
    with pytest.raises(Conflict):
        upload(docroot, "design.html", "second", max_size=10_000)


def test_upload_case_insensitive_conflict_with_force(tmp_path):
    docroot = tmp_path / "notes"
    docroot.mkdir()
    upload(docroot, "DESIGN.HTML", "first", max_size=10_000)
    upload(docroot, "design.html", "second", max_size=10_000, force=True)
    assert (docroot / "DESIGN.HTML").read_text() == "second"


def test_upload_empty_content_writes_zero_byte_file(tmp_path):
    docroot = tmp_path / "notes"
    docroot.mkdir()
    info = upload(docroot, "design.html", "", max_size=10_000)
    assert (docroot / "design.html").exists()
    assert info.size == 0


def test_upload_cleans_tmp_on_disk_full(tmp_path, monkeypatch):
    """If the atomic replace fails, the .tmp is cleaned up."""
    docroot = tmp_path / "notes"
    docroot.mkdir()

    # Simulate replace() failure.
    def boom(*args, **kwargs):
        raise OSError("simulated disk full")

    monkeypatch.setattr("os.replace", boom)

    with pytest.raises(OSError):
        upload(docroot, "design.html", "x", max_size=10_000)
    assert not (docroot / "design.html.tmp").exists()


def test_upload_rejects_symlink_escape(tmp_path):
    """Even with a valid name, a symlink in docroot pointing outside is rejected."""
    docroot = tmp_path / "notes"
    docroot.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.html").write_text("secret")

    # Plant a symlink INSIDE docroot pointing OUTSIDE.
    link = docroot / "escape.html"
    link.symlink_to(outside / "secret.html")

    with pytest.raises(InvalidName, match="outside docroot"):
        upload(docroot, "escape.html", "x", max_size=10_000)


# --- list_files --------------------------------------------------------------

def test_list_files_empty(tmp_path):
    docroot = tmp_path / "notes"
    docroot.mkdir()
    assert list_files(docroot) == []


def test_list_files_skips_non_html(tmp_path):
    docroot = tmp_path / "notes"
    docroot.mkdir()
    (docroot / "readme.txt").write_text("hi")
    (docroot / "design.html").write_text("<title>X</title>")
    files = list_files(docroot)
    assert [f.name for f in files] == ["design.html"]


def test_list_files_returns_size_mtime_title(tmp_path):
    docroot = tmp_path / "notes"
    docroot.mkdir()
    (docroot / "a.html").write_text("<title>A</title>hello")
    (docroot / "b.html").write_text("<title>B</title>world")

    files = list_files(docroot)
    by_name = {f.name: f for f in files}
    assert set(by_name) == {"a.html", "b.html"}
    assert by_name["a.html"].size == len("<title>A</title>hello")
    assert by_name["a.html"].title == "A"
    assert by_name["b.html"].title == "B"
    # mtime is a sane recent unix timestamp
    assert by_name["a.html"].mtime > 0


def test_list_files_handles_binary_gracefully(tmp_path):
    """A non-UTF-8 file in docroot must not crash list_files."""
    docroot = tmp_path / "notes"
    docroot.mkdir()
    (docroot / "binary.html").write_bytes(b"\xff\xfe\x00bad")
    files = list_files(docroot)
    assert len(files) == 1
    assert files[0].title is None


def test_list_files_returns_empty_for_missing_docroot(tmp_path):
    assert list_files(tmp_path / "nope") == []


def test_list_files_skips_subdirectories(tmp_path):
    """Files directly under docroot only; no recursion."""
    docroot = tmp_path / "notes"
    docroot.mkdir()
    sub = docroot / "sub"
    sub.mkdir()
    (sub / "deep.html").write_text("x")
    (docroot / "shallow.html").write_text("y")
    names = [f.name for f in list_files(docroot)]
    assert names == ["shallow.html"]


# --- delete ------------------------------------------------------------------

def test_delete_removes_file(tmp_path):
    docroot = tmp_path / "notes"
    docroot.mkdir()
    (docroot / "design.html").write_text("x")
    assert delete(docroot, "design.html") is True
    assert not (docroot / "design.html").exists()


def test_delete_returns_false_for_missing(tmp_path):
    docroot = tmp_path / "notes"
    docroot.mkdir()
    assert delete(docroot, "nope.html") is False


def test_delete_rejects_invalid_name(tmp_path):
    docroot = tmp_path / "notes"
    docroot.mkdir()
    with pytest.raises(InvalidName):
        delete(docroot, "../escape.html")


def test_delete_rejects_missing_docroot(tmp_path):
    with pytest.raises(DocrootUnwritable):
        delete(tmp_path / "nope", "design.html")


# --- FileInfo dataclass ------------------------------------------------------

def test_fileinfo_equality():
    a = FileInfo(name="x.html", size=10, mtime=100, title="T")
    b = FileInfo(name="x.html", size=10, mtime=100, title="T")
    assert a == b


def test_fileinfo_inequality_on_name():
    a = FileInfo(name="x.html", size=10, mtime=100, title="T")
    b = FileInfo(name="y.html", size=10, mtime=100, title="T")
    assert a != b