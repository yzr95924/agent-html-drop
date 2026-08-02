"""Tests for agent_html_drop.cli — 9 subcommands via the local runner."""
import os
from pathlib import Path

import pytest

from agent_html_drop.config import load_config
from _cli_runner import invoke


@pytest.fixture
def paths_(_isolate_agent_html_drop_state):
    return _isolate_agent_html_drop_state


# --- init --------------------------------------------------------------------

def test_init_creates_config(paths_):
    cfg = paths_["agent_html_drop_config_file"]
    assert not cfg.exists()
    r = invoke(["init"])
    assert r.exit_code == 0, r.stderr
    assert cfg.exists()
    text = cfg.read_text()
    assert "[auth]" in text
    assert "token" in text


def test_init_generates_64_hex_token(paths_):
    cfg = paths_["agent_html_drop_config_file"]
    invoke(["init"])
    c = load_config(cfg)
    assert c.token is not None
    assert len(c.token) == 64
    int(c.token, 16)  # parseable as hex


def test_init_refuses_to_overwrite(paths_):
    cfg = paths_["agent_html_drop_config_file"]
    invoke(["init"])
    original = cfg.read_text()
    r = invoke(["init"])
    assert r.exit_code == 1
    assert cfg.read_text() == original


def test_init_force_overwrites(paths_):
    cfg = paths_["agent_html_drop_config_file"]
    invoke(["init"])
    first_token = load_config(cfg).token
    r = invoke(["init", "--force"])
    assert r.exit_code == 0
    second_token = load_config(cfg).token
    assert second_token is not None
    assert second_token != first_token


def test_init_creates_parent_dir(paths_):
    cfg = paths_["agent_html_drop_config_file"]
    if cfg.parent.exists():
        # autouse fixture made it — that's fine.
        pass
    r = invoke(["init"])
    assert r.exit_code == 0
    assert cfg.parent.is_dir()


# --- token show / rotate -----------------------------------------------------

def test_token_show_prints_token(paths_):
    invoke(["init"])
    r = invoke(["token", "show"])
    assert r.exit_code == 0
    token = load_config(paths_["agent_html_drop_config_file"]).token
    assert r.stdout.strip() == token


def test_token_show_fails_without_config(paths_):
    r = invoke(["token", "show"])
    assert r.exit_code == 1


def test_token_rotate_changes_token(paths_):
    invoke(["init"])
    first = load_config(paths_["agent_html_drop_config_file"]).token
    r = invoke(["token", "rotate"])
    assert r.exit_code == 0
    second = load_config(paths_["agent_html_drop_config_file"]).token
    assert second != first
    assert r.stdout.strip().endswith(second)


def test_token_rotate_fails_without_config(paths_):
    r = invoke(["token", "rotate"])
    assert r.exit_code == 1


# --- config show / path / edit ----------------------------------------------

def test_config_path_prints_path(paths_):
    r = invoke(["config", "path"])
    assert r.exit_code == 0
    assert r.stdout.strip() == str(paths_["agent_html_drop_config_file"])


def test_config_show_masks_token(paths_):
    invoke(["init"])
    r = invoke(["config", "show"])
    assert r.exit_code == 0
    real_token = load_config(paths_["agent_html_drop_config_file"]).token
    assert real_token not in r.stdout
    assert "****" in r.stdout


def test_config_show_fails_without_config(paths_):
    r = invoke(["config", "show"])
    assert r.exit_code == 1


def test_config_edit_exec_with_editor(monkeypatch, paths_):
    """`config edit` execs $EDITOR on the config path (mocked to record)."""
    invoke(["init"])
    editor = paths_["agent_html_drop_config_dir"] / "fake-editor.sh"
    editor.write_text("#!/bin/sh\necho $1 > {}/called.txt\n".format(paths_["agent_html_drop_config_dir"]))
    editor.chmod(0o755)
    monkeypatch.setenv("EDITOR", str(editor))

    # Mock os.execvp to record args instead of replacing the test process.
    calls = []
    def fake_execvp(file, args):
        calls.append((file, list(args)))
    monkeypatch.setattr("os.execvp", fake_execvp)

    invoke(["config", "edit"])
    assert calls, "os.execvp was never called"
    cmd, args = calls[0]
    assert cmd == str(editor)
    assert str(paths_["agent_html_drop_config_file"]) in args


def test_config_edit_creates_empty_when_missing(monkeypatch, paths_):
    cfg = paths_["agent_html_drop_config_file"]
    assert not cfg.exists()
    editor = paths_["agent_html_drop_config_dir"] / "fake-editor.sh"
    editor.write_text("#!/bin/sh\nexit 0\n")
    editor.chmod(0o755)
    monkeypatch.setenv("EDITOR", str(editor))

    calls = []
    monkeypatch.setattr("os.execvp", lambda *a: calls.append(a))
    invoke(["config", "edit"])
    assert cfg.exists()
    assert calls, "os.execvp was never called"


# --- nginx-config ------------------------------------------------------------

def test_nginx_config_prints_to_stdout(paths_):
    invoke(["init"])
    r = invoke(["nginx-config"])
    assert r.exit_code == 0
    text = r.stdout
    assert "server {" in text
    assert "listen 443 ssl" in text
    assert "{{" not in text  # all placeholders replaced


def test_nginx_config_writes_default_path(paths_):
    invoke(["init"])
    target = paths_["agent_html_drop_nginx_example"]
    r = invoke(["nginx-config", "--write"])
    assert r.exit_code == 0
    assert target.exists()
    text = target.read_text()
    assert "{{" not in text
    assert "server {" in text


def test_nginx_config_writes_custom_path(paths_):
    invoke(["init"])
    custom = paths_["agent_html_drop_config_dir"] / "my-nginx.conf"
    r = invoke(["nginx-config", "--write", str(custom)])
    assert r.exit_code == 0
    assert custom.exists()


def test_nginx_config_fails_without_config(paths_):
    r = invoke(["nginx-config"])
    assert r.exit_code == 1


# --- status ------------------------------------------------------------------

def test_status_works_without_config(paths_):
    r = invoke(["status"])
    assert r.exit_code == 0
    assert "config path" in r.stdout
    assert "exists" in r.stdout


def test_status_reports_docroot_status(paths_):
    invoke(["init"])
    r = invoke(["status"])
    assert r.exit_code == 0
    assert "docroot" in r.stdout
    assert "has token : yes" in r.stdout


# --- version -----------------------------------------------------------------

def test_version_flag(capsys):
    """`agent-html-drop --version` prints the version string."""
    import sys
    from agent_html_drop.cli import main
    try:
        main(["--version"])
    except SystemExit:
        pass
    captured = capsys.readouterr()
    assert captured.out.strip()  # non-empty


# --- error: no subcommand ----------------------------------------------------

def test_no_subcommand_exits_nonzero():
    r = invoke([])
    assert r.exit_code != 0