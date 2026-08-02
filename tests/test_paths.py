"""Tests for agent_html_drop.paths — pure path resolution functions.

Marked ``no_isolation`` because these tests intentionally exercise the
real XDG / HOME resolution; they don't touch any state on disk beyond
tmp_path.
"""
import pytest

from agent_html_drop.paths import config_dir, config_file, nginx_example_file

pytestmark = pytest.mark.no_isolation


def test_config_dir_uses_xdg_config_home_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_dir() == tmp_path / "agent-html-drop"


def test_config_dir_defaults_to_home_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config_dir() == tmp_path / ".config" / "agent-html-drop"


def test_config_file_lives_under_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_file() == tmp_path / "agent-html-drop" / "config.toml"


def test_nginx_example_file_lives_under_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert nginx_example_file() == tmp_path / "agent-html-drop" / "nginx.conf.example"


def test_paths_do_not_create_directories(monkeypatch, tmp_path):
    """Path resolvers must not touch the filesystem."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _ = config_dir()
    _ = config_file()
    _ = nginx_example_file()
    assert not (tmp_path / "agent-html-drop").exists()