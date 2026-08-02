"""Tests for agent_html_drop.nginx_config — template loading + placeholder rendering."""
import os
import stat

from agent_html_drop import nginx_config


def test_template_file_exists():
    assert os.path.isfile(nginx_config._TEMPLATE_PATH)


def test_render_substitutes_docroot():
    out = nginx_config.render(docroot="/srv/notes", port=8765,
                              public_base_url="https://notes.example.com")
    assert "/srv/notes" in out
    assert "{{DOCROOT}}" not in out


def test_render_substitutes_port():
    out = nginx_config.render(docroot="/srv/notes", port=9999,
                              public_base_url="https://notes.example.com")
    assert "9999" in out
    assert "{{PORT}}" not in out


def test_render_substitutes_public_base_url():
    out = nginx_config.render(docroot="/srv/notes", port=8765,
                              public_base_url="https://my.example.com")
    assert "https://my.example.com" in out
    assert "{{PUBLIC_BASE_URL}}" not in out


def test_render_contains_expected_directives():
    out = nginx_config.render(docroot="/var/www/notes", port=8765,
                              public_base_url="https://notes.example.com")
    # The four key routing blocks
    assert "location /files/" in out
    assert "location /mcp" in out
    assert "location /api/" in out
    assert "location /" in out
    # Reverse-proxy points at our daemon
    assert "127.0.0.1:8765" in out
    # Files location points at docroot
    assert "/var/www/notes" in out


def test_nginx_template_sets_samesite_lax():
    text = nginx_config.render(docroot="/var/www/notes", port=8765,
                               public_base_url="https://notes.example.com")
    assert "proxy_cookie_path" in text
    assert "SameSite=Lax" in text


def test_nginx_template_includes_limit_req():
    text = nginx_config.render(docroot="/var/www/notes", port=8765,
                               public_base_url="https://notes.example.com")
    assert "limit_req_zone" in text
    assert "rate=10r/s" in text


def test_nginx_template_applies_limit_req_to_auth():
    text = nginx_config.render(docroot="/var/www/notes", port=8765,
                               public_base_url="https://notes.example.com")
    auth_block = text.split("location = /api/auth", 1)[1].split("}", 1)[0]
    assert "limit_req zone=auth" in auth_block


def test_nginx_template_applies_limit_req_to_annotations():
    text = nginx_config.render(docroot="/var/www/notes", port=8765,
                               public_base_url="https://notes.example.com")
    assert "location ~ ^/api/files/[^/]+/annotations" in text


def test_render_to_creates_file(tmp_path):
    out_path = str(tmp_path / "nginx.conf.example")
    nginx_config.render_to(out_path, docroot="/srv/n", port=9000,
                           public_base_url="https://x.example.com")
    assert os.path.isfile(out_path)
    text = open(out_path).read()
    assert "/srv/n" in text
    assert "9000" in text


def test_render_to_creates_parent_dirs(tmp_path):
    out_path = str(tmp_path / "deep" / "nested" / "nginx.conf.example")
    nginx_config.render_to(out_path, docroot="/x", port=1, public_base_url="https://x")
    assert os.path.isfile(out_path)


def test_render_to_chmod_0600(tmp_path):
    out_path = str(tmp_path / "nginx.conf.example")
    nginx_config.render_to(out_path, docroot="/x", port=1, public_base_url="https://x")
    mode = os.stat(out_path).st_mode
    assert mode & 0o777 == 0o600


def test_render_to_does_not_leave_tmp(tmp_path):
    out_path = str(tmp_path / "nginx.conf.example")
    nginx_config.render_to(out_path, docroot="/x", port=1, public_base_url="https://x")
    assert not os.path.exists(out_path + ".tmp")