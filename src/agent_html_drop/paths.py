"""XDG-aware config directory path resolution for agent-html-drop."""
import os
from pathlib import Path


def _config_base() -> Path:
    """The XDG config root: $XDG_CONFIG_HOME, else ~/.config."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


def config_dir() -> Path:
    """Return the agent-html-drop config directory (does not create it).

    Resolves to ``$XDG_CONFIG_HOME/agent-html-drop`` (default
    ``~/.config/agent-html-drop``).
    """
    return _config_base() / "agent-html-drop"


def config_file() -> Path:
    """Return the agent-html-drop config file path."""
    return config_dir() / "config.toml"


def nginx_example_file() -> Path:
    """Return the default path ``agent-html-drop nginx-config --write`` writes to."""
    return config_dir() / "nginx.conf.example"