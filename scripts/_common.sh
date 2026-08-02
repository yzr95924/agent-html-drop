#!/usr/bin/env bash
# Shared install/uninstall helpers for the per-tool control script
# (scripts/agent-html-drop.sh).
#
# This file is a LIBRARY — source it, don't execute it directly:
#     SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#     . "$SCRIPT_DIR/_common.sh"
#
# It owns the per-tool piece of the install story: the bin/<tool> wrapper and
# the bash/fish completion symlinks. The REPO-GLOBAL piece (the idempotent
# PATH marker block in the user's shell rc) is owned by scripts/install.sh /
# scripts/uninstall.sh, which delegate here via the per-tool script. Keeping
# that split means `scripts/agent-html-drop.sh install` never touches your
# shell rc, and the rc block is added/removed exactly once.
#
# Not executable on its own; no shebang dispatch.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$PROJECT_ROOT/bin"
COMPLETION_SRC_DIR="$PROJECT_ROOT/completions"
BASH_COMPLETION_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/bash-completion/completions"
FISH_COMPLETION_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/fish/completions"

# Default logger. agent-html-drop.sh overrides this with a timestamped variant
# after sourcing.
log() { printf '>> %s\n' "$*" >&2; }

# kebab-case tool name -> python module name (agent-html-drop -> agent_html_drop).
tool_to_module() { printf '%s\n' "${1//-/_}"; }

# --- wrapper ----------------------------------------------------------------

write_wrapper() {
    local tool="$1" py_module
    py_module="$(tool_to_module "$tool")"
    mkdir -p "$BIN_DIR"
    cat > "$BIN_DIR/$tool" <<WRAPPER
#!/usr/bin/env bash
set -euo pipefail
REPO="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="\$REPO/src\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -B -m ${py_module} "\$@"
WRAPPER
    chmod +x "$BIN_DIR/$tool"
}

remove_wrapper() {
    rm -f "$BIN_DIR/$1"
}

# --- completions ------------------------------------------------------------

link_completion() {
    local src="$1" dest="$2"
    mkdir -p "$(dirname "$dest")"
    if [ -e "$dest" ] && [ ! -L "$dest" ]; then
        log "$dest exists and is not a symlink; leaving it alone"
        return 0
    fi
    ln -sfn "$src" "$dest"
    log "Linked completion: $dest -> $src"
}

# Remove a completion symlink ONLY if it points into this repo's completions/
# (so a user's own symlink/file at the same path is never clobbered).
remove_completion_link() {
    local dest="$1"
    if [ -L "$dest" ]; then
        case "$(readlink "$dest")" in
            "$COMPLETION_SRC_DIR"/*)
                rm -f "$dest"
                log "Removed completion link: $dest"
                ;;
            *)
                log "$dest points elsewhere, leaving it alone"
                ;;
        esac
    fi
}

install_completions_for() {
    local tool="$1"
    [ -f "$COMPLETION_SRC_DIR/$tool.bash" ] && \
        link_completion "$COMPLETION_SRC_DIR/$tool.bash" "$BASH_COMPLETION_DIR/$tool"
    [ -f "$COMPLETION_SRC_DIR/$tool.fish" ] && \
        link_completion "$COMPLETION_SRC_DIR/$tool.fish" "$FISH_COMPLETION_DIR/$tool.fish"
}

uninstall_completions_for() {
    local tool="$1"
    remove_completion_link "$BASH_COMPLETION_DIR/$tool"
    remove_completion_link "$FISH_COMPLETION_DIR/$tool.fish"
}

# --- entry points used by every per-tool script -----------------------------

do_install_tool() {
    local tool="$1"
    write_wrapper "$tool"
    log "Wrote wrapper: $BIN_DIR/$tool"
    install_completions_for "$tool"
}

do_uninstall_tool() {
    local tool="$1"
    remove_wrapper "$tool"
    log "Removed wrapper: $BIN_DIR/$tool"
    uninstall_completions_for "$tool"
}
