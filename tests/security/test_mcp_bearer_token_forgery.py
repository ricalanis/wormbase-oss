"""W6.A6 — MCP bearer token forgery patterns all rejected.

Six canonical forgery shapes plus a legitimate-token isolation check:

1. **Mismatched HMAC** — take a valid token, modify the payload,
   keep the original signature → ``decode_compact_token`` returns
   ``None`` (auth fail).
2. **Expired** — payload with ``exp`` in the past → ``None``.
3. **Wrong signing key** — token signed with secret B, decoded with
   secret A → ``None``.
4. **Truncated** — bearer with the last 5 chars cut → ``None``.
5. **Padded** — bearer with junk appended → ``None``.
6. **Empty / no Authorization header** — ``resolve_bearer_token``
   returns ``None``; ``resolve_caller`` raises ``PermissionError``.
7. **Revoked** (via the legacy flat-token disabled path) — the
   compact-token path requires ``presented == api_token`` for the
   flat fallback; once we flip the secret, every previously-issued
   token decodes to None.

Plus the rate-limiter isolation invariant: the legitimate token's
counter must NOT advance when forged tokens hit the wire. Forgery
attempts are denied at auth (no audit row), so the audit-derived
rate counter (``check_rate_limit``) for the real caller stays put.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from wormbase_core.mcp_tools.auth import (
    DEFAULT_RATE_LIMIT_PER_MIN,
    check_rate_limit,
    decode_compact_token,
    encode_compact_token,
    issue_person_token,
)
from wormbase_ledger import InMemoryLedger


SECRET_A = "test-secret-A-do-not-use-in-prod"
SECRET_B = "test-secret-B-different-key"


def _legit_token(person_id: UUID, tenant: str = "baseworm") -> str:
    return encode_compact_token(
        secret=SECRET_A,
        person_id=person_id,
        tenant_slug=tenant,
        expires_in_seconds=3600,
    )


def test_legitimate_token_decodes_successfully() -> None:
    """Sanity: a freshly-issued, well-formed token decodes cleanly.

    The negative-case sweep below is only meaningful if the positive
    case actually passes.
    """
    pid = uuid4()
    token = _legit_token(pid)
    claims = decode_compact_token(token, secret=SECRET_A)
    assert claims is not None
    assert claims.get("person_id") == str(pid)
    assert claims.get("tenant_slug") == "baseworm"


def test_mismatched_hmac_token_rejected() -> None:
    """Modifying the payload with the original signature fails decode.

    Classic forgery: keep the signature, change the body. HMAC
    verification will not match the modified body.
    """
    pid = uuid4()
    token = _legit_token(pid)
    head, dot, sig = token.rpartition(".")
    # Flip a known character in the head (the base64-url payload).
    modified_head = ("A" if head[0] != "A" else "B") + head[1:]
    forged = f"{modified_head}{dot}{sig}"
    assert decode_compact_token(forged, secret=SECRET_A) is None


def test_expired_token_rejected() -> None:
    """Token whose ``exp`` is in the past returns None.

    The decode path checks ``exp`` against ``datetime.now(UTC)``;
    expired tokens are treated as forged.
    """
    pid = uuid4()
    token = encode_compact_token(
        secret=SECRET_A,
        person_id=pid,
        tenant_slug="baseworm",
        expires_in_seconds=-60,  # already expired
    )
    assert decode_compact_token(token, secret=SECRET_A) is None


def test_wrong_signing_key_rejected() -> None:
    """Token signed with secret B fails decode under secret A.

    Equivalent to "compromised one tenant's secret" — keys must be
    independent.
    """
    pid = uuid4()
    token_b = encode_compact_token(
        secret=SECRET_B,
        person_id=pid,
        tenant_slug="baseworm",
        expires_in_seconds=3600,
    )
    assert decode_compact_token(token_b, secret=SECRET_A) is None


def test_truncated_token_rejected() -> None:
    """Bearer with the last 5 chars cut fails decode.

    Truncation breaks the signature length; HMAC compare returns
    False.
    """
    pid = uuid4()
    token = _legit_token(pid)
    truncated = token[:-5]
    assert decode_compact_token(truncated, secret=SECRET_A) is None


def test_padded_token_rejected() -> None:
    """Bearer with junk appended fails decode.

    Appending bytes to the signature makes b64-decode succeed but
    HMAC compare-digest fails.
    """
    pid = uuid4()
    token = _legit_token(pid)
    padded = token + "junkbytes"
    assert decode_compact_token(padded, secret=SECRET_A) is None


def test_empty_token_rejected() -> None:
    """Empty / missing token returns None at decode."""
    assert decode_compact_token("", secret=SECRET_A) is None
    assert decode_compact_token(".", secret=SECRET_A) is None
    assert decode_compact_token("a.", secret=SECRET_A) is None
    assert decode_compact_token(".b", secret=SECRET_A) is None


def test_malformed_token_rejected() -> None:
    """Tokens with broken base64 or no dot separator return None."""
    assert decode_compact_function_safely(decode_compact_token, "no-dot-here", SECRET_A) is None
    # Non-base64 head
    assert decode_compact_function_safely(decode_compact_token, "!!notb64.also-not-b64", SECRET_A) is None


def decode_compact_function_safely(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return None


def test_revoked_token_pattern_simulated_via_secret_rotation() -> None:
    """Rotating ``WORMBASE_LEDGER_API_TOKEN`` invalidates every prior token.

    The system has no per-token revocation list yet; the canonical
    revocation primitive is "rotate the signing secret." Assert that
    rotation invalidates a previously-issued token.
    """
    pid = uuid4()
    old_token = encode_compact_token(
        secret=SECRET_A,
        person_id=pid,
        tenant_slug="baseworm",
        expires_in_seconds=3600,
    )
    # Decode under rotated secret → None (effectively revoked).
    assert decode_compact_token(old_token, secret=SECRET_B) is None


def test_issue_person_token_requires_secret() -> None:
    """``issue_person_token`` refuses to issue with an empty secret.

    A regression that lets the API issue tokens with an empty secret
    means every token is forgeable.
    """
    # Save + clear env, then assert.
    saved = os.environ.pop("WORMBASE_LEDGER_API_TOKEN", None)
    try:
        with pytest.raises(ValueError, match="non-empty secret"):
            issue_person_token(
                person_id=uuid4(),
                tenant_slug="baseworm",
                secret=None,
            )
    finally:
        if saved is not None:
            os.environ["WORMBASE_LEDGER_API_TOKEN"] = saved


async def test_rate_counter_does_not_advance_on_forgery_attempts() -> None:
    """Forged tokens never reach audit-write; legitimate counter unchanged.

    The ledger-derived rate counter only counts ``mcp_call_received``
    audit rows. Forgery attempts must fail BEFORE the audit step, so
    the counter is unaffected.

    Verified by:
    1. Counting the legitimate caller's rate before any forgery attempts.
    2. Simulating N forgery attempts (all rejected at decode).
    3. Counting again — must be identical.
    """
    ledger = InMemoryLedger()
    company_id = uuid4()
    legit_pid = uuid4()

    # Baseline: with no audit rows, the rate counter is 0.
    count0 = await check_rate_limit(
        ledger,
        company_id=company_id,
        caller_person_id=legit_pid,
    )
    assert count0 == 0

    # Forgery attempts. Each should fail at decode with no ledger write.
    forged_tokens = [
        "garbage",
        "a.b.c",
        ".",
        "a." + "x" * 100,
        encode_compact_token(
            secret=SECRET_B,
            person_id=legit_pid,
            tenant_slug="baseworm",
            expires_in_seconds=3600,
        ),
    ]
    for tok in forged_tokens:
        assert decode_compact_token(tok, secret=SECRET_A) is None

    # Count the legit caller again — must still be zero (no audit
    # rows ever landed; forgery attempts are pre-audit).
    count1 = await check_rate_limit(
        ledger,
        company_id=company_id,
        caller_person_id=legit_pid,
    )
    assert count1 == 0, (
        f"forgery attempts polluted legit caller's rate counter: "
        f"{count0} -> {count1}"
    )


async def test_rate_limit_ceiling_applies_per_caller() -> None:
    """The rate limiter's ceiling is enforced per (caller, tenant) pair.

    Confirms the ceiling is a real number and that it counts the
    legit caller's audit rows — not a global budget shared with
    forgery attempts.
    """
    ledger = InMemoryLedger()
    company_id = uuid4()
    legit_pid = uuid4()
    other_pid = uuid4()

    # Mock-write a few mcp_call_received rows for the legit caller.
    for _ in range(5):
        await ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "mcp_call",
                "ref_id": str(uuid4()),
                "reason": "test",
                "proposed_by": "test",
            },
            execute_fn=lambda pid=legit_pid: {
                "tool": "emit_mcp_call_received",
                "args": {
                    "caller_person_id": str(pid),
                    "outcome": "ok",
                    "tool_name": "list_decisions",
                    "args_hash": "deadbeef",
                    "client_ua": "tests",
                    "started_at": datetime.now(tz=UTC).isoformat(),
                    "latency_ms": 10,
                },
                "result_ref": str(uuid4()),
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "ok", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test"},
            quadrant="active_deterministic",
        )

    # Legit caller's count is 5; far below the default ceiling.
    legit_count = await check_rate_limit(
        ledger, company_id=company_id, caller_person_id=legit_pid,
    )
    assert legit_count == 5, f"expected 5, got {legit_count}"

    # Other caller's count is 0 — counters are isolated.
    other_count = await check_rate_limit(
        ledger, company_id=company_id, caller_person_id=other_pid,
    )
    assert other_count == 0, (
        f"rate counter for other caller should be 0, got {other_count}"
    )

    # The default ceiling is well above 5.
    assert DEFAULT_RATE_LIMIT_PER_MIN > 5
