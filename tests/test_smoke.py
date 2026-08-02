"""End-to-end smoke test for agent-html-drop.

Runs the full install → init → serve → MCP request → uninstall flow in
a tmp $HOME so we never touch the real user configs. Designed to catch
integration breakage (wrong import paths, missing route registration,
install/uninstall asymmetry) that the per-module tests would miss.
"""
import http.client
import json
import os
import shutil
import signal
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _wait_for_port(host: str, port: int, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.05)
    return False


@pytest.fixture
def isolated_env(tmp_path):
    """Copy repo to tmp; provide a fake $HOME; install in-place."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_repo = tmp_path / "repo"
    shutil.copytree(
        ROOT,
        fake_repo,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".venv", ".git", "__pycache__", ".pytest_cache", "*.egg-info",
        ),
    )
    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["SHELL"] = "/bin/bash"
    env["XDG_DATA_HOME"] = str(fake_home / ".local" / "share")
    env["XDG_CONFIG_HOME"] = str(fake_home / ".config")
    env["PATH"] = str(fake_repo / "bin") + os.pathsep + env.get("PATH", "")

    install_sh = str(fake_repo / "scripts" / "install.sh")
    r = subprocess.run(
        ["bash", install_sh], check=False, capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, f"install failed:\n{r.stderr}"

    yield {
        "home": fake_home,
        "repo": fake_repo,
        "env": env,
        "bin": fake_repo / "bin",
        "config_file": fake_home / ".config" / "agent-html-drop" / "config.toml",
        "docroot": fake_home / "docroot",
    }

    # Cleanup: kill any leftover daemon, then uninstall.
    subprocess.run(
        ["bash", str(fake_repo / "scripts" / "uninstall.sh")],
        check=False, capture_output=True, text=True, env=env,
    )


def _read_token(env):
    """Run `agent-html-drop token show` and return the bare token string."""
    r = subprocess.run(
        ["agent-html-drop", "token", "show"],
        check=False, capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _init(env, docroot):
    """Init config with a docroot pointing at our fake dir."""
    r = subprocess.run(
        ["agent-html-drop", "init", "--force"],
        check=False, capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    # Point docroot at a writable tmp path so upload/list/delete works.
    docroot.mkdir()
    # Patch config.toml to override the default docroot.
    config_file = env["HOME"] + "/.config/agent-html-drop/config.toml"
    text = Path(config_file).read_text()
    text = text.replace('docroot = "/var/www/notes"', f'docroot = "{docroot}"')
    Path(config_file).write_text(text)


@contextmanager
def _start_daemon(env, port):
    """Spawn `agent-html-drop serve` on the requested port; yield the Popen handle."""
    # Use a non-default port to avoid clashing with anything on 8765.
    proc = subprocess.Popen(
        ["agent-html-drop", "serve"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        if not _wait_for_port("127.0.0.1", port, timeout=5.0):
            stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            raise RuntimeError(
                f"daemon did not start within 5s on port {port}; stderr: {stderr}"
            )
        yield proc
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)


def _http_get(env, port, path, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        conn.request("GET", path, headers=headers or {})
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        conn.close()


def _http_post(env, port, path, body, headers=None):
    hdrs = {"Content-Length": str(len(body))}
    if headers:
        hdrs.update(headers)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        conn.request("POST", path, body=body, headers=hdrs)
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        conn.close()


def _http_delete(env, port, path, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        conn.request("DELETE", path, headers=headers or {})
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        conn.close()


def _choose_port():
    """Pick a free ephemeral port by opening then closing a socket."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# --- install → init → serve → MCP request → uninstall ----------------------

def test_full_install_to_uninstall_smoke(isolated_env):
    env = isolated_env["env"]
    docroot = isolated_env["docroot"]

    # Patch config to use our fake docroot, then start daemon on a free port.
    _init(env, docroot)
    port = _choose_port()
    # Tell the daemon to listen on the chosen port (config-driven).
    config_file = isolated_env["config_file"]
    text = config_file.read_text()
    text = text.replace("port = 8765", f"port = {port}")
    config_file.write_text(text)

    token = _read_token(env)
    assert len(token) == 64
    auth = "Bearer " + token

    with _start_daemon(env, port):
        # 1. /api/health — no auth.
        status, _, body = _http_get(env, port, "/api/health")
        assert status == 200
        assert json.loads(body)["status"] == "ok"

        # 2. List empty docroot.
        status, _, body = _http_get(env, port, "/api/files", headers={"Authorization": auth})
        assert status == 200
        assert json.loads(body)["files"] == []

        # 3. Upload via MCP.
        upload_msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "upload_html",
                "arguments": {
                    "name": "design.html",
                    "content": "<html><head><title>My Design</title></head><body>hi</body></html>",
                },
            },
        }).encode("utf-8")
        status, _, body = _http_post(
            env, port, "/mcp", upload_msg,
            headers={"Authorization": auth, "Content-Type": "application/json"},
        )
        assert status == 200
        payload = json.loads(body)
        assert payload["result"]["isError"] is False
        inner = json.loads(payload["result"]["content"][0]["text"])
        assert inner["name"] == "design.html"
        assert inner["url"].endswith("/design.html")

        # Verify file landed on disk.
        on_disk = docroot / "design.html"
        assert on_disk.exists()
        assert "My Design" in on_disk.read_text()

        # 4. List shows the file.
        status, _, body = _http_get(env, port, "/api/files", headers={"Authorization": auth})
        assert status == 200
        listed = json.loads(body)["files"]
        names = [f["name"] for f in listed]
        assert "design.html" in names

        # 5. Delete via MCP.
        del_msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "delete_html",
                "arguments": {"name": "design.html"},
            },
        }).encode("utf-8")
        status, _, body = _http_post(
            env, port, "/mcp", del_msg,
            headers={"Authorization": auth, "Content-Type": "application/json"},
        )
        assert status == 200
        assert json.loads(body)["result"]["isError"] is False

        assert not (docroot / "design.html").exists()

        # 6. /api/files empty again.
        status, _, body = _http_get(env, port, "/api/files", headers={"Authorization": auth})
        assert json.loads(body)["files"] == []

    # Cleanup happens in fixture teardown (runs uninstall.sh). The
    # dedicated test_install.uninstall tests cover that contract.


def test_install_uninstall_smoke(isolated_env):
    """Pure install/uninstall round-trip — daemon not exercised."""
    env = isolated_env["env"]
    bin_dir = isolated_env["bin"]

    # Pre: wrapper exists.
    assert (bin_dir / "agent-html-drop").exists()

    # Manually re-run uninstall (fixture teardown will do it again, idempotent).
    r = subprocess.run(
        ["bash", str(isolated_env["repo"] / "scripts" / "uninstall.sh")],
        check=False, capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr

    assert not (bin_dir / "agent-html-drop").exists()


def test_nginx_config_smoke(isolated_env):
    """`agent-html-drop nginx-config` works end-to-end via the installed wrapper."""
    env = isolated_env["env"]
    # Force-create a config (init was not called by this test's fixture user).
    subprocess.run(
        ["agent-html-drop", "init", "--force"],
        check=False, capture_output=True, text=True, env=env,
    )

    r = subprocess.run(
        ["agent-html-drop", "nginx-config"],
        check=False, capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    text = r.stdout
    assert "server {" in text
    assert "listen 443 ssl" in text
    assert "{{" not in text  # all placeholders replaced


def test_status_smoke(isolated_env):
    env = isolated_env["env"]
    r = subprocess.run(
        ["agent-html-drop", "status"],
        check=False, capture_output=True, text=True, env=env,
    )
    assert r.exit_code == 0 if hasattr(r, "exit_code") else r.returncode == 0
    text = r.stdout
    assert "config path" in text
    # If init was never called, config won't exist.
    assert "exists" in text