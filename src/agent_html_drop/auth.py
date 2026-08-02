"""Bearer token check + log redaction.

Pure logic — no I/O, no daemon state. The HTTP layer extracts the
``Authorization`` header and hands the raw value to ``check_bearer``.

Why a function instead of a method on a config object: keeps auth
testable in isolation, and lets ``mcp_handler`` / ``api`` / future
internal callers all share one verifier.

Constant-time comparison (via ``hmac.compare_digest``) blocks trivial
timing-based token guessing.
"""
import hmac
from typing import Optional


_BEARER_PREFIX = "bearer"


def check_bearer(auth_header: Optional[str], expected_token: Optional[str]) -> bool:
    """Return True iff ``auth_header`` is a Bearer carrying exactly ``expected_token``.

    Returns False on missing header, wrong scheme, malformed value, or
    mismatched token. ``expected_token`` being None / empty also returns
    False — the daemon cannot serve if no token is configured.
    """
    if not expected_token:
        return False
    if not auth_header:
        return False
    parts = auth_header.split(" ", 1)
    if len(parts) != 2:
        return False
    if parts[0].lower() != _BEARER_PREFIX:
        return False
    # Constant-time comparison.
    return hmac.compare_digest(parts[1], expected_token)


def redact_token(token: Optional[str]) -> str:
    """Return a log-safe representation of ``token``.

    Format: first 4 + ``****`` + last 4. Tokens shorter than 9 chars
    collapse to ``****`` (don't leak length either).
    """
    if not token:
        return "<none>"
    if len(token) <= 8:
        return "****"
    return "{}{}{}".format(token[:4], "****", token[-4:])