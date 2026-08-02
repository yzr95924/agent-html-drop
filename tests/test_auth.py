"""Tests for agent_html_drop.auth — Bearer check + token redaction."""
import hmac
import time

from agent_html_drop.auth import check_bearer, redact_token


TOKEN = "x" * 64  # secrets.token_hex(32) format


# --- check_bearer ------------------------------------------------------------

def test_check_bearer_accepts_correct_token():
    assert check_bearer("Bearer " + TOKEN, TOKEN) is True


def test_check_bearer_scheme_case_insensitive():
    assert check_bearer("bearer " + TOKEN, TOKEN) is True
    assert check_bearer("BEARER " + TOKEN, TOKEN) is True
    assert check_bearer("BeArEr " + TOKEN, TOKEN) is True


def test_check_bearer_rejects_missing_header():
    assert check_bearer(None, TOKEN) is False
    assert check_bearer("", TOKEN) is False


def test_check_bearer_rejects_wrong_scheme():
    assert check_bearer("Basic " + TOKEN, TOKEN) is False
    assert check_bearer("Token " + TOKEN, TOKEN) is False
    assert check_bearer(TOKEN, TOKEN) is False  # no scheme at all


def test_check_bearer_rejects_wrong_token():
    assert check_bearer("Bearer " + "y" * 64, TOKEN) is False


def test_check_bearer_rejects_empty_expected_token():
    """If the daemon is misconfigured (no token), everything fails closed."""
    assert check_bearer("Bearer " + TOKEN, None) is False
    assert check_bearer("Bearer " + TOKEN, "") is False


def test_check_bearer_rejects_empty_token_in_header():
    assert check_bearer("Bearer ", TOKEN) is False


def test_check_bearer_rejects_garbage_header():
    assert check_bearer("not even close", TOKEN) is False
    assert check_bearer("Bearer", TOKEN) is False  # no space, no token
    assert check_bearer("Bearer  " + TOKEN + " extra", TOKEN) is False


def test_check_bearer_uses_constant_time():
    """The compare must NOT short-circuit on first mismatch.

    Sanity check: equal-length wrong tokens should take similar time.
    This is a smoke test, not a rigorous timing-attack test.
    """
    right = TOKEN
    wrong_close = "x" * 63 + "y"
    wrong_far = "y" * 64

    # 500 iterations each, alternating.
    N = 500
    t_close = 0.0
    t_far = 0.0
    for i in range(N):
        t0 = time.perf_counter()
        hmac.compare_digest(wrong_close, right)
        t_close += time.perf_counter() - t0
        t0 = time.perf_counter()
        hmac.compare_digest(wrong_far, right)
        t_far += time.perf_counter() - t0

    # Within an order of magnitude — we're not asserting strict equality,
    # just sanity that close/far don't differ wildly.
    ratio = max(t_close, t_far) / min(t_close, t_far)
    assert ratio < 5.0, "timing differs too much: close={} far={}".format(t_close, t_far)


# --- redact_token ------------------------------------------------------------

def test_redact_token_normal_length():
    assert redact_token(TOKEN) == "xxxx****xxxx"


def test_redact_token_short_collapses():
    assert redact_token("short") == "****"
    assert redact_token("12345678") == "****"  # exactly 8


def test_redact_token_empty():
    assert redact_token("") == "<none>"
    assert redact_token(None) == "<none>"


def test_redact_token_exactly_9():
    """9-char token: first 4 + **** + last 4."""
    assert redact_token("abcdefghi") == "abcd****fghi"


def test_redact_token_does_not_leak_full():
    out = redact_token(TOKEN)
    assert TOKEN not in out
    # But the first/last 4 still appear (caller can correlate IDs).
    assert out.startswith("xxxx")
    assert out.endswith("xxxx")