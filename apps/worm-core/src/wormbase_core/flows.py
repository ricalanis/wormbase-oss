"""flows.py — partial shim post-Wave-B chat-worm extraction.

Four chat-driven flows + helpers lifted to wormbase_chat_presence.chat_flows:
  - DropAndProfileFlow
  - CredentialInDmFlow + helpers (link_credential_to_proactive_offer,
    credential_in_dm_with_offer_link)
  - MentionedInConversationFlow + helpers (recognized_remote_archetypes,
    propose_remote_archetype, ProactiveMentionResult)
  - KpiGapTriggeredFlow

Two flows STAY in worm-core (per D4 + spike §4.2):
  - DashboardFormFlow         — dashboard write surface (POST handler)
  - LakeDiscoveryFlow         — one-shot CLI install-time helper

Plus a chat-worm-adjacent helper that stays:
  - cascade_after_propose     — used by make_flow_dispatcher_with_cascade

This module re-exports the lifted four for legacy import compatibility.
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

# Re-exports of the lifted four (chat-driven) flows + helpers. Importing
# CredentialLeakError + FileProfile here keeps legacy callers compiling.
from wormbase_chat_presence.chat_flows import (
    CredentialInDmFlow,
    DropAndProfileFlow,
    KpiGap,
    KpiGapTriggeredFlow,
    MentionedInConversationFlow,
    ProactiveMentionResult,
    credential_in_dm_with_offer_link,
    link_credential_to_proactive_offer,
    propose_remote_archetype,
    recognized_remote_archetypes,
)
from wormbase_chat_presence.chat_flows._shared import (
    CredentialLeakError,
    FileProfile,
    _PIIGateProto,
)

from wormbase_core.source_builder import (
    SourceBuilder,
    SourceKind,
    SourceProposal,
    build_full_sequence,
)
from wormbase_core.types import CorrelationId
from wormbase_ledger import InMemoryLedger, Ledger


# Underscore is a word char in Python regex, so "customers_ssn" matches as a
# single word. We use a permissive boundary that breaks on underscore too.
# Used by the in-place lake-discovery classifier; kept local so the shim
# does not depend on a private symbol from chat_flows.drop_and_profile.
_PII_FILENAME_HINTS = re.compile(
    r"(?:^|[^a-z0-9])(ssn|sin|tax_id|customers?|users?|pii|email|phone|dob|"
    r"cardholder|kyc)(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 4) dashboard_form  (NOT lifted — dashboard write surface)
# ---------------------------------------------------------------------------


def _scrub_credential(uri: str) -> str:
    """Strip user:pass before storing the URI.

    Local copy (lifted symbol stays chat-worm-private). Used by
    DashboardFormFlow below; kept module-private to avoid coupling
    dashboard-form to chat_flows internals.
    """
    return re.sub(r"://[^@\s]+@", "://[REDACTED]@", uri)


class DashboardSourceSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    submission_id: str
    uri: str
    type: Literal["file", "database", "blob", "rest_api"]
    domain: str
    classification: Literal["public", "internal", "confidential", "pii", "regulated"]
    owner_person_id: UUID
    submitter_person_id: UUID
    company_id: UUID


class DashboardFormFlow:
    """Power-user submission via the dashboard form (P4 will wire this)."""

    def __init__(
        self,
        builder: SourceBuilder,
        pii_gate: _PIIGateProto,
        connector_register: Callable[[str], Awaitable[str] | str] | None = None,
    ) -> None:
        self._builder = builder
        self._pii_gate = pii_gate
        self._connector_register = connector_register

    async def on_submission(
        self, submission: DashboardSourceSubmission
    ) -> CorrelationId:
        # PII-gate the URI in case of embedded credentials.
        check = await self._pii_gate.check(submission.uri, {"source": "dashboard"})
        scrubbed = (
            check.redacted_text
            if hasattr(check, "redacted_text") and check.changed
            else submission.uri
        )
        proposal = SourceProposal(
            proposed_uri=_scrub_credential(scrubbed),
            proposed_type=submission.type,
            proposed_domain=submission.domain,
            proposed_classification=submission.classification,
            proposed_owner_person_id=submission.owner_person_id,
            added_by_person_id=submission.submitter_person_id,
            added_via_flow="dashboard_form",
            added_in_response_to=f"dashboard_submission:{submission.submission_id}",
            company_id=submission.company_id,
        )

        async def _connect() -> str:
            if self._connector_register is None:
                return f"dashboard-conn-{submission.submission_id}"
            r = self._connector_register(submission.uri)
            if hasattr(r, "__await__"):
                return await r  # type: ignore[no-any-return]
            return str(r)

        return await build_full_sequence(
            self._builder,
            proposal,
            confirmer_id=submission.submitter_person_id,
            domain_id=uuid4(),
            classification=submission.classification,
            connection_fn=_connect,
            profile_fn=lambda: {
                "row_count": 0,
                "column_count": 0,
                "schema_hash": "deferred",
                "profile_ref": submission.submission_id,
            },
        )


# ---------------------------------------------------------------------------
# 6) lake_discovery (NOT lifted — one-shot CLI install-time helper)
#
# Step 2 of the canonical product arc — see
# ``docs/superpowers/specs/2026-04-26-wormbase-product-arc.md``. The worm
# walks an existing data-lake catalog at install time (or admin command)
# and proposes one source per discovered table. For the demo we mock the
# catalog walks so they're deterministic and offline.
# ---------------------------------------------------------------------------


_LakeKind = Literal["snowflake", "postgres", "s3"]


_MOCK_SNOWFLAKE_TABLES: tuple[str, ...] = (
    "subscriptions",
    "invoices",
    "customers",
    "events",
    "monthly_revenue",
    "expansion",
    "churn",
)

_MOCK_POSTGRES_TABLES: tuple[str, ...] = (
    "users",
    "orders",
    "payments",
    "sessions",
)

_MOCK_S3_OBJECTS: tuple[str, ...] = (
    "exports/2026-q3-summary.parquet",
    "exports/feature_store_v2.parquet",
    "logs/access-2026-04.json",
)


def _classify_table_name(name: str) -> tuple[str, "Literal['public', 'internal', 'confidential', 'pii', 'regulated']"]:
    """Return (suggested_domain, suggested_classification) for a table.

    Heuristic: PII filename hints elevate classification; revenue/billing
    table names map to the finance domain.
    """
    domain = "general"
    if any(k in name.lower() for k in ("revenue", "invoice", "payment", "subscription", "billing")):
        domain = "finance"
    elif any(k in name.lower() for k in ("user", "customer", "person")):
        domain = "customer"
    elif any(k in name.lower() for k in ("event", "session", "log")):
        domain = "product"
    classification: Literal[
        "public", "internal", "confidential", "pii", "regulated"
    ] = "internal"
    if _PII_FILENAME_HINTS.search(name):
        classification = "pii"
    return domain, classification


class LakeDiscoveryFlow:
    """Walk an existing lake catalog and emit per-table source proposals.

    The discovery is deterministic — same root URI -> same sources, in the
    same order, for clean replay (Triad C2). For demo purposes the catalog
    is mocked; real snowflake / postgres / s3 walkers can plug into the
    same shape later.
    """

    def __init__(
        self,
        builder: SourceBuilder,
        ledger: Ledger | InMemoryLedger,
    ) -> None:
        self._builder = builder
        self._ledger = ledger

    async def discover(
        self,
        company_id: UUID,
        root_uri: str,
        *,
        added_by_person_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Walk the catalog at root_uri and write proposals + a summary.

        Returns ``{lake_kind, tables_seen, sources_proposed, source_correlation_ids}``.
        """
        kind = _detect_lake_kind(root_uri)
        tables = _mock_catalog(kind, root_uri)
        cids: list[str] = []
        for table in tables:
            uri = _build_table_uri(kind, root_uri, table)
            domain, classification = _classify_table_name(table)
            source_kind: SourceKind = (
                "blob" if kind == "s3" else "database"
            )
            proposal = SourceProposal(
                proposed_uri=uri,
                proposed_type=source_kind,
                proposed_domain=domain,
                proposed_classification=classification,
                proposed_owner_person_id=added_by_person_id,
                added_by_person_id=added_by_person_id,
                added_via_flow="lake_discovery",
                added_in_response_to=f"lake:{root_uri}",
                company_id=company_id,
            )
            cid = await self._builder.propose(proposal)
            cids.append(str(cid))

        # Summary entry. We use memory_written-style PEVR write; the
        # ledger entry kind itself is "execute" with tool=emit_lake_discovered.
        from datetime import UTC as _UTC, datetime as _dt
        now = _dt.now(_UTC)
        await self._ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "lake_discovered",
                "ref_id": str(uuid4()),
                "reason": f"lake_discovery walk of {root_uri}",
                "proposed_by": "lake_discovery_flow",
            },
            execute_fn=lambda: {
                "tool": "emit_lake_discovered",
                "args": {
                    "lake_kind": kind,
                    "root_uri": root_uri,
                    "tables_seen": len(tables),
                    "sources_proposed": len(cids),
                    "classified_at": now.isoformat(),
                },
                "result_ref": root_uri,
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "lake_discovery_valid", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "lake discovery summary recorded",
            },
            timestamp=now,
            quadrant="active_deterministic",
        )
        return {
            "lake_kind": kind,
            "tables_seen": len(tables),
            "sources_proposed": len(cids),
            "source_correlation_ids": cids,
        }


def _detect_lake_kind(root_uri: str) -> _LakeKind:
    if root_uri.startswith("snowflake://"):
        return "snowflake"
    if root_uri.startswith("postgres://") or root_uri.startswith("postgresql://"):
        return "postgres"
    if root_uri.startswith("s3://"):
        return "s3"
    raise ValueError(
        f"unsupported lake URI scheme: {root_uri!r}. Use snowflake://, "
        f"postgres://, or s3://"
    )


def _mock_catalog(kind: _LakeKind, root_uri: str) -> tuple[str, ...]:
    if kind == "snowflake":
        return _MOCK_SNOWFLAKE_TABLES
    if kind == "postgres":
        return _MOCK_POSTGRES_TABLES
    return _MOCK_S3_OBJECTS


def _build_table_uri(kind: _LakeKind, root_uri: str, table: str) -> str:
    sep = "" if root_uri.endswith("/") else "/"
    return f"{root_uri}{sep}{table}"


# ---------------------------------------------------------------------------
# Medallion cascade trigger: bronze/silver/gold after a successful propose.
#
# The cascade is an additive layer over the existing flow methods; callers
# that don't want it ignore this helper. ``DropAndProfileFlow.on_file_drop``
# and ``LakeDiscoveryFlow.discover`` both return the propose's correlation
# id; pass that here together with the source's URI + mime to fire the
# cascade. See ``apps/worm-core/src/wormbase_core/medallion.py``.
# ---------------------------------------------------------------------------


async def cascade_after_propose(
    builder: SourceBuilder,
    cascade: Any,  # MedallionCascade — Any-typed to avoid a circular import
    *,
    correlation_id: str,
    company_id: UUID,
    uri: str,
    mime: str | None = None,
    raw_bytes: bytes | None = None,
) -> dict[str, Any] | None:
    """Run the medallion cascade for an already-proposed source.

    The cascade derives the source_id from the SourceBuilder's in-memory
    map keyed by correlation_id, so callers must invoke this immediately
    after ``builder.propose(...)``. Returns the cascade summary or None if
    the correlation_id is unknown (e.g. the propose was a no-op due to
    idempotency).
    """
    source_id = builder.get_source_id(correlation_id)
    if source_id is None:
        return None
    return await cascade.cascade(
        company_id=company_id,
        source_id=source_id,
        uri=uri,
        mime=mime,
        raw_bytes=raw_bytes,
    )


__all__ = [
    "CredentialInDmFlow",
    "CredentialLeakError",
    "DashboardFormFlow",
    "DashboardSourceSubmission",
    "DropAndProfileFlow",
    "FileProfile",
    "KpiGap",
    "KpiGapTriggeredFlow",
    "LakeDiscoveryFlow",
    "MentionedInConversationFlow",
    "ProactiveMentionResult",
    "cascade_after_propose",
    "credential_in_dm_with_offer_link",
    "link_credential_to_proactive_offer",
    "propose_remote_archetype",
    "recognized_remote_archetypes",
]
