"""agent-html-drop command-line interface.

Nine subcommands (design §7.3 / §12):

  init           create config dir + generate token
  serve          foreground daemon
  token show     print current bearer token
  token rotate   generate new token, save, hint about restart
  config show    print config (token redacted)
  config path    print config path
  config edit    $EDITOR on the config
  nginx-config   print (or --write) the nginx reverse-proxy snippet
  status         one-line report: config exists / token set / docroot exists

The CLI is a thin orchestrator — every subcommand defers to a focused
module (paths / config / storage / auth / mcp / api / ui / nginx_config
/ server).
"""
import argparse
import os
import secrets
import sys
from pathlib import Path
from typing import Optional

from agent_html_drop import api as api_mod
from agent_html_drop import mcp_handler
from agent_html_drop import nginx_config as nginx_mod
from agent_html_drop import paths
from agent_html_drop import server as srv
from agent_html_drop import ui as ui_mod
from agent_html_drop.auth import redact_token
from agent_html_drop.config import (
    Config,
    ConfigError,
    InvalidConfig,
    MissingConfigFile,
    load_config,
    save_config,
    validate_for_serve,
)

from ._version import VERSION


# --- subcommand handlers ----------------------------------------------------

def cmd_init(args) -> int:
    config_path = paths.config_file()
    if config_path.exists() and not args.force:
        print(
            "config already exists at {}; pass --force to overwrite".format(config_path),
            file=sys.stderr,
        )
        return 1
    config_path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(32)
    cfg = Config(token=token)
    save_config(config_path, cfg)
    print("Created config at: {}".format(config_path))
    print("")
    print("  Bearer token: {}".format(token))
    print("")
    print("Next steps:")
    print("  1. (Optional) edit {} to set docroot / public_base_url / port.".format(config_path))
    print("  2. Create the docroot if it doesn't exist:")
    print("       sudo mkdir -p /var/www/notes && sudo chown $USER /var/www/notes")
    print("  3. Render the nginx config:  agent-html-drop nginx-config --write")
    print("  4. Start the daemon:           agent-html-drop serve")
    return 0


def cmd_serve(args) -> int:
    config_path = Path(args.config) if args.config else paths.config_file()
    try:
        cfg = load_config(config_path)
    except MissingConfigFile as exc:
        print("Error: {}".format(exc), file=sys.stderr)
        return 2
    try:
        validate_for_serve(cfg)
    except InvalidConfig as exc:
        print("Error: invalid config: {}".format(exc), file=sys.stderr)
        return 2

    # Wire config into runtime.
    srv.Handler.max_body_size = cfg.max_file_size
    mcp_handler.register_route(cfg)
    api_mod.register_routes(cfg)
    ui_mod.register_routes()

    server = srv.make_server(cfg.host, cfg.port)
    print(
        "agent-html-drop v{}: serving on http://{}:{} (docroot={})".format(
            VERSION, cfg.host, cfg.port, cfg.docroot
        ),
        file=sys.stderr,
    )
    srv.install_signal_shutdown(server)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def cmd_token_show(_args) -> int:
    config_path = paths.config_file()
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        print("Error: {}".format(exc), file=sys.stderr)
        return 1
    if not cfg.token:
        print("No token configured; run `agent-html-drop init`.", file=sys.stderr)
        return 1
    print(cfg.token)
    return 0


def cmd_token_rotate(_args) -> int:
    config_path = paths.config_file()
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        print("Error: {}".format(exc), file=sys.stderr)
        return 1
    cfg.token = secrets.token_hex(32)
    save_config(config_path, cfg)
    print("Token rotated. Restart `agent-html-drop serve` to use the new token.")
    print("New token: {}".format(cfg.token))
    return 0


def cmd_config_show(_args) -> int:
    config_path = paths.config_file()
    if not config_path.exists():
        print(
            "No config at {}; run `agent-html-drop init` first.".format(config_path),
            file=sys.stderr,
        )
        return 1
    cfg = load_config(config_path)
    out = cfg.to_toml_dict()
    if isinstance(out.get("auth"), dict) and "token" in out["auth"]:
        out["auth"]["token"] = redact_token(out["auth"]["token"])
    from agent_html_drop._compat import toml_dump
    import io as _io
    buf = _io.StringIO()
    toml_dump(out, buf)
    print(buf.getvalue())
    return 0


def cmd_config_path(_args) -> int:
    print(str(paths.config_file()))
    return 0


def cmd_config_edit(_args) -> int:
    config_path = paths.config_file()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(
            "# Empty config. Run `agent-html-drop init` to populate defaults.\n",
            encoding="utf-8",
        )
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    os.execvp(editor, [editor, str(config_path)])
    # os.execvp does not return.


def cmd_nginx_config(args) -> int:
    config_path = paths.config_file()
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        print("Error: {}".format(exc), file=sys.stderr)
        return 1
    if args.write is None:
        # Print to stdout.
        print(nginx_mod.render(
            port=cfg.port,
            public_base_url=cfg.public_base_url,
        ))
        return 0
    # --write: empty string from `const` means default path.
    out_path = args.write if args.write else str(paths.nginx_example_file())
    nginx_mod.render_to(
        out_path,
        port=cfg.port,
        public_base_url=cfg.public_base_url,
    )
    print("Wrote {}".format(out_path), file=sys.stderr)
    return 0


def cmd_status(_args) -> int:
    config_path = paths.config_file()
    print("config path : {}".format(config_path))
    if config_path.exists():
        print("  exists    : yes")
        try:
            cfg = load_config(config_path)
            print("  has token : {}".format("yes" if cfg.token else "no"))
            print("  docroot   : {}".format(cfg.docroot))
            docroot_p = Path(cfg.docroot)
            if docroot_p.exists():
                print("  docroot exists: yes")
                print("  docroot writable: {}".format(
                    "yes" if os.access(str(docroot_p), os.W_OK) else "no"
                ))
            else:
                print("  docroot exists: NO (run `sudo mkdir -p {}`)".format(cfg.docroot))
            print("  port      : {} (listen on {})".format(cfg.port, cfg.host))
        except ConfigError as exc:
            print("  parse error: {}".format(exc))
    else:
        print("  exists    : NO (run `agent-html-drop init`)")
    return 0


# --- argparse wiring --------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-html-drop",
        description=(
            "HTTP MCP server + HTML management page for serving "
            "self-contained HTML on nginx."
        ),
    )
    parser.add_argument("--version", action="version", version=VERSION)

    sub = parser.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    # init
    p = sub.add_parser("init", help="Create config dir and generate a token.")
    p.add_argument("--force", action="store_true", help="Overwrite existing config.")
    p.set_defaults(func=cmd_init)

    # serve
    p = sub.add_parser("serve", help="Run the daemon in the foreground.")
    p.add_argument(
        "--config",
        help="Path to config.toml (default: ~/.config/agent-html-drop/config.toml).",
    )
    p.set_defaults(func=cmd_serve)

    # token show | rotate
    p = sub.add_parser("token", help="Show or rotate the bearer token.")
    token_sub = p.add_subparsers(dest="token_cmd", required=True, metavar="SUBCOMMAND")
    sp = token_sub.add_parser("show", help="Print the current token to stdout.")
    sp.set_defaults(func=cmd_token_show)
    sp = token_sub.add_parser("rotate", help="Generate a new token (daemon must be restarted).")
    sp.set_defaults(func=cmd_token_rotate)

    # config show | path | edit
    p = sub.add_parser("config", help="Inspect or edit the config.")
    config_sub = p.add_subparsers(dest="config_cmd", required=True, metavar="SUBCOMMAND")
    config_sub.add_parser("show", help="Print config (token masked).").set_defaults(func=cmd_config_show)
    config_sub.add_parser("path", help="Print the config file path.").set_defaults(func=cmd_config_path)
    config_sub.add_parser("edit", help="Open the config in $EDITOR.").set_defaults(func=cmd_config_edit)

    # nginx-config
    p = sub.add_parser(
        "nginx-config",
        help="Render the bundled nginx reverse-proxy snippet (stdout or --write).",
    )
    p.add_argument(
        "--write",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help=(
            "Write to file instead of stdout. "
            "Without PATH, writes to ~/.config/agent-html-drop/nginx.conf.example."
        ),
    )
    p.set_defaults(func=cmd_nginx_config)

    # status
    p = sub.add_parser("status", help="One-line report on config / token / docroot.")
    p.set_defaults(func=cmd_status)

    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())