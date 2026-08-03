"""Tests for agent_html_drop.config — TOML config with unknown-field pass-through."""
import os
import pytest

from agent_html_drop.config import (
    Config,
    ConfigError,
    InvalidConfig,
    MissingConfigFile,
    load_config,
    save_config,
    validate_for_serve,
)


# --- load_config -------------------------------------------------------------

def test_load_config_raises_when_missing(tmp_path):
    with pytest.raises(MissingConfigFile):
        load_config(tmp_path / "config.toml")


def test_load_config_round_trip(tmp_path):
    p = tmp_path / "config.toml"
    cfg = Config(token="x" * 64, docroot="/srv/n", port=9000)
    save_config(p, cfg)

    loaded = load_config(p)
    assert loaded.token == "x" * 64
    assert loaded.docroot == "/srv/n"
    assert loaded.port == 9000


def test_load_config_preserves_unknown_top_level_keys(tmp_path):
    """Top-level keys agent-html-drop doesn't own round-trip via extra_top."""
    p = tmp_path / "config.toml"
    p.write_text(
        'host = "127.0.0.1"\n'
        'port = 8765\n'
        'docroot = "/var/www/notes"\n'
        'public_base_url = "https://notes.example.com"\n'
        'max_file_size = 52428800\n'
        'schema_version = 2\n'
        'custom_field = "hello"\n'
        '\n[auth]\ntoken = "x" * 64\n'.replace('"x" * 64', '"' + "x" * 64 + '"')
    )

    cfg = load_config(p)
    assert cfg.extra_top.get("schema_version") == 2
    assert cfg.extra_top.get("custom_field") == "hello"


def test_load_config_preserves_unknown_auth_keys(tmp_path):
    """Unknown [auth] keys round-trip via extra_auth."""
    p = tmp_path / "config.toml"
    p.write_text(
        'host = "127.0.0.1"\n'
        'port = 8765\n'
        'docroot = "/var/www/notes"\n'
        'public_base_url = "https://notes.example.com"\n'
        'max_file_size = 52428800\n'
        '\n[auth]\n'
        'token = "' + "x" * 64 + '"\n'
        'rotation_count = 3\n'
        'previous_token_hash = "abc"\n'
    )
    cfg = load_config(p)
    assert cfg.token == "x" * 64
    assert cfg.extra_auth.get("rotation_count") == 3
    assert cfg.extra_auth.get("previous_token_hash") == "abc"


def test_load_config_preserves_unknown_keys_after_save(tmp_path):
    """Round-trip: unknown keys survive a save/load cycle."""
    p = tmp_path / "config.toml"
    p.write_text(
        'host = "127.0.0.1"\n'
        'port = 8765\n'
        'docroot = "/var/www/notes"\n'
        'public_base_url = "https://notes.example.com"\n'
        'max_file_size = 52428800\n'
        'schema_version = 7\n'
        '\n[auth]\ntoken = "' + "x" * 64 + '"\n'
    )

    cfg = load_config(p)
    cfg.port = 9000  # mutate an owned field
    save_config(p, cfg)

    reloaded = load_config(p)
    assert reloaded.port == 9000
    assert reloaded.extra_top.get("schema_version") == 7


def test_load_config_rejects_non_int_port(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        'host = "127.0.0.1"\n'
        'port = "8765"\n'  # wrong type
        'docroot = "/var/www/notes"\n'
        'public_base_url = "https://notes.example.com"\n'
        'max_file_size = 52428800\n'
    )
    with pytest.raises(InvalidConfig):
        load_config(p)


def test_load_config_rejects_non_string_host(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        'host = 12345\n'  # wrong type
        'port = 8765\n'
        'docroot = "/var/www/notes"\n'
        'public_base_url = "https://notes.example.com"\n'
        'max_file_size = 52428800\n'
    )
    with pytest.raises(InvalidConfig):
        load_config(p)


# --- save_config -------------------------------------------------------------

def test_save_config_creates_parent_directory(tmp_path):
    p = tmp_path / "nested" / "config.toml"
    save_config(p, Config(token="x" * 64))
    assert p.exists()


def test_save_config_chmod_0600(tmp_path):
    p = tmp_path / "config.toml"
    save_config(p, Config(token="x" * 64))
    mode = stat_mode(p)
    # Owner read+write only; group/other none.
    assert mode & 0o777 == 0o600


def test_save_config_atomic(tmp_path, monkeypatch):
    """`.tmp` is replaced, never left behind on success."""
    p = tmp_path / "config.toml"
    save_config(p, Config(token="x" * 64))
    assert not (p.with_suffix(p.suffix + ".tmp")).exists()


def test_save_config_omits_auth_when_no_token(tmp_path):
    """An init-before-tokenize flow should still produce valid TOML."""
    p = tmp_path / "config.toml"
    save_config(p, Config())  # no token, no extra_auth
    text = p.read_text()
    assert "[auth]" not in text
    # But defaults are written
    assert "host" in text
    assert "port" in text


# --- validate_for_serve ------------------------------------------------------

def test_validate_for_serve_accepts_valid_config():
    cfg = Config(token="x" * 64)
    validate_for_serve(cfg)  # should not raise


def test_validate_for_serve_rejects_missing_token():
    cfg = Config()
    with pytest.raises(InvalidConfig, match="token is missing"):
        validate_for_serve(cfg)


def test_validate_for_serve_rejects_invalid_port():
    cfg = Config(token="x" * 64, port=0)
    with pytest.raises(InvalidConfig, match="port must be in 1..65535"):
        validate_for_serve(cfg)


def test_validate_for_serve_rejects_invalid_port_high():
    cfg = Config(token="x" * 64, port=99999)
    with pytest.raises(InvalidConfig, match="port must be in 1..65535"):
        validate_for_serve(cfg)


def test_validate_for_serve_rejects_zero_max_file_size():
    cfg = Config(token="x" * 64, max_file_size=0)
    with pytest.raises(InvalidConfig, match="max_file_size must be positive"):
        validate_for_serve(cfg)


def test_validate_for_serve_rejects_empty_docroot():
    cfg = Config(token="x" * 64, docroot="")
    with pytest.raises(InvalidConfig, match="docroot must be a non-empty"):
        validate_for_serve(cfg)


# --- allow_insecure_annotations ---------------------------------------------

def test_allow_insecure_annotations_defaults_false():
    cfg = Config(token="x" * 64)
    assert cfg.allow_insecure_annotations is False


def test_allow_insecure_annotations_round_trip(tmp_path):
    p = tmp_path / "config.toml"
    save_config(p, Config(token="x" * 64, allow_insecure_annotations=True))
    loaded = load_config(p)
    assert loaded.allow_insecure_annotations is True


def test_load_config_rejects_non_bool_allow_insecure(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        'host = "127.0.0.1"\n'
        'port = 8765\n'
        'docroot = "/var/www/notes"\n'
        'public_base_url = "https://notes.example.com"\n'
        'max_file_size = 52428800\n'
        'allow_insecure_annotations = "yes"\n'  # wrong type
    )
    with pytest.raises(InvalidConfig):
        load_config(p)


# --- helpers -----------------------------------------------------------------

def stat_mode(path):
    return os.stat(path).st_mode