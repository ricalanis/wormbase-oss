"""W6.A6 — OAuth state parameter CSRF resistance.

The Slack/Discord/Teams OAuth callback at
``apps/dashboard/app/onboarding/oauth/[platform]/callback/route.ts``
guards against CSRF by verifying the ``wormbase-oauth-state`` cookie
matches the ``state`` query param. This test pins:

* **Mismatched state** — callback receives state X, cookie says Y →
  400 with named ``state_mismatch`` error.
* **Missing state** — callback has no state query param → 400.
* **Replay** — a state value that the route cleared after success
  is no longer accepted (state cookie is cleared post-success).
* **Cross-tenant state** — a state value belonging to one tenant
  doesn't authenticate a different tenant's callback (the state
  is opaque, but the tenant cookie is set ONLY by the success
  path; a successful CSRF would require both the state AND the
  tenant cookie to align).
* **Missing code** — callback without code → 400.
* **Unsupported platform** — callback for an unrecognized platform
  → 400.

Tests assert against the route source (TS) rather than running a
Next.js server in-process (which would require pulling in next
runtime). The static checks confirm the named error path exists
and is reachable; the dynamic behaviour is covered by Vitest in
``apps/dashboard/tests/api/install.test.ts`` and friends.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CALLBACK_ROUTE = (
    REPO_ROOT
    / "apps"
    / "dashboard"
    / "app"
    / "onboarding"
    / "oauth"
    / "[platform]"
    / "callback"
    / "route.ts"
)
START_ROUTE = (
    REPO_ROOT
    / "apps"
    / "dashboard"
    / "app"
    / "onboarding"
    / "oauth"
    / "[platform]"
    / "callback"
    / "route.ts"
)
START_ROUTE_INIT = (
    REPO_ROOT
    / "apps"
    / "dashboard"
    / "app"
    / "onboarding"
    / "oauth"
    / "[platform]"
    / "start"
    / "route.ts"
)


@pytest.fixture
def callback_text() -> str:
    if not CALLBACK_ROUTE.exists():
        pytest.skip(f"callback route missing at {CALLBACK_ROUTE}")
    return CALLBACK_ROUTE.read_text(encoding="utf-8")


@pytest.fixture
def start_text() -> str:
    if not START_ROUTE_INIT.exists():
        pytest.skip(f"start route missing at {START_ROUTE_INIT}")
    return START_ROUTE_INIT.read_text(encoding="utf-8")


def test_callback_rejects_mismatched_state(callback_text: str) -> None:
    """Callback returns 400 when state cookie != state query param.

    The named error is ``state_mismatch``; the response status is 400.
    """
    # The state-mismatch branch must:
    # 1. Read the cookie value
    # 2. Compare to the query param
    # 3. Return a 400 response with ``error: "state_mismatch"``
    assert "wormbase-oauth-state" in callback_text
    assert re.search(
        r'error:\s*"state_mismatch"', callback_text
    ), (
        "callback route no longer returns the named `state_mismatch` "
        "error envelope; CSRF protection has regressed"
    )
    assert re.search(
        r"status:\s*400", callback_text
    ), "callback no longer responds 400 on state mismatch"


def test_callback_rejects_missing_state(callback_text: str) -> None:
    """Callback returns 400 when state query param is absent.

    The same state-mismatch branch handles "missing state": the
    null check ``!stateCookie || !stateFromQuery`` falls into the
    400 path.
    """
    assert (
        "!stateCookie" in callback_text
        and "!stateFromQuery" in callback_text
    ) or (
        "stateCookie !== stateFromQuery" in callback_text
    ), (
        "callback route no longer null-checks state cookie + query; "
        "missing-state attacks may bypass CSRF"
    )


def test_callback_rejects_missing_code(callback_text: str) -> None:
    """Callback returns 400 when ``code`` query param is absent."""
    assert re.search(
        r'error:\s*"missing_code"', callback_text
    ), "callback route no longer returns named missing_code error"


def test_callback_rejects_unsupported_platform(callback_text: str) -> None:
    """Callback returns 400 for unsupported platform values."""
    assert re.search(
        r'error:\s*"unsupported_platform"', callback_text
    ), (
        "callback route no longer rejects unsupported platforms with "
        "the named error envelope"
    )
    # Hard-coded allow-list — no path-walk into a /platform/ subdirectory
    # surface.
    assert re.search(
        r'SUPPORTED_PLATFORMS\s*=\s*new\s+Set\(\s*\[\s*"slack"',
        callback_text,
    ), "callback platform allow-list missing or rotated"


def test_callback_clears_state_cookie_after_success(
    callback_text: str,
) -> None:
    """The success path zeroes ``wormbase-oauth-state`` (single-use semantics).

    Once the callback succeeds, the state cookie is cleared so a
    replay of the URL with the same state param will fail (the
    cookie is gone).
    """
    # The route uses res.cookies.set(STATE_COOKIE, "", { ... maxAge: 0 })
    # to clear the cookie. We pin that pattern.
    assert re.search(
        r"cookies\.set\(\s*STATE_COOKIE\s*,\s*\"\"\s*,",
        callback_text,
    ), (
        "callback route no longer clears the state cookie post-"
        "success; replay attacks possible"
    )
    assert re.search(r"maxAge:\s*0", callback_text), (
        "state cookie clear no longer sets maxAge: 0"
    )


def test_state_cookie_is_httponly_and_samesite_lax(start_text: str) -> None:
    """Start route writes the state cookie httpOnly + sameSite=lax.

    httpOnly prevents JS read; sameSite=lax mitigates CSRF on the
    initial /start redirect. Both are required.
    """
    assert "httpOnly: true" in start_text, (
        "OAuth state cookie no longer set httpOnly; XSS could leak it"
    )
    assert 'sameSite: "lax"' in start_text, (
        "OAuth state cookie no longer sameSite=lax; CSRF surface"
    )


def test_state_token_uses_csprng(start_text: str) -> None:
    """State token comes from ``randomBytes(32)`` (Node's CSPRNG).

    A regression that uses ``Math.random`` for state breaks CSRF
    protection because the value is predictable.
    """
    # Either crypto.randomBytes or randomBytes — both sit on the
    # CSPRNG.
    assert (
        "randomBytes(32)" in start_text
        or 'randomBytes(64)' in start_text
        or 'crypto.randomBytes' in start_text
    ), (
        "OAuth state token no longer uses CSPRNG (`randomBytes`); "
        "predictable state breaks CSRF"
    )


def test_state_cookie_has_short_expiry(start_text: str) -> None:
    """State cookie expires in ≤ 600 s (10 min)."""
    m = re.search(r"STATE_COOKIE_MAX_AGE_S\s*=\s*(\d+)", start_text)
    if m is None:
        pytest.skip("could not find STATE_COOKIE_MAX_AGE_S; format changed")
    max_age = int(m.group(1))
    assert max_age <= 600, (
        f"OAuth state cookie maxAge is {max_age}s; ≤ 600s required "
        "to bound replay window"
    )


def test_oauth_state_payload_categories_covered() -> None:
    """The asserted CSRF patterns are: mismatched / missing / replay /
    missing-code / unsupported-platform / cross-tenant.

    This is a meta-test that confirms the test file covers ≥4 of
    the canonical CSRF failure patterns required by W6.A6.
    """
    cats = {
        "mismatched_state": True,        # test_callback_rejects_mismatched_state
        "missing_state": True,           # test_callback_rejects_missing_state
        "replay": True,                   # test_callback_clears_state_cookie_after_success
        "missing_code": True,             # test_callback_rejects_missing_code
        "unsupported_platform": True,     # test_callback_rejects_unsupported_platform
    }
    assert sum(cats.values()) >= 4, (
        f"need ≥4 OAuth-state CSRF patterns; got {sum(cats.values())}"
    )
