# bash completion for agent-html-drop(1)
#
# Loaded two ways by scripts/install.sh (both harmless if repeated):
#   - symlinked into ~/.local/share/bash-completion/completions/agent-html-drop
#   - sourced from the PATH marker block in ~/.bashrc

_agent_html_drop() {
    local cur prev cmd sub
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    cmd=""
    sub=""

    # Walk the completed words to establish context:
    #   cmd = init | serve | token | config | nginx-config | status
    #   sub = under `token` (show/rotate) or `config` (show/path/edit)
    local i w
    for (( i = 1; i < COMP_CWORD; i++ )); do
        w="${COMP_WORDS[i]}"
        case "$w" in
            init|serve|status|nginx-config)
                [ -z "$cmd" ] && cmd="$w"
                ;;
            token|config)
                [ -z "$cmd" ] && cmd="$w"
                ;;
            show|rotate)
                [ "$cmd" = "token" ] && [ -z "$sub" ] && sub="token-$w"
                [ "$cmd" = "config" ] && [ -z "$sub" ] && sub="config-$w"
                ;;
            path|edit)
                [ "$cmd" = "config" ] && [ -z "$sub" ] && sub="config-$w"
                ;;
        esac
    done

    if [ -z "$cmd" ]; then
        COMPREPLY=( $(compgen -W "init serve token config nginx-config status --version --help" -- "$cur") )
        return 0
    fi

    case "$cmd" in
        init)
            COMPREPLY=( $(compgen -W "--force --help" -- "$cur") )
            ;;
        serve)
            COMPREPLY=( $(compgen -W "--config --help" -- "$cur") )
            ;;
        status)
            COMPREPLY=( $(compgen -W "--help" -- "$cur") )
            ;;
        nginx-config)
            if [[ "$cur" == -* ]]; then
                COMPREPLY=( $(compgen -W "--write --help" -- "$cur") )
            else
                COMPREPLY=()
            fi
            ;;
        token)
            if [ -z "$sub" ]; then
                COMPREPLY=( $(compgen -W "show rotate --help" -- "$cur") )
            else
                COMPREPLY=( $(compgen -W "--help" -- "$cur") )
            fi
            ;;
        config)
            if [ -z "$sub" ]; then
                COMPREPLY=( $(compgen -W "show path edit --help" -- "$cur") )
            else
                COMPREPLY=( $(compgen -W "--help" -- "$cur") )
            fi
            ;;
    esac
    return 0
}

complete -F _agent_html_drop agent-html-drop