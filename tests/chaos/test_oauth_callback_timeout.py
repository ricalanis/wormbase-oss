"""Chaos: OAuth callback / install orchestrator times out.

Failure mode
------------
The Slack OAuth code-exchange (or the post-OAuth install orchestrator
that runs immediately after) times out — the upstream takes longer
than the configured budget. The plan calls this "Slack OAuth code
exchange times out (mock ``slack_sdk.web.WebClient.oauth_v2_access``
to hang past 30s)".

Architectural note: the OAuth code-exchange itself runs in the
TypeScript dashboard route at ``apps/dashboard/app/onboarding/oauth/
[platform]/callback/route.ts``. The Python-side equivalent — and the
worm-core invariant we can test deterministically from pytest — is
the post-callback ``POST /api/v1/installs`` orchestration, which is
where the install state actually lands. We exercise the same invariant
shape there:

    - A timeout / hang during the install orchestration must NOT
      leave a half-installed state.
    - The user-visible failure is a structured error, NOT a partial
      Person row + no Install row.
    - Retrying the install after the upstream heals must work clean.

Invariants the system MUST preserve
-----------------------------------
1. The HTTP handler returns a structured 5xx (or propagates a
   ``TimeoutError``) — the dashboard routes the user to
   ``/onboarding?error=oauth_timeout&hint=...`` from there.
2. NO half-installed state lands: when the orchestrator hits the
   timeout mid-chain (e.g. after writing the propose Person but
   before writing the install_completed row), the **per-PEVR**
   write that succeeded already is intact, but no Install row +
   no role grants land. The retry below proves the system can
   recover cleanly.
3. The retry from ``POST /api/v1/installs`` works clean once the
   upstream heals.

Failure-injection point
-----------------------
We patch ``write_actions.complete_install`` to raise
``asyncio.TimeoutError`` on the first call. The aiohttp handler does
not catch ``TimeoutError`` (only ``VerifyFailed`` / ``ValueError`` /
``ValidationError``), so the request errors. The retry call lets
``complete_install`` run normally and lands the full chain.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core.http_api import build_app
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger


API_TOKEN = "chaos-oauth-token"
TENANT_SLUG = "baseworm"


@pytest_asyncio.fixture
async def memory_ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest_asyncio.fixture
async def client(memory_ledger: InMemoryLedger) -> AsyncIterator[TestClient]:
    app = build_app(ledger=memory_ledger, api_token=API_TOKEN)
    server = TestServer(app)
    cli = TestClient(server)
    await cli.start_server()
    try:
        yield cli
    finally:
        await cli.close()


def _auth() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {API_TOKEN}",
        "X-Tenant-Slug": TENANT_SLUG,
    }


def _install_body() -> dict[str, Any]:
    return {
        "platform": "slack",
        "installer_email": "carol@x.co",
        "installer_name": "Carol Reyes",
        "installer_avatar_url": None,
        "platform_user_id": "UCAROL",
        "oauth_grant_ref": "vault://local-dev/abc123",
        "scopes": ["channels:read", "chat:write"],
        "bot_user_id": "UBOT",
    }


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


async def test_install_timeout_returns_error_no_half_state_then_retry_clean(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """An install-orchestrator timeout produces a 5xx-shaped error
    (no fake success), no half-installed state lands, and the next
    attempt runs clean."""
    company_id = tenant_to_uuid(TENANT_SLUG)

    rows_before = len(await memory_ledger.fetch(company_id))

    # Inject the failure: the orchestrator times out.
    timeout_exc = asyncio.TimeoutError(
        "slack oauth_v2_access hung past 30s; install rolled back",
    )

    with patch(
        "wormbase_core.http_api.write_actions.complete_install",
        new=AsyncMock(side_effect=timeout_exc),
    ):
        # The aiohttp handler doesn't catch TimeoutError; the test client
        # surfaces it as a 5xx response (or a propagated exception in
        # some aiohttp versions). Both shapes are honest "the user sees
        # an error, not a fake success".
        try:
            resp = await client.post(
                "/api/v1/installs",
                headers=_auth(),
                json=_install_body(),
            )
            status = resp.status
            body_text = await resp.text()
        except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
            # Some aiohttp test client versions propagate uncaught
            # exceptions to the caller. Treat that as a 5xx.
            if isinstance(exc, asyncio.TimeoutError):
                status = 500
                body_text = str(exc)
            else:
                # Re-raise unexpected exceptions.
                if "TimeoutError" not in repr(exc):
                    raise
                status = 500
                body_text = str(exc)

    # Invariant 1: status is 5xx (or the failure surfaced as a
    # propagated exception we caught and labelled 500). The dashboard
    # would map this to /onboarding?error=oauth_timeout.
    assert status >= 500, (
        f"expected 5xx error from install timeout; got {status} body="
        f"{body_text[:200]}"
    )

    # Invariant 2: NO half-installed state. The mocked
    # ``complete_install`` raised before any ledger writes, so the
    # ledger contents are byte-identical to pre-attempt.
    rows_after = await memory_ledger.fetch(company_id)
    assert len(rows_after) == rows_before, (
        "no half-installed state — when the install orchestrator times "
        f"out, NO ledger entries land; got delta="
        f"{len(rows_after) - rows_before}"
    )

    # Invariant 3: the retry runs clean once the upstream heals.
    # We exit the patch context (above) so the real complete_install
    # runs. Re-issue the same install request.
    retry = await client.post(
        "/api/v1/installs",
        headers=_auth(),
        json=_install_body(),
    )
    assert retry.status == 201, await retry.text()
    retry_body = await retry.json()
    assert UUID(retry_body["install_id"])
    assert UUID(retry_body["installer_person_id"])

    # The retry writes the full install chain (5 PEVR cycles + 4 lake
    # cycles = 36 entries; mirrors test_post_installs_happy_path).
    rows_final = await memory_ledger.fetch(company_id)
    assert len(rows_final) == 36, (
        f"clean retry must produce the canonical 36-entry install chain; "
        f"got {len(rows_final)}"
    )

    # Invariant 2 cont'd: the install orchestrator's first row is
    # ``emit_person_proposed`` for the installer. There is no orphaned
    # PEVR cycle from a previous attempt — every entry belongs to the
    # successful retry.
    exec_tools = [
        r["payload"]["tool"] for r in rows_final
        if r["kind"] == "execute"
    ]
    assert exec_tools[0] == "emit_person_proposed"
    assert exec_tools.count("emit_install_completed") == 1
    assert exec_tools.count("emit_person_proposed") == 1, (
        "exactly ONE installer Person was proposed — no leftover Person "
        "from the timed-out first attempt"
    )
