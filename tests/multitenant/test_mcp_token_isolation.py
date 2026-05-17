"""MCP token isolation across tenants.

INVARIANT: a Person-scoped MCP token T_A issued for tenant_a CAN NOT be
used to read tenant_b data, regardless of:

- the tenant slug claimed in headers,
- the ``company_id`` argument supplied to the MCP tool,
- request ordering (tenant_b call interleaved with tenant_a calls).

Rate-limit buckets per ``(token, tenant)`` pair MUST NOT bleed: a flood
of tenant_a calls under T_A must NOT consume tenant_b's budget under
the same caller key.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_core.mcp_tools.auth import (
    DEFAULT_RATE_LIMIT_PER_MIN,
    RateLimitExceeded,
    check_rate_limit,
    decode_compact_token,
    encode_compact_token,
    resolve_caller,
)
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger


API_TOKEN = "test-mt-mcp-secret"
TENANT_A_SLUG = "baseworm"
TENANT_B_SLUG = "democorp"


def _company_id(slug: str) -> UUID:
    return tenant_to_uuid(slug)


def _ctx_with(headers: dict[str, str]):
    """Build a fake FastMCP-style Context with the supplied headers."""

    class _H:
        def __init__(self, h: dict[str, str]) -> None:
            self.h = h

        def get(self, k: str) -> str | None:
            return self.h.get(k.lower()) or self.h.get(k)

    class _Req:
        def __init__(self, h: dict[str, str]) -> None:
            self.headers = _H(h)

    class _RC:
        def __init__(self, h: dict[str, str]) -> None:
            self.request = _Req(h)

    class _Ctx:
        def __init__(self, h: dict[str, str]) -> None:
            self.request_context = _RC(h)

    return _Ctx({k.lower(): v for k, v in headers.items()})


def _bearer_ctx(token: str, *, tenant_header: str | None = None):
    headers: dict[str, str] = {"authorization": f"Bearer {token}"}
    if tenant_header is not None:
        headers["x-tenant-slug"] = tenant_header
    return _ctx_with(headers)


# ---------------------------------------------------------------------------
# Token claim-binding: claims-tenant beats header-tenant.
# ---------------------------------------------------------------------------


def test_compact_token_tenant_claim_beats_header() -> None:
    """INVARIANT: when a compact token carries a ``tenant_slug`` claim, the
    resolver MUST use that slug — NOT a forged ``X-Tenant-Slug`` header
    pointing at a different tenant.
    """
    person = uuid4()
    token = encode_compact_token(
        secret=API_TOKEN,
        person_id=person,
        tenant_slug=TENANT_A_SLUG,
    )
    ctx = _bearer_ctx(token, tenant_header=TENANT_B_SLUG)
    pid, company_id, slug = resolve_caller(
        ctx, api_token=API_TOKEN, fallback_company_id=None,
    )
    assert pid == person
    assert slug == TENANT_A_SLUG
    assert company_id == _company_id(TENANT_A_SLUG)
    # Concretely: the resolved company_id is NOT tenant_b's.
    assert company_id != _company_id(TENANT_B_SLUG)


def test_compact_token_for_tenant_a_never_resolves_to_tenant_b() -> None:
    """INVARIANT: a token with claim ``tenant_slug=baseworm`` cannot be
    pointed at democorp by ANY combination of header tricks.
    """
    person = uuid4()
    token_a = encode_compact_token(
        secret=API_TOKEN,
        person_id=person,
        tenant_slug=TENANT_A_SLUG,
    )

    # Try every header combination: present + absent, lower + upper case,
    # and various spoof values.
    spoof_attempts = [
        {"x-tenant-slug": TENANT_B_SLUG},
        {"X-Tenant-Slug": TENANT_B_SLUG},
        {"x-tenant-slug": TENANT_B_SLUG.upper()},
        {"x-tenant-slug": "  democorp  "},
        {"x-tenant-slug": ""},
        {},
    ]
    for headers in spoof_attempts:
        h = {k.lower(): v for k, v in headers.items()}
        h["authorization"] = f"Bearer {token_a}"
        ctx = _ctx_with(h)
        _, company_id, slug = resolve_caller(
            ctx, api_token=API_TOKEN, fallback_company_id=None,
        )
        assert company_id == _company_id(TENANT_A_SLUG), (
            f"compact-token for tenant_a leaked into {slug!r} "
            f"(headers={headers})"
        )


# ---------------------------------------------------------------------------
# Wrong-key signing → token rejected at the gate.
# ---------------------------------------------------------------------------


def test_compact_token_signed_with_wrong_key_rejected() -> None:
    """INVARIANT: a compact token whose HMAC was computed under a
    different secret is rejected by ``decode_compact_token`` (returns
    None) and the caller falls into the flat-token branch — which
    rejects it (token != api_token) → 401.
    """
    person = uuid4()
    forged = encode_compact_token(
        secret="wrong-secret",
        person_id=person,
        tenant_slug=TENANT_A_SLUG,
    )
    assert decode_compact_token(forged, secret=API_TOKEN) is None

    ctx = _bearer_ctx(forged)
    with pytest.raises(PermissionError):
        resolve_caller(ctx, api_token=API_TOKEN, fallback_company_id=None)


def test_expired_compact_token_rejected() -> None:
    """INVARIANT: an expired compact token is rejected; the caller cannot
    use a long-since-revoked token to read either tenant.
    """
    person = uuid4()
    issued = datetime.now(tz=UTC) - timedelta(hours=2)
    expired = encode_compact_token(
        secret=API_TOKEN,
        person_id=person,
        tenant_slug=TENANT_A_SLUG,
        expires_in_seconds=60,
        issued_at=issued,
    )
    assert decode_compact_token(expired, secret=API_TOKEN) is None
    ctx = _bearer_ctx(expired)
    with pytest.raises(PermissionError):
        resolve_caller(ctx, api_token=API_TOKEN, fallback_company_id=None)


# ---------------------------------------------------------------------------
# Rate-limit isolation: per-(caller, tenant) buckets do not bleed.
# ---------------------------------------------------------------------------


async def _seed_mcp_call(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    caller_person_id: UUID,
    outcome: str = "ok",
) -> None:
    """Append one ``emit_mcp_call_received`` execute row counted by the
    rate limiter."""
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "mcp_call_received",
            "ref_id": str(uuid4()),
            "reason": "seed mcp call",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_mcp_call_received",
            "args": {
                "mcp_call_id": str(uuid4()),
                "caller_person_id": str(caller_person_id),
                "tool_name": "query_kpis",
                "args_hash": "deadbeef",
                "outcome": outcome,
                "latency_ms": 5,
            },
            "result_ref": str(uuid4()),
        },
        verify_fn=lambda _ep: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep"},
    )


async def test_rate_limit_buckets_do_not_bleed_across_tenants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: tenant A's rate-limit budget is independent of tenant
    B's. Saturating tenant A's budget does NOT block tenant B requests
    by the same Person.
    """
    monkeypatch.setenv("WORMBASE_MCP_RATE_LIMIT_PER_MIN", "5")
    ledger = InMemoryLedger()
    person = uuid4()
    cid_a = _company_id(TENANT_A_SLUG)
    cid_b = _company_id(TENANT_B_SLUG)

    # Saturate tenant A.
    for _ in range(5):
        await _seed_mcp_call(ledger, cid_a, caller_person_id=person)

    # Tenant A is now over the limit.
    with pytest.raises(RateLimitExceeded):
        await check_rate_limit(
            ledger, company_id=cid_a, caller_person_id=person,
        )

    # Tenant B for the same Person must NOT be at the limit.
    count_b = await check_rate_limit(
        ledger, company_id=cid_b, caller_person_id=person,
    )
    assert count_b == 0, (
        f"tenant_b's bucket polluted by tenant_a's saturation (count={count_b})"
    )


async def test_rate_limit_buckets_do_not_bleed_across_callers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: caller A's burn does NOT consume caller B's budget
    even within the same tenant — corollary of the (caller, tenant) pair
    being the bucket key.
    """
    monkeypatch.setenv("WORMBASE_MCP_RATE_LIMIT_PER_MIN", "3")
    ledger = InMemoryLedger()
    cid_a = _company_id(TENANT_A_SLUG)
    person_alice = uuid4()
    person_bob = uuid4()

    for _ in range(3):
        await _seed_mcp_call(ledger, cid_a, caller_person_id=person_alice)

    with pytest.raises(RateLimitExceeded):
        await check_rate_limit(
            ledger, company_id=cid_a, caller_person_id=person_alice,
        )

    # Bob hasn't sent anything — his bucket is empty.
    count = await check_rate_limit(
        ledger, company_id=cid_a, caller_person_id=person_bob,
    )
    assert count == 0


async def test_rate_limit_window_excludes_old_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: the per-minute rate-limit window MUST be rolling — old
    entries fall out as time advances. Tested by passing a synthetic
    "now" two minutes after the seeded entries.
    """
    monkeypatch.setenv("WORMBASE_MCP_RATE_LIMIT_PER_MIN", "3")
    ledger = InMemoryLedger()
    cid = _company_id(TENANT_A_SLUG)
    person = uuid4()
    for _ in range(5):
        await _seed_mcp_call(ledger, cid, caller_person_id=person)

    future = datetime.now(tz=UTC) + timedelta(minutes=2)
    count = await check_rate_limit(
        ledger, company_id=cid, caller_person_id=person, now=future,
    )
    assert count == 0


# ---------------------------------------------------------------------------
# Negative: cross-tenant token use returns 401/403 (or routes to a ghost).
# ---------------------------------------------------------------------------


def test_token_with_no_person_claim_resolves_to_header_tenant_only() -> None:
    """INVARIANT: a flat (legacy) token uses the ``X-Tenant-Slug`` header
    for tenant resolution. Switching the header switches the company_id
    — this is intentional for legacy admin tooling, but means the flat
    token is NOT a SaaS production credential.

    The spec test is: switching the header DOES change company_id when
    the bearer is the flat secret. (Negative case: customer-grade
    Person-tokens above.)
    """
    ctx_a = _bearer_ctx(API_TOKEN, tenant_header=TENANT_A_SLUG)
    pid_a, cid_a, slug_a = resolve_caller(
        ctx_a, api_token=API_TOKEN, fallback_company_id=None,
    )
    assert pid_a is None
    assert cid_a == _company_id(TENANT_A_SLUG)
    assert slug_a == TENANT_A_SLUG

    ctx_b = _bearer_ctx(API_TOKEN, tenant_header=TENANT_B_SLUG)
    pid_b, cid_b, slug_b = resolve_caller(
        ctx_b, api_token=API_TOKEN, fallback_company_id=None,
    )
    assert pid_b is None
    assert cid_b == _company_id(TENANT_B_SLUG)
    # The two flat-token resolutions are distinct company_ids.
    assert cid_a != cid_b
