"""Tests for agent_html_drop.nginx_config — template loading + rendering.

The template is a *minimal reverse-proxy snippet* (design §15.3.3,
2026-08-02): the daemon serves /files/* itself, so nginx no longer aliases
a docroot, and TLS is the user's nginx's job (no ssl directives). The CLI
renders it with the daemon port + public_base_url substituted.
"""
import os

from agent_html_drop import nginx_config


def test_template_file_exists():
    assert os.path.isfile(nginx_config._TEMPLATE_PATH)


def test_render_substitutes_port():
    out = nginx_config.render(port=9999,
                              public_base_url="https://notes.example.com")
    assert "9999" in out
    assert "{{PORT}}" not in out


def test_render_substitutes_public_base_url():
    out = nginx_config.render(port=8765,
                              public_base_url="https://my.example.com")
    assert "https://my.example.com" in out
    assert "{{PUBLIC_BASE_URL}}" not in out


def test_render_contains_reverse_proxy_directives():
    out = nginx_config.render(port=8765,
                              public_base_url="https://notes.example.com")
    assert "location /mcp" in out
    assert "location /" in out            # catch-all proxy to the daemon
    assert "127.0.0.1:8765" in out


def test_render_is_minimal_no_docroot_alias_or_ssl():
    """Container-era snippet: daemon serves /files/*, nginx is a pure proxy."""
    out = nginx_config.render(port=8765,
                              public_base_url="https://notes.example.com")
    assert "alias" not in out             # no nginx docroot alias directive
    assert "listen 443 ssl" not in out    # TLS is the user's nginx's job
    assert "ssl_certificate" not in out


def test_render_mcp_block_streams():
    out = nginx_config.render(port=8765,
                              public_base_url="https://notes.example.com")
    mcp = out.split("location /mcp", 1)[1].split("}", 1)[0]
    assert "proxy_buffering off" in mcp
    assert "proxy_read_timeout 86400" in mcp


def test_render_does_not_munge_cookies():
    """Cookie attrs (Secure/HttpOnly/SameSite) are set by the daemon; the
    snippet passes Set-Cookie through untouched."""
    out = nginx_config.render(port=8765,
                              public_base_url="https://notes.example.com")
    assert "proxy_cookie_path" not in out


def test_nginx_template_includes_limit_req():
    out = nginx_config.render(port=8765,
                              public_base_url="https://notes.example.com")
    assert "limit_req_zone" in out
    assert "rate=10r/s" in out


def test_nginx_template_applies_limit_req_to_auth():
    out = nginx_config.render(port=8765,
                              public_base_url="https://notes.example.com")
    auth_block = out.split("location = /api/auth", 1)[1].split("}", 1)[0]
    assert "limit_req zone=auth" in auth_block


def test_nginx_template_applies_limit_req_to_annotations():
    out = nginx_config.render(port=8765,
                              public_base_url="https://notes.example.com")
    assert "location ~ ^/api/files/[^/]+/annotations" in out


def test_render_to_creates_file(tmp_path):
    out_path = str(tmp_path / "nginx.conf.example")
    nginx_config.render_to(out_path, port=9000,
                           public_base_url="https://x.example.com")
    assert os.path.isfile(out_path)
    text = open(out_path).read()
    assert "9000" in text
    assert "{{PORT}}" not in text


def test_render_to_creates_parent_dirs(tmp_path):
    out_path = str(tmp_path / "deep" / "nested" / "nginx.conf.example")
    nginx_config.render_to(out_path, port=1, public_base_url="https://x")
    assert os.path.isfile(out_path)


def test_render_to_chmod_0600(tmp_path):
    out_path = str(tmp_path / "nginx.conf.example")
    nginx_config.render_to(out_path, port=1, public_base_url="https://x")
    mode = os.stat(out_path).st_mode
    assert mode & 0o777 == 0o600


def test_render_to_does_not_leave_tmp(tmp_path):
    out_path = str(tmp_path / "nginx.conf.example")
    nginx_config.render_to(out_path, port=1, public_base_url="https://x")
    assert not os.path.exists(out_path + ".tmp")
