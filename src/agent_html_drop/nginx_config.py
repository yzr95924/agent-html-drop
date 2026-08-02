"""Render the bundled nginx server block template.

Template lives at ``assets/nginx.conf.template`` (relative to this
module). Three placeholders are substituted:

  - ``{{DOCROOT}}``        -> docroot from config (e.g. /var/www/notes)
  - ``{{PORT}}``           -> daemon's listen port
  - ``{{PUBLIC_BASE_URL}}``-> the public URL base (used as a header
                             comment; the user must edit ``server_name``
                             to match)

Design §7.3 / §12.
"""
import os
from typing import Optional


_HERE = os.path.dirname(__file__)
_TEMPLATE_PATH = os.path.join(_HERE, "assets", "nginx.conf.template")


def _load_template() -> str:
    with open(_TEMPLATE_PATH, encoding="utf-8") as f:
        return f.read()


def render(docroot: str, port: int, public_base_url: str) -> str:
    """Return the rendered nginx server block as a string."""
    tpl = _load_template()
    return (
        tpl
        .replace("{{DOCROOT}}", docroot)
        .replace("{{PORT}}", str(port))
        .replace("{{PUBLIC_BASE_URL}}", public_base_url)
    )


def render_to(
    out_path: str,
    docroot: str,
    port: int,
    public_base_url: str,
) -> str:
    """Render to ``out_path`` (creating parent dirs). Returns the rendered text.

    File is written 0600 — the template is not secret per se, but matching
    config.toml's permission avoids surprise.
    """
    rendered = render(docroot, port, public_base_url)
    parent = os.path.dirname(out_path) or "."
    os.makedirs(parent, exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(rendered)
    os.chmod(tmp, 0o600)
    os.replace(tmp, out_path)
    return rendered