#!/usr/bin/env bash
# Uninstall agent-html-drop — the tool wrapper + completions + the PATH block.
#
# Per-tool cleanup (bin/agent-html-drop wrapper + completion symlinks) is owned
# by scripts/agent-html-drop.sh uninstall. This script runs that, then strips
# the repo-global PATH marker block from the user's shell rc.
#
# Notes:
#   - Does NOT touch a legacy .venv/ — that was created by an earlier install
#     flow and is unrelated to current install. Clean it up manually if you
#     want it gone: `rm -rf .venv`.
#   - Does NOT touch user data under ~/.config/agent-html-drop/ (config.toml,
#     daemon.pid, daemon.log, etc.). Those are service data, not install
#     artifacts.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_DIR="$PROJECT_ROOT/scripts"
BIN_DIR="$PROJECT_ROOT/bin"

TOOLS=(
    "agent-html-drop"
)

# --- per-tool wrapper + completions -----------------------------------------

for tool in "${TOOLS[@]}"; do
    bash "$SCRIPT_DIR/$tool.sh" uninstall
done

# --- strip the shared PATH marker from shell rc -----------------------------

begin_marker="# agent-html-drop PATH begin"
end_marker="# agent-html-drop PATH end"

# Uses awk: print lines OUTSIDE the [begin, end] inclusive range.
strip_marker() {
    local rc_path="$1"
    [ ! -f "$rc_path" ] && return 0

    if grep -qxF "$begin_marker" "$rc_path"; then
        local tmp
        tmp="$(mktemp)"
        awk -v begin="$begin_marker" -v end="$end_marker" '
            $0 == begin      { in_block = 1; next }
            $0 == end        { in_block = 0; next }
            in_block         { next }
                          { print }
        ' "$rc_path" > "$tmp"
        mv "$tmp" "$rc_path"
        echo "Stripped PATH marker block ($begin_marker) from $rc_path"
    else
        echo "  $rc_path: no $begin_marker marker, skipping"
    fi
}

case "${SHELL:-}" in
    */zsh)
        strip_marker "$HOME/.zshrc"
        ;;
    */bash|*)
        strip_marker "$HOME/.bashrc"
        ;;
esac

cat <<EOF

Uninstalled.

  removed : ${TOOLS[@]/#/$BIN_DIR/}
  rc      : PATH marker stripped (per detected shell)

To uninstall without touching shell rc:
  scripts/agent-html-drop.sh uninstall

Restart your shell (or 'source ~/.bashrc' / '~/.zshrc') to drop the
PATH entry from the running session.
EOF
