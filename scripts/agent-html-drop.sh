#!/usr/bin/env bash
# agent-html-drop service control: start | stop | restart | status
#
# User-level process control — no sudo, no systemd, no dependency on a
# specific init system. Works on macOS + any modern Linux.
#
# State lives in $STATE_DIR (default ~/.config/agent-html-drop):
#   daemon.pid  — pid of the running `agent-html-drop serve`
#   daemon.log  — combined stdout+stderr from `agent-html-drop serve`
#
# Install: copy to somewhere on $PATH and chmod +x:
#     cp scripts/agent-html-drop.sh /usr/local/bin/agent-html-drop-service
#     chmod +x /usr/local/bin/agent-html-drop-service
#
# Usage:
#     agent-html-drop-service start      # background; logs to daemon.log
#     agent-html-drop-service stop       # SIGTERM, then SIGKILL after 5s
#     agent-html-drop-service restart    # stop + start
#     agent-html-drop-service status     # pid + uptime + port listener check
#     agent-html-drop-service install    # write bin/agent-html-drop wrapper + link completions
#     agent-html-drop-service uninstall  # remove wrapper + completion links
set -euo pipefail

# Shared install helpers (write_wrapper / do_install_tool / do_uninstall_tool).
# Sourced BEFORE the local log() below, so this script's timestamped log()
# overrides the plain one from _common.sh.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/_common.sh"

PROG="agent-html-drop"
SCRIPT_NAME="agent-html-drop-service"

STATE_DIR="${AGENT_HTML_DROP_STATE_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/agent-html-drop}"
PID_FILE="$STATE_DIR/daemon.pid"
LOG_FILE="$STATE_DIR/daemon.log"
HOST="${AGENT_HTML_DROP_HOST:-127.0.0.1}"
PORT="${AGENT_HTML_DROP_PORT:-}"
GRACE_SECONDS=5

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$*" >&2; }

# --- helpers --------------------------------------------------------------

# Resolve the port from config.toml if AGENT_HTML_DROP_PORT is unset, so status
# / restart reflect the same value the daemon was started with.
resolve_port() {
    if [ -n "$PORT" ]; then
        return 0
    fi
    local cfg="$STATE_DIR/config.toml"
    if [ -f "$cfg" ]; then
        local p
        p=$(grep -E '^[[:space:]]*port[[:space:]]*=' "$cfg" 2>/dev/null \
            | head -n1 | sed -E 's/.*=[[:space:]]*([0-9]+).*/\1/' || true)
        if [ -n "$p" ]; then
            PORT="$p"
            return 0
        fi
    fi
    PORT=8765
}

# Read pid from pidfile, or empty. No validation here.
read_pid() {
    [ -f "$PID_FILE" ] || return 0
    cat "$PID_FILE" 2>/dev/null || true
}

# Is the given pid alive and looks like our process?
pid_alive() {
    local pid="$1"
    [ -n "$pid" ] || return 1
    kill -0 "$pid" 2>/dev/null
}

# Best-effort: find a `agent-html-drop serve` pid listening on $PORT when
# the pidfile is missing/stale. Avoids forcing users to recover by hand
# after a hard crash.
pid_from_port() {
    if [ -z "$PORT" ]; then
        return 0
    fi
    # lsof is the most portable; ss/lsof both work but lsof ships on
    # macOS by default.
    if ! command -v lsof >/dev/null 2>&1; then
        return 0
    fi
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null | head -n1 || true
}

# --- subcommands ----------------------------------------------------------

cmd_start() {
    if [ ! -x "$(command -v "$PROG")" ]; then
        log "Error: '$PROG' not found on PATH. Run scripts/install.sh first."
        exit 1
    fi
    if [ ! -f "$STATE_DIR/config.toml" ]; then
        log "Error: no config at $STATE_DIR/config.toml; run '$PROG init' first."
        exit 1
    fi

    local existing
    existing=$(read_pid)
    if pid_alive "$existing"; then
        log "already running (pid=$existing)"
        exit 0
    fi
    if [ -f "$PID_FILE" ]; then
        log "removing stale pidfile (pid=$existing is not alive)"
        rm -f "$PID_FILE"
    fi

    resolve_port

    mkdir -p "$STATE_DIR"
    : >> "$LOG_FILE"

    # setsid (when present) puts the daemon in its own session so a
    # later SIGHUP on this shell doesn't reach it. On macOS setsid is
    # not part of the base system; we tolerate that and fall back to
    # nohup + & + disown, which is good enough.
    if command -v setsid >/dev/null 2>&1; then
        setsid nohup "$PROG" serve >>"$LOG_FILE" 2>&1 </dev/null &
    else
        nohup "$PROG" serve >>"$LOG_FILE" 2>&1 </dev/null &
    fi
    disown 2>/dev/null || true

    # Re-read pidfile written by agent-html-drop serve (or recover from port).
    # `agent-html-drop serve` does not write a pidfile itself, so we need to
    # discover the pid. Wait briefly for the listener to come up.
    local pid="" tries=0
    while [ $tries -lt 25 ]; do
        pid=$(pid_from_port)
        if [ -n "$pid" ]; then break; fi
        sleep 0.2
        tries=$((tries + 1))
    done

    if [ -z "$pid" ]; then
        # Last-ditch: scan recent children of this shell.
        pid=$(pgrep -f "agent_html_drop.__main__" 2>/dev/null | head -n1 || true)
        if [ -z "$pid" ]; then
            pid=$(pgrep -f "python3 -B -m agent_html_drop" 2>/dev/null | head -n1 || true)
        fi
    fi

    if [ -z "$pid" ]; then
        log "started, but couldn't discover pid; check $LOG_FILE"
        exit 1
    fi

    printf '%s\n' "$pid" > "$PID_FILE"
    log "started pid=$pid host=$HOST port=$PORT log=$LOG_FILE"
}

cmd_stop() {
    local pid
    pid=$(read_pid)
    if [ -z "$pid" ] || ! pid_alive "$pid"; then
        # Try to discover from port as a last resort.
        pid=$(pid_from_port)
    fi
    if [ -z "$pid" ] || ! pid_alive "$pid"; then
        log "not running"
        rm -f "$PID_FILE"
        return 0
    fi

    log "sending SIGTERM to pid=$pid"
    kill -TERM "$pid" 2>/dev/null || true

    local waited=0
    while pid_alive "$pid" && [ $waited -lt "$GRACE_SECONDS" ]; do
        sleep 1
        waited=$((waited + 1))
    done

    if pid_alive "$pid"; then
        log "still alive after ${GRACE_SECONDS}s; sending SIGKILL"
        kill -KILL "$pid" 2>/dev/null || true
        sleep 0.2
    fi

    rm -f "$PID_FILE"
    if pid_alive "$pid"; then
        log "failed to stop pid=$pid"
        exit 1
    fi
    log "stopped"
}

cmd_restart() {
    cmd_stop || true
    cmd_start
}

cmd_status() {
    resolve_port
    local pid
    pid=$(read_pid)
    if pid_alive "$pid"; then
        local started
        started=$(ps -o lstart= -p "$pid" 2>/dev/null | sed 's/^[[:space:]]*//' || true)
        log "running pid=$pid started='$started' port=$PORT"
        return 0
    fi
    if [ -f "$PID_FILE" ]; then
        log "stale pidfile (pid=$pid not alive); use start to recover"
        return 1
    fi
    pid=$(pid_from_port)
    if [ -n "$pid" ]; then
        log "no pidfile but port $PORT is held by pid=$pid (orphan)"
        return 1
    fi
    log "not running"
    return 3
}

# --- dispatch -------------------------------------------------------------

usage() {
    cat >&2 <<EOF
Usage: $SCRIPT_NAME {start|stop|restart|status|install|uninstall}

Service control:
  start      background; logs to daemon.log
  stop       SIGTERM, then SIGKILL after 5s
  restart    stop + start
  status     pid + uptime + port listener check

Install (manage ONE tool's wrapper + completions; does not touch shell rc):
  install    Write the $PROG wrapper ($BIN_DIR/$PROG) and link bash/fish completions.
  uninstall  Remove the $PROG wrapper and its completion symlinks.

Env:
  AGENT_HTML_DROP_STATE_DIR   default: \$HOME/.config/agent-html-drop
  AGENT_HTML_DROP_PORT        default: read from config.toml, else 8765
EOF
    exit 64
}

[ $# -ge 1 ] || usage
sub="$1"
shift || true

case "$sub" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_restart ;;
    status)  cmd_status ;;
    install)   do_install_tool "$PROG" ;;
    uninstall) do_uninstall_tool "$PROG" ;;
    -h|--help|help) usage ;;
    *) log "Unknown subcommand: $sub"; usage ;;
esac
