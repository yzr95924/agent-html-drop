# fish completion for agent-html-drop
#
# scripts/install.sh symlinks this file into ~/.config/fish/completions/.

function __fish_agent_html_drop_needs_command
    set -l cmd (commandline -opc)
    test (count $cmd) -le 1
end

function __fish_agent_html_drop_using_command
    set -l cmd (commandline -opc)
    test (count $cmd) -ge 2; and contains -- $cmd[2] $argv
end

# Disable file completions for the bare command — only our subcommands are valid.
complete -c agent-html-drop -f
complete -c agent-html-drop -n __fish_agent_html_drop_needs_command -a "init serve token config nginx-config status"

# init
complete -c agent-html-drop -n __fish_agent_html_drop_using_command init -l force -d "Overwrite existing config."

# serve
complete -c agent-html-drop -n __fish_agent_html_drop_using_command serve -l config -r -d "Path to config.toml."

# status (no options)

# nginx-config
complete -c agent-html-drop -n __fish_agent_html_drop_using_command nginx-config -l write -r -d "Write to file instead of stdout."

# token show | rotate
complete -c agent-html-drop -n __fish_agent_html_drop_using_command token -a "show rotate"
complete -c agent-html-drop -n "__fish_agent_html_drop_using_command token; and contains -- show (commandline -opc)" -d "Print the current bearer token"
complete -c agent-html-drop -n "__fish_agent_html_drop_using_command token; and contains -- rotate (commandline -opc)" -d "Generate a new token"

# config show | path | edit
complete -c agent-html-drop -n __fish_agent_html_drop_using_command config -a "show path edit"
complete -c agent-html-drop -n "__fish_agent_html_drop_using_command config; and contains -- show (commandline -opc)" -d "Print config (token masked)"
complete -c agent-html-drop -n "__fish_agent_html_drop_using_command config; and contains -- path (commandline -opc)" -d "Print config file path"
complete -c agent-html-drop -n "__fish_agent_html_drop_using_command config; and contains -- edit (commandline -opc)" -d "Open config in \$EDITOR"