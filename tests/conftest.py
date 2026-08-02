"""Project-wide pytest fixtures.

The autouse fixture below enforces the basic principle:
    TESTS MUST NEVER WRITE TO THE USER'S REAL CONFIG FILES.

Any test that would touch the real `~/.config/agent-html-drop/` (the running
daemon's config.toml / token live there) would wedge the deployed service. So:

  1. agent-html-drop's path functions are redirected to tmp.
  2. Before the test exits, the real `~/.config/agent-html-drop/` is verified
     to be untouched (mtime + content hash match pre-test snapshot).

Tests that intentionally need to exercise real paths (e.g. a smoke e2e that
spawns the daemon under a tmp $HOME) manage their own isolation —
see tests/test_smoke.py, which never consults these path functions.
"""
import hashlib
import os
from pathlib import Path

import pytest


# Real paths we MUST NOT touch during tests. Tracked for integrity checks.
REAL_AGENT_HTML_DROP_CONFIG_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    / "agent-html-drop"
)


def _sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def _isolate_agent_html_drop_state(tmp_path: Path, monkeypatch, request):
    """Hard isolation for every test. NEVER touch real user configs.

    Opt out with `@pytest.mark.no_isolation` for tests that intentionally
    exercise the real path-resolution behavior (e.g. test_paths.py).
    """
    if "no_isolation" in request.keywords:
        yield None
        return

    # Snapshot the real config dir so we can verify it was not modified.
    p = REAL_AGENT_HTML_DROP_CONFIG_DIR
    snapshot = {
        "exists": p.exists(),
        "mtime": p.stat().st_mtime if p.exists() else None,
    }

    # Redirect agent-html-drop's own paths into tmp.
    from agent_html_drop import paths as ahd_paths

    cfg_dir = tmp_path / "agent-html-drop-cfg"
    cfg_dir.mkdir()
    cfg_p = cfg_dir / "config.toml"
    nginx_p = cfg_dir / "nginx.conf.example"
    monkeypatch.setattr(ahd_paths, "config_dir", lambda: cfg_dir)
    monkeypatch.setattr(ahd_paths, "config_file", lambda: cfg_p)
    monkeypatch.setattr(ahd_paths, "nginx_example_file", lambda: nginx_p)

    paths_dict = {
        "agent_html_drop_config_dir": cfg_dir,
        "agent_html_drop_config_file": cfg_p,
        "agent_html_drop_nginx_example": nginx_p,
    }
    yield paths_dict

    # Integrity check: the real config dir must be untouched.
    if snapshot["exists"]:
        assert p.exists(), (
            "Test deleted real config at {}!".format(p)
        )
        assert p.stat().st_mtime == snapshot["mtime"], (
            "Test modified mtime of real config dir {} — "
            "this would have wedged the deployed agent-html-drop service!".format(p)
        )
