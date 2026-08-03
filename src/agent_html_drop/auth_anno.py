"""Browser-side auth for annotation write paths."""
import hashlib
import hmac
import time
from typing import Optional, Tuple


ANNO_COOKIE_NAME = "anno_session"
ANNO_COOKIE_MAX_AGE = 1800


def _sign(secret: bytes, payload: str) -> str:
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _get_secret() -> bytes:
    """Derive the cookie signing secret from the configured bearer token."""
    from agent_html_drop.config import load_config
    from agent_html_drop.paths import config_file

    cfg = load_config(config_file())
    return hashlib.sha256(
        b"anno-cookie-v1|" + cfg.token.encode("utf-8")
    ).digest()


def sign_cookie(token: str, max_age: int = ANNO_COOKIE_MAX_AGE) -> str:
    """Return a cookie value carrying the token, expiry, and HMAC."""
    expires = int(time.time()) + max_age
    payload = "{}|{}".format(token, expires)
    return "{}|{}".format(payload, _sign(_get_secret(), payload))


def verify_cookie(value: str) -> Optional[str]:
    """Return the token when the cookie is authentic and unexpired."""
    if not value:
        return None
    parts = value.split("|")
    if len(parts) != 3:
        return None
    token, expires_s, signature = parts
    expected = _sign(_get_secret(), "{}|{}".format(token, expires_s))
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        expires = int(expires_s)
    except ValueError:
        return None
    if expires <= int(time.time()):
        return None
    return token


def csrf_check(
    req_host: str,
    origin_header: Optional[str],
    allow_insecure: bool = False,
) -> bool:
    """Same-origin Origin check for annotation writes (design §8).

    Returns True when Origin is absent (non-browser / same-origin GET
    navigation) or it matches the request Host. HTTPS origins are always
    accepted; HTTP origins are accepted only when ``allow_insecure`` is set
    (plain-HTTP testing mode — see ``Config.allow_insecure_annotations``).

    Authority matching is port-tolerant: browsers omit default ports, so an
    Origin of ``https://host`` still matches a Host of ``host:443``. When
    both sides carry a port, the ports must agree.
    """
    if not origin_header:
        return True
    scheme, authority = _parse_origin(origin_header)
    if scheme is None:
        return False  # malformed Origin → reject
    if scheme == "https":
        scheme_ok = True
    elif scheme == "http":
        scheme_ok = allow_insecure
    else:
        scheme_ok = False
    if not scheme_ok:
        return False
    return _authority_matches(authority, req_host)


def _parse_origin(origin: str) -> Tuple[Optional[str], Optional[str]]:
    """Split an Origin header into (scheme, authority) or (None, None)."""
    if origin.startswith("https://"):
        return "https", origin[len("https://"):]
    if origin.startswith("http://"):
        return "http", origin[len("http://"):]
    return None, None


def _split_authority(authority: str) -> Tuple[str, Optional[str]]:
    """``host:port`` or ``host`` -> (host, port_or_None)."""
    if ":" in authority:
        host, port = authority.split(":", 1)
        return host, port
    return authority, None


def _authority_matches(origin_authority: str, req_host: str) -> bool:
    """True if Origin authority is the same host as the request Host header."""
    o_host, o_port = _split_authority(origin_authority)
    r_host, r_port = _split_authority(req_host)
    if o_host != r_host:
        return False
    if o_port is not None and r_port is not None and o_port != r_port:
        return False
    return True


def cookie_set_header(
    value: str,
    max_age: int = ANNO_COOKIE_MAX_AGE,
    secure: bool = True,
) -> str:
    """Format an annotation-session Set-Cookie value.

    ``secure`` toggles the ``Secure`` flag. It must be False only in the
    opt-in plain-HTTP testing mode (``Config.allow_insecure_annotations``):
    a Secure cookie can never be stored or sent over HTTP, so annotation
    login would silently fail over plain HTTP without this.
    """
    parts = ["{name}={value}".format(name=ANNO_COOKIE_NAME, value=value)]
    parts.append("HttpOnly")
    if secure:
        parts.append("Secure")
    parts.append("SameSite=Lax")
    parts.append("Path=/")
    parts.append("Max-Age={}".format(max_age))
    return "; ".join(parts)
