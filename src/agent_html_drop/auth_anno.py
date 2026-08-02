"""Browser-side auth for annotation write paths."""
import hashlib
import hmac
import time
from typing import Optional


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


def csrf_check(req_host: str, origin_header: Optional[str]) -> bool:
    """Allow a missing Origin or the HTTPS origin matching the request host."""
    if not origin_header:
        return True
    host_only = req_host.split(":", 1)[0]
    return origin_header == "https://" + host_only


def cookie_set_header(value: str, max_age: int = ANNO_COOKIE_MAX_AGE) -> str:
    """Format a secure annotation-session Set-Cookie value."""
    return (
        "{name}={value}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age={max_age}"
    ).format(name=ANNO_COOKIE_NAME, value=value, max_age=max_age)
