"""credential lifecycle helpers — broker delegation + ledger emission.

Per doctrine Addendum 3: ``credential`` is ONE entry kind with a ``status``
field for active/revoked (not a separate ``credential_revoked`` kind). Two
``credential_kind`` axes — ``data`` and ``model`` — share the same payload
shape; ``target`` is the resource_id for data tokens and the model_kind
string for model tokens.

Emission mechanics: ``Ledger.write`` is the only write surface, and it
always writes a 4-entry PEVR cycle. Credential lifecycle is
observation-only — the broker is the deterministic core that mints/revokes
the token; the ledger entry records the lifecycle event with full
provenance. The PEVR cycle is therefore degenerate (verify always passes,
resolve always keeps) — matching ``lake-maintainer._emit_signal``.

If a future Wave introduces a ``write_simple`` non-PEVR primitive, the
helper can collapse to one-entry semantics without changing the call-site
contract.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from wormbase_inference import AgentID
from wormbase_ledger.entries import CredentialPayload

from ..credential_broker import (
    CredentialBroker,
    DataScope,
    ModelScope,
    ScopedToken,
)


def _emit_credential_pevr(
    *,
    payload: CredentialPayload,
) -> tuple[dict[str, Any], Any, Any, Any]:
    """Build the (propose, execute_fn, verify_fn, resolve_fn) tuple for a
    credential lifecycle event.

    The PEVR cycle is observation-only: verify always passes, resolve
    always keeps. Carries the CredentialPayload-shaped dict at every
    phase so projection-folders see a consistent payload across the
    four envelope entries.
    """
    payload_dict = payload.model_dump()

    def _execute() -> dict[str, Any]:
        return dict(payload_dict)

    def _verify(_exec: dict[str, Any]) -> dict[str, Any]:
        return {
            **payload_dict,
            "checks": [{"name": "credential_lifecycle_recorded", "ok": True}],
            "passed": True,
        }

    def _resolve(_v: dict[str, Any]) -> dict[str, Any]:
        return {
            **payload_dict,
            "outcome": "keep",
            "rationale": f"credential {payload.status}",
        }

    return payload_dict, _execute, _verify, _resolve


async def issue_data_credential(
    *,
    broker: CredentialBroker,
    ledger: Any,
    company_id: UUID,
    agent_id: AgentID,
    scope: DataScope,
    ttl_s: int,
    issued_by: str = "agent-gateway",
) -> ScopedToken:
    """Issue a scoped data token AND emit a ``credential`` ledger entry.

    Two-step transaction:
        1. Broker mints the token (revocable, ttl-bounded).
        2. Ledger records the credential lifecycle event with the
           token's ``expires_at`` populated.
    """
    token = await broker.issue_data_token(
        agent_id=agent_id.value,
        scope=scope,
        ttl_s=ttl_s,
    )
    payload = CredentialPayload(
        agent_id=agent_id.value,
        credential_kind="data",
        target=scope.resource_id,
        status="active",
        ttl_expires_at=datetime.fromtimestamp(token.expires_at, tz=timezone.utc).isoformat(),
        issued_by=issued_by,
    )
    propose, execute_fn, verify_fn, resolve_fn = _emit_credential_pevr(payload=payload)
    await ledger.write(
        company_id=company_id,
        propose=propose,
        execute_fn=execute_fn,
        verify_fn=verify_fn,
        resolve_fn=resolve_fn,
    )
    return token


async def issue_model_credential(
    *,
    broker: CredentialBroker,
    ledger: Any,
    company_id: UUID,
    agent_id: AgentID,
    scope: ModelScope,
    ttl_s: int,
    issued_by: str = "agent-gateway",
) -> ScopedToken:
    """Issue a scoped model token AND emit a ``credential`` ledger entry.

    Analogous to :func:`issue_data_credential` but for ``ModelScope``.
    ``target`` carries the ``model_kind`` string (e.g. ``"kimi"``).
    """
    token = await broker.issue_model_token(
        agent_id=agent_id.value,
        scope=scope,
        ttl_s=ttl_s,
    )
    payload = CredentialPayload(
        agent_id=agent_id.value,
        credential_kind="model",
        target=scope.model_kind,
        status="active",
        ttl_expires_at=datetime.fromtimestamp(token.expires_at, tz=timezone.utc).isoformat(),
        issued_by=issued_by,
    )
    propose, execute_fn, verify_fn, resolve_fn = _emit_credential_pevr(payload=payload)
    await ledger.write(
        company_id=company_id,
        propose=propose,
        execute_fn=execute_fn,
        verify_fn=verify_fn,
        resolve_fn=resolve_fn,
    )
    return token


async def revoke_credential(
    *,
    broker: CredentialBroker,
    ledger: Any,
    company_id: UUID,
    agent_id: AgentID,
    token_id: str,
    credential_kind: Literal["data", "model"],
    target: str,
    ttl_expires_at: str,
    issued_by: str = "agent-gateway",
) -> None:
    """Revoke a broker-issued token AND emit a ``credential`` entry with
    status="revoked".

    The caller passes the original credential's ``credential_kind`` /
    ``target`` / ``ttl_expires_at`` so the revocation entry retains
    full provenance without re-fetching state from the projection. In
    a future Wave the projection-fold can derive these via
    ``token_id`` join; today they are caller-supplied to keep the
    revoke path synchronous-deterministic.
    """
    await broker.revoke(token_id)
    payload = CredentialPayload(
        agent_id=agent_id.value,
        credential_kind=credential_kind,
        target=target,
        status="revoked",
        ttl_expires_at=ttl_expires_at,
        issued_by=issued_by,
    )
    propose, execute_fn, verify_fn, resolve_fn = _emit_credential_pevr(payload=payload)
    await ledger.write(
        company_id=company_id,
        propose=propose,
        execute_fn=execute_fn,
        verify_fn=verify_fn,
        resolve_fn=resolve_fn,
    )


__all__ = ["issue_data_credential", "issue_model_credential", "revoke_credential"]
