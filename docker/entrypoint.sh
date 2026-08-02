#!/bin/sh
# Container entrypoint for agent-html-drop (design §15.4).
#
# On first `serve`: seed a container-friendly config (host=0.0.0.0,
# docroot=/data/docroot, public_base_url=$PUBLIC_BASE_URL) with a freshly
# generated bearer token — using the project's own Config/save_config so the
# TOML is always well-formed and written atomically at 0600. The config lives
# under $XDG_CONFIG_HOME (=/data/config) so it persists on the bind-mounted
# ./data/config volume. Then exec the daemon.
#
# Privilege drop (§15.5): the image has no USER directive, so this starts as
# root. It chowns /data to the app uid, then re-execs itself as non-root
# `ahd` via gosu; the re-invoked copy skips the block below (id -u != 0) and
# runs the seed + daemon as ahd. Net: ./data works for any host-side owner,
# and the daemon never runs as root.
set -e

if [ "$(id -u)" = "0" ]; then
    chown -R 1000:1000 /data
    exec gosu ahd "$0" "$@"
fi

if [ "$1" = "serve" ] || [ $# -eq 0 ]; then
    mkdir -p "${AHD_DOCROOT:-/data/docroot}"
    python3 - <<'PY'
import os
import secrets
import sys

from agent_html_drop.config import Config, save_config
from agent_html_drop.paths import config_dir, config_file

cfg_path = config_file()
if not cfg_path.exists():
    os.makedirs(str(config_dir()), exist_ok=True)
    cfg = Config(
        host=os.environ.get("AHD_HOST", "0.0.0.0"),
        port=int(os.environ.get("AHD_PORT", "8765")),
        docroot=os.environ.get("AHD_DOCROOT", "/data/docroot"),
        public_base_url=os.environ.get("PUBLIC_BASE_URL", "http://localhost"),
        token=secrets.token_hex(32),
    )
    save_config(cfg_path, cfg)
    sys.stderr.write("agent-html-drop: generated config at {}\n".format(cfg_path))
    sys.stderr.write("agent-html-drop: bearer token: {}\n".format(cfg.token))
    sys.stderr.write(
        "(retrieve later: docker compose exec agent-html-drop "
        "agent-html-drop token show)\n"
    )
PY
fi

exec python3 -m agent_html_drop "$@"
