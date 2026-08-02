"""Render the bundled nginx reverse-proxy snippet.

Template lives at ``assets/nginx.conf.template`` (relative to this
module). Two placeholders are substituted:

  - ``{{PORT}}``           -> daemon's listen port
  - ``{{PUBLIC_BASE_URL}}``-> the public URL base (informational header
                             comment)

Since 2026-08-02 (design §15.3.3) the snippet is a *pure reverse proxy*:
the daemon serves /files/* itself, so nginx no longer aliases a docroot
and TLS is the user's nginx's job. The ``{{DOCROOT}}`` placeholder is
gone with it.

Design §7.3 / §12 / §15.3.3.
"""
import os


_HERE = os.path.dirname(__file__)
_TEMPLATE_PATH = os.path.join(_HERE, "assets", "nginx.conf.template")


def _load_template() -> str:
    with open(_TEMPLATE_PATH, encoding="utf-8") as f:
        return f.read()


def render(port: int, public_base_url: str) -> str:
    """Return the rendered nginx reverse-proxy snippet as a string."""
    tpl = _load_template()
    return (
        tpl
        .replace("{{PORT}}", str(port))
        .replace("{{PUBLIC_BASE_URL}}", public_base_url)
    )


def render_to(
    out_path: str,
    port: int,
    public_base_url: str,
) -> str:
    """Render to ``out_path`` (creating parent dirs). Returns the rendered text.

    File is written 0600 — the template is not secret per se, but matching
    config.toml's permission avoids surprise.
    """
    rendered = render(port, public_base_url)
    parent = os.path.dirname(out_path) or "."
    os.makedirs(parent, exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(rendered)
    os.chmod(tmp, 0o600)
    os.replace(tmp, out_path)
    return rendered