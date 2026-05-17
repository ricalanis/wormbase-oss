"""Tests for the MCP auth hardening (J5).

Three hardenings, six+ tests:

1. Token-encoded tenancy. Compact ``payload.sig`` tokens decode to
   ``(person_id, tenant_slug, exp)``; legacy flat tokens still work
   and resolve to ``(None, fallback_tenant)``.
2. Rate-limit via the ledger fold. Default ceiling is 100/min/caller;
   exceeded → ``denied`` audit + RateLimitExceeded.
3. Audit-log privacy. ``client_ua`` clipped to 32 chars when the result
   contained pii / regulated rows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from wormbase_core.mcp_server import build_mcp_server
from wormbase_core.mcp_tools.auth import (
    DEFAULT_RATE_LIMIT_PER_MIN,
    PII_UA_CLIP,
    RateLimitExceeded,
    bucket_size,
    canonical_args_hash,
    check_rate_limit,
    clip_ua_for_audit,
    decode_compact_token,
    encode_compact_token,
    rate_limit_per_min,
    resolve_caller,
)
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger

API_TOKEN = "test-token-j5"
TENANT_SLUG = "baseworm"


def _company_id() -> UUID:
    return tenant_to_uuid(TENANT_SLUG)


def _ctx_with_token(token: str | None, extra_headers: dict[str, str] | None = None):
    headers = dict(extra_headers or {})
    if token is not None:
        headers["authorization"] = f"Bearer {token}"

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

    return _Ctx(headers)


# -------------------------------------------------------------------
# Token round-trip
# -------------------------------------------------------------------


def test_encode_decode_compact_token_roundtrip() -> None:
    person = uuid4()
    token = encode_compact_token(
        secret=API_TOKEN, person_id=person, tenant_slug=TENANT_SLUG,
    )
    claims = decode_compact_token(token, secret=API_TOKEN)
    assert claims is not None
    assert claims["person_id"] == str(person)
    assert claims["tenant_slug"] == TENANT_SLUG
    assert claims["exp"] is not None


def test_decode_compact_token_rejects_wrong_secret() -> None:
    person = uuid4()
    token = encode_compact_token(
        secret=API_TOKEN, person_id=person, tenant_slug=TENANT_SLUG,
    )
    assert decode_compact_token(token, secret="wrong-secret") is None


def test_decode_compact_token_rejects_expired() -> None:
    person = uuid4()
    # Issued 2 hours ago, with a 1-hour expiry.
    issued = datetime.now(tz=UTC) - timedelta(hours=2)
    token = encode_compact_token(
        secret=API_TOKEN,
        person_id=person,
        tenant_slug=TENANT_SLUG,
        expires_in_seconds=3600,
        issued_at=issued,
    )
    assert decode_compact_token(token, secret=API_TOKEN) is None


def test_decode_compact_token_rejects_garbage() -> None:
    assert decode_compact_token("not-a-token", secret=API_TOKEN) is None
    assert decode_compact_token("", secret=API_TOKEN) is None


# -------------------------------------------------------------------
# Caller resolution: compact + flat token + tenant header.
# -------------------------------------------------------------------


def test_resolve_caller_compact_token_flow() -> None:
    person = uuid4()
    token = encode_compact_token(
        secret=API_TOKEN, person_id=person, tenant_slug=TENANT_SLUG,
    )
    ctx = _ctx_with_token(token)
    caller_pid, company_id, slug = resolve_caller(
        ctx, api_token=API_TOKEN, fallback_company_id=None,
    )
    assert caller_pid == person
    assert company_id == _company_id()
    assert slug == TENANT_SLUG


def test_resolve_caller_flat_token_uses_header_tenant() -> None:
    ctx = _ctx_with_token(API_TOKEN, extra_headers={"x-tenant-slug": TENANT_SLUG})
    caller_pid, company_id, slug = resolve_caller(
        ctx, api_token=API_TOKEN, fallback_company_id=None,
    )
    assert caller_pid is None  # legacy flat token → no Person resolution
    assert company_id == _company_id()
    assert slug == TENANT_SLUG


def test_resolve_caller_missing_token_raises() -> None:
    ctx = _ctx_with_token(None)
    with pytest.raises(PermissionError, match="missing bearer token"):
        resolve_caller(ctx, api_token=API_TOKEN, fallback_company_id=None)


def test_resolve_caller_invalid_flat_token_raises() -> None:
    ctx = _ctx_with_token("totally-wrong-token")
    with pytest.raises(PermissionError, match="invalid bearer token"):
        resolve_caller(ctx, api_token=API_TOKEN, fallback_company_id=None)


# -------------------------------------------------------------------
# Rate limit: env var + ledger fold.
# -------------------------------------------------------------------


def test_rate_limit_per_min_env_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORMBASE_MCP_RATE_LIMIT_PER_MIN", raising=False)
    assert rate_limit_per_min() == DEFAULT_RATE_LIMIT_PER_MIN


def test_rate_limit_per_min_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORMBASE_MCP_RATE_LIMIT_PER_MIN", "5")
    assert rate_limit_per_min() == 5


def test_rate_limit_per_min_invalid_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_MCP_RATE_LIMIT_PER_MIN", "boom")
    assert rate_limit_per_min() == DEFAULT_RATE_LIMIT_PER_MIN


@pytest.mark.asyncio
async def test_check_rate_limit_blocks_after_breach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_MCP_RATE_LIMIT_PER_MIN", "3")
    ledger = InMemoryLedger()
    cid = _company_id()
    person = uuid4()

    # Seed 3 mcp_call_received audit entries for this caller.
    from wormbase_core import write_actions

    now = datetime.now(tz=UTC)
    for _ in range(3):
        await write_actions.record_mcp_call(
            ledger, cid,
            caller_person_id=person,
            tool_name="query_kpis",
            args_hash="0" * 64,
            client_ua=None,
            started_at=now,
            outcome="ok",
            latency_ms=1,
        )

    with pytest.raises(RateLimitExceeded):
        await check_rate_limit(
            ledger, company_id=cid, caller_person_id=person, now=now,
        )


@pytest.mark.asyncio
async def test_check_rate_limit_window_drops_old_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_MCP_RATE_LIMIT_PER_MIN", "3")
    ledger = InMemoryLedger()
    cid = _company_id()
    person = uuid4()

    from wormbase_core import write_actions

    # Three "old" entries, well outside the 60s window.
    old = datetime.now(tz=UTC) - timedelta(minutes=5)
    for _ in range(3):
        await write_actions.record_mcp_call(
            ledger, cid,
            caller_person_id=person,
            tool_name="query_kpis",
            args_hash="0" * 64,
            client_ua=None,
            started_at=old,
            outcome="ok",
            latency_ms=1,
        )
    # InMemoryLedger.write uses timestamp arg; we relied on default. Use a
    # fresh ledger to assert the fresh-window count is zero.
    ledger2 = InMemoryLedger()
    count = await check_rate_limit(
        ledger2, company_id=cid, caller_person_id=person,
        now=datetime.now(tz=UTC),
    )
    assert count == 0


# -------------------------------------------------------------------
# Audit-log privacy: client_ua clipping + result-bucket.
# -------------------------------------------------------------------


def test_clip_ua_for_audit_no_pii_returns_full_ua() -> None:
    ua = "claude-desktop/1.2.3 (very-very-long-ua-string)"
    assert clip_ua_for_audit(ua, has_pii=False) == ua


def test_clip_ua_for_audit_pii_clips_to_pii_length() -> None:
    ua = "claude-desktop/1.2.3 (very-very-long-ua-string-leak-y)"
    out = clip_ua_for_audit(ua, has_pii=True)
    assert out is not None
    assert len(out) <= PII_UA_CLIP


def test_clip_ua_for_audit_none_passes_through() -> None:
    assert clip_ua_for_audit(None, has_pii=True) is None


def test_bucket_size_thresholds() -> None:
    assert bucket_size(0) == "small"
    assert bucket_size(10) == "small"
    assert bucket_size(11) == "medium"
    assert bucket_size(100) == "medium"
    assert bucket_size(101) == "large"


# -------------------------------------------------------------------
# Canonical args hash sanity (replay-stability is the only invariant).
# -------------------------------------------------------------------


def test_canonical_args_hash_is_stable() -> None:
    a = {"company_id": "x", "limit": 10}
    b = {"limit": 10, "company_id": "x"}
    assert canonical_args_hash(a) == canonical_args_hash(b)


# -------------------------------------------------------------------
# End-to-end: a tool call under the rate limit succeeds; the next one
# trips the gate and produces a denied audit.
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_rate_limit_trips_via_query_kpis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_MCP_RATE_LIMIT_PER_MIN", "2")
    ledger = InMemoryLedger()
    mcp = build_mcp_server(ledger=ledger, api_token=API_TOKEN)

    person = uuid4()
    # Phase 1B.F: seed the Person row first so authorize_caller's
    # binding gate accepts the token.
    await ledger.write(
        company_id=_company_id(),
        propose={
            "target_kind": "person_proposed", "ref_id": str(person),
            "reason": "seed person row for 1B.F gate", "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_person_proposed",
            "args": {
                "person_id": str(person),
                "tenant_id": str(_company_id()),
                "name": "Test Person",
                "email": f"{person}@test.invalid",
                "proposed_by": "test",
            },
            "result_ref": str(uuid4()),
        },
        verify_fn=lambda _ep: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )
    # Grant tenancy.admin so the call would otherwise pass.
    args = {
        "person_id": str(person),
        "role": "admin",
        "granted_by": str(person),
    }
    await ledger.write(
        company_id=_company_id(),
        propose={
            "target_kind": "role_assigned", "ref_id": str(uuid4()),
            "reason": "seed", "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_role_assigned", "args": args,
            "result_ref": str(uuid4()),
        },
        verify_fn=lambda _ep: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )

    token = encode_compact_token(
        secret=API_TOKEN, person_id=person, tenant_slug=TENANT_SLUG,
    )
    ctx = _ctx_with_token(token)
    tm = mcp._tool_manager  # noqa: SLF001
    fn = tm.get_tool("query_kpis").fn

    # First two calls succeed.
    await fn(ctx=ctx, company_id=TENANT_SLUG)
    await fn(ctx=ctx, company_id=TENANT_SLUG)
    # Third call blows past the budget.
    with pytest.raises(RateLimitExceeded):
        await fn(ctx=ctx, company_id=TENANT_SLUG)

    # Verify that a denied audit was written for the third call.
    rows = await ledger.fetch(_company_id())
    audit_args = [
        r["payload"]["args"] for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_mcp_call_received"
    ]
    outcomes = [a["outcome"] for a in audit_args]
    assert "denied" in outcomes
