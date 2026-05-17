"""Source-building primitive: canonical 4-stage lifecycle on the ledger.

Every source flow (drop_and_profile, credential_offered_in_dm,
mentioned_in_conversation, dashboard_form, kpi_gap_triggered) goes through
this builder. The 4-stage sequence (proposed → confirmed → connected →
profiled) maps to the 4 dedicated ledger entries already defined in
wormbase_ledger.entries:

    source_proposed   — caller proposes a URI + type + provenance
    source_confirmed  — a human (or the system, for trusted flows)
                        confirms the proposal
    source_connected  — connector returns a connection handle
                        (optionally carrying a ``credential_ref``
                        that the :class:`CredentialBroker` can later
                        resolve to opaque-secret payload material;
                        required at sampling time for stripe /
                        salesforce / hubspot / gsheets kinds)
    source_profiled   — profiler returns row/column counts + schema hash

Every entry shares a stable ``correlation_id`` (carried via the propose
``ref_id`` field, mirrored in the execute payload) and a ``provenance``
block (added_by, added_via_flow, added_in_response_to, added_at).

The builder also writes a ``source_aborted`` entry when a downstream stage
fails — encoded as a memory_written entry with tag 'source_aborted' so we
don't need a new ledger entry kind for the abort path.
"""

from __future__ import annotations

import contextlib
import inspect
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("wormbase_core.source_builder")

from wormbase_catalog_mirror import wire_catalog_for_source
from wormbase_core.types import CorrelationId
from wormbase_lake_maintainer.registry import (
    SourceRegistry,
    wire_maintenance_for_source,
)
from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ledger.entries import (
    AddedViaFlow,
    Classification,
    SourceConfirmedPayload,
    SourceConnectedPayload,
    SourceProfiledPayload,
    SourceProposedPayload,
)


SourceKind = Literal["file", "database", "blob", "rest_api"]


class SourceBuilderStateError(Exception):
    """Raised when stages are called out of order."""


class SourceProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposed_uri: str
    proposed_type: SourceKind
    proposed_domain: str
    proposed_classification: Classification
    proposed_owner_person_id: UUID | None = None
    added_by_person_id: UUID | None = None
    added_via_flow: AddedViaFlow
    added_in_response_to: str | None = None
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    company_id: UUID

    def with_correlation_id(self, cid: str) -> SourceProposal:
        return self.model_copy(update={"correlation_id": cid})


class _ClockProto(Protocol):
    def now(self) -> datetime: ...


class _DefaultClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class SourceBuilder:
    """Writes the 4-stage canonical sequence and enforces stage ordering."""

    def __init__(
        self,
        ledger: Ledger | InMemoryLedger,
        clock: _ClockProto | None = None,
        *,
        source_registry: SourceRegistry | None = None,
        reactivity_registry: Any | None = None,
    ) -> None:
        self._ledger = ledger
        self._clock = clock or _DefaultClock()
        # Tracks per-correlation_id state in-process (across abnormal exits
        # the ledger itself is the source of truth — see _stage_for).
        self._state: dict[str, str] = {}
        # Carry the original SourceProposal across stages.
        self._proposals: dict[str, SourceProposal] = {}
        # Lake-maintenance wiring (Block G3). Default ``None`` keeps
        # backward compat for callers not yet updated; ``on_source_connected``
        # becomes a no-op when either registry is absent.
        self._source_registry = source_registry
        self._reactivity_registry = reactivity_registry

    async def on_source_connected(self, source: Any) -> list[Any]:
        """Lifecycle hook called after a Source completes the connect flow.

        Wires per-source Reactivities into the W5a registry so the existing
        ReactivityRunner picks them up on its next pass:

        * **lake-maintainer** — always fires when both registries are
          available; registers the four maintenance Reactivities
          (drift / classification / staleness / lineage) for ALL source
          families.
        * **catalog-mirror** — additionally fires when
          ``source.source_mode == "upstream_mirror"`` (i.e. the source
          is catalog-mirrored from an external authoritative source
          like dbt / Snowflake). Registers the two catalog-mirror
          Reactivities (initial import + drift detection).
          ``wormbase_owned`` sources (the default) fall through to
          lake-maintainer only.

        Returns the combined list of registered Reactivities. The list
        is empty when the builder was constructed without registries.
        """
        if self._source_registry is None or self._reactivity_registry is None:
            return []
        registered: list[Any] = []
        registered.extend(
            await wire_maintenance_for_source(
                source=source,
                source_registry=self._source_registry,
                reactivity_registry=self._reactivity_registry,
            )
        )
        # Per-source catalog-mirror dispatch (Wave 3 Task 7, 2026-05-11).
        # ``source_mode == "upstream_mirror"`` Sources (dbt / Snowflake /
        # etc.) get the two catalog-mirror Reactivities in addition to
        # lake-maintainer's four. ``wormbase_owned`` is the default and
        # passes through unchanged. Replaces the Wave 1 cleanup 1a
        # ``catalog_source is not None`` heuristic with the explicit
        # field — see ``MaintainableSource.source_mode`` Protocol.
        if getattr(source, "source_mode", "wormbase_owned") == "upstream_mirror":
            registered.extend(
                await wire_catalog_for_source(
                    source=source,
                    ledger=self._ledger,
                    reactivity_registry=self._reactivity_registry,
                )
            )
        return registered

    # ------------------------------------------------------------------
    # Stage transitions
    # ------------------------------------------------------------------

    async def propose(self, proposal: SourceProposal) -> CorrelationId:
        cid = proposal.correlation_id
        if cid in self._state:
            # Idempotent: same correlation_id is a no-op.
            return CorrelationId(cid)
        source_id = uuid4()
        payload = SourceProposedPayload(
            source_id=source_id,
            source_kind=proposal.proposed_type,
            uri=proposal.proposed_uri,
            added_via_flow=proposal.added_via_flow,
            suggested_domain=proposal.proposed_domain,
            suggested_classification=proposal.proposed_classification,
        )
        await self._ledger.write(
            company_id=proposal.company_id,
            propose={
                "target_kind": "source_proposed",
                "ref_id": cid,
                "reason": f"propose source via {proposal.added_via_flow}",
                "proposed_by": "worm_core",
            },
            execute_fn=lambda: {
                "tool": "emit_source_proposed",
                "args": {
                    **payload.model_dump(mode="json"),
                    # Carry the correlation id + provenance in args so the
                    # projector can reconstruct the lifecycle.
                    "correlation_id": cid,
                    "added_by_person": str(proposal.added_by_person_id)
                        if proposal.added_by_person_id else None,
                    "added_in_response_to": proposal.added_in_response_to,
                    "added_at": self._clock.now().isoformat(),
                },
                "result_ref": cid,
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "proposal_valid", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "source proposal recorded",
            },
            timestamp=self._clock.now(),
            quadrant="active_deterministic",
        )
        self._state[cid] = "proposed"
        # Stash a stand-alone source_id mapping for later stages.
        self._proposals[cid] = proposal.model_copy(
            update={"correlation_id": cid}
        )
        # Store the source_id as part of the in-memory mapping.
        self._source_ids[cid] = source_id  # type: ignore[attr-defined]
        return CorrelationId(cid)

    @property
    def _source_ids(self) -> dict[str, UUID]:
        return self.__dict__.setdefault("_source_ids_dict", {})

    # ------------------------------------------------------------------
    # Public read-only accessors (E4 cleanup pass)
    # ------------------------------------------------------------------
    #
    # The CLI inspector and the source-building flows previously reached
    # into ``_proposals`` / ``_source_ids`` directly via ``# noqa: SLF001``.
    # These public methods make the intent explicit and let downstream
    # callers stop suppressing the SLF001 lint rule.

    def get_proposal(self, correlation_id: str) -> SourceProposal | None:
        """Return the SourceProposal for ``correlation_id``, or None if unseen.

        Read-only view over the per-correlation-id proposal map written
        in :meth:`propose`. Callers must NOT mutate the returned object;
        use the lifecycle methods (``confirm``, ``connect``, ``profile``)
        to advance state.
        """
        return self._proposals.get(correlation_id)

    def get_source_id(self, correlation_id: str) -> UUID | None:
        """Return the source UUID for ``correlation_id``, or None if unseen."""
        return self._source_ids.get(correlation_id)

    def has_correlation(self, correlation_id: str) -> bool:
        """Whether the builder has seen ``correlation_id`` (any stage)."""
        return correlation_id in self._state

    def current_stage(self, correlation_id: str, default: str = "unknown") -> str:
        """Return the current lifecycle stage for ``correlation_id``.

        Stages are: proposed | confirmed | connected | profiled | aborted.
        Returns ``default`` if the builder has not seen the correlation_id.
        """
        return self._state.get(correlation_id, default)

    @property
    def ledger(self) -> Ledger | InMemoryLedger:
        """Read-only view of the underlying Ledger.

        Used by helpers that need to query / write ledger entries
        downstream of a source-building flow (e.g. linking a
        credential-DM to a proactive offer). Callers must NOT swap
        the ledger out — that's a constructor responsibility.
        """
        return self._ledger

    async def confirm(
        self,
        correlation_id: str,
        confirmed_by_person_id: UUID,
        domain_id: UUID,
        classification: Classification = "internal",
    ) -> None:
        self._assert_stage(correlation_id, "proposed")
        prop = self._proposals[correlation_id]
        payload = SourceConfirmedPayload(
            source_id=self._source_ids[correlation_id],
            confirmed_by_person=confirmed_by_person_id,
            domain_id=domain_id,
            classification=classification,
        )
        await self._ledger.write(
            company_id=prop.company_id,
            propose={
                "target_kind": "source_confirmed",
                "ref_id": correlation_id,
                "reason": "confirm proposal",
                "proposed_by": "worm_core",
            },
            execute_fn=lambda: {
                "tool": "emit_source_confirmed",
                "args": {
                    **payload.model_dump(mode="json"),
                    "correlation_id": correlation_id,
                },
                "result_ref": correlation_id,
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "confirm_valid", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "source confirmed",
            },
            timestamp=self._clock.now(),
            quadrant="active_deterministic",
        )
        self._state[correlation_id] = "confirmed"

    async def connect(
        self,
        correlation_id: str,
        connection_ref: str,
        *,
        credential_ref: str | None = None,
    ) -> None:
        """Advance the source to ``connected``.

        ``credential_ref`` (additive 2026-06-10, default ``None``): an
        opaque, non-secret identifier that the
        :class:`wormbase_agent_gateway.credential_broker.CredentialBroker`
        understands as the ``install_id`` slot under which the opaque
        secret material lives. Required at sampling-time for opaque-
        secret connector kinds (stripe / salesforce / hubspot /
        gsheets); ignored for URI-shaped kinds (csv_local / postgres /
        snowflake / bigquery / s3_csv / http_csv) which reconstruct
        from ``proposed_uri`` alone.

        When ``credential_ref`` is None and the proposal's
        ``proposed_type`` looks opaque-secret-shaped, the builder logs
        a warning and proceeds — the entry is still written but
        sampler-side handle reconstruction will return None (honest-
        empty fallback). This matches the broker's read-only operator-
        provisioned posture: secrets live in the broker out-of-band; the
        operator pastes the ref into the dashboard form (or supplies it
        programmatically). No silent failures: the warning fires so the
        gap is auditable.

        Default ``None`` preserves byte-identical behavior for non-
        opaque connector kinds and for callers that haven't been
        updated to thread credential_ref yet.
        """
        self._assert_stage(correlation_id, "confirmed")
        prop = self._proposals[correlation_id]

        # Soft-validate against the opaque-secret assembler registry. A
        # missing credential_ref for an opaque-secret kind is a future
        # honest-empty at sampling time; surface it loudly here so the
        # operator can fix the wiring before the sampler runs.
        if credential_ref is None:
            _maybe_warn_missing_credential_ref(
                connection_ref=connection_ref,
                correlation_id=correlation_id,
                proposed_uri=prop.proposed_uri,
            )

        payload = SourceConnectedPayload(
            source_id=self._source_ids[correlation_id],
            connection_ref=connection_ref,
            connected_at=self._clock.now(),
            credential_ref=credential_ref,
        )
        await self._ledger.write(
            company_id=prop.company_id,
            propose={
                "target_kind": "source_connected",
                "ref_id": correlation_id,
                "reason": "connector ack",
                "proposed_by": "worm_core",
            },
            execute_fn=lambda: {
                "tool": "emit_source_connected",
                "args": {
                    **payload.model_dump(mode="json"),
                    "correlation_id": correlation_id,
                },
                "result_ref": correlation_id,
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "connection_ok", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "source connected",
            },
            timestamp=self._clock.now(),
            quadrant="active_deterministic",
        )
        self._state[correlation_id] = "connected"

    async def profile(
        self,
        correlation_id: str,
        *,
        row_count: int,
        column_count: int,
        schema_hash: str,
        profile_ref: str,
    ) -> None:
        self._assert_stage(correlation_id, "connected")
        prop = self._proposals[correlation_id]
        payload = SourceProfiledPayload(
            source_id=self._source_ids[correlation_id],
            row_count=row_count,
            column_count=column_count,
            schema_hash=schema_hash,
            profile_ref=profile_ref,
        )
        await self._ledger.write(
            company_id=prop.company_id,
            propose={
                "target_kind": "source_profiled",
                "ref_id": correlation_id,
                "reason": "profile complete",
                "proposed_by": "worm_core",
            },
            execute_fn=lambda: {
                "tool": "emit_source_profiled",
                "args": {
                    **payload.model_dump(mode="json"),
                    "correlation_id": correlation_id,
                },
                "result_ref": correlation_id,
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "profile_valid", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "source profiled",
            },
            timestamp=self._clock.now(),
            quadrant="active_deterministic",
        )
        self._state[correlation_id] = "profiled"

    async def abort(
        self,
        correlation_id: str,
        reason: str,
        stage_reached: str,
    ) -> None:
        prop = self._proposals.get(correlation_id)
        if prop is None:
            return
        await self._ledger.write(
            company_id=prop.company_id,
            propose={
                "target_kind": "memory_written",
                "ref_id": correlation_id,
                "reason": "source aborted",
                "proposed_by": "worm_core",
            },
            execute_fn=lambda: {
                "tool": "emit_memory_written",
                "args": {
                    "memory_id": str(uuid4()),
                    "content": f"source_aborted:{reason}",
                    "tags": [
                        "source_aborted",
                        f"correlation_id:{correlation_id}",
                        f"stage:{stage_reached}",
                    ],
                },
                "result_ref": correlation_id,
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "abort_logged", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "abort recorded",
            },
            timestamp=self._clock.now(),
            quadrant="active_deterministic",
        )
        self._state[correlation_id] = f"aborted_at_{stage_reached}"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _assert_stage(self, correlation_id: str, required: str) -> None:
        cur = self._state.get(correlation_id)
        if cur != required:
            raise SourceBuilderStateError(
                f"correlation {correlation_id}: expected stage "
                f"{required!r}, got {cur!r}"
            )


# ---------------------------------------------------------------------------
# Opaque-secret detection — for credential_ref warning at connect()
# ---------------------------------------------------------------------------
#
# Local mirror of ``source_handle_provider.OPAQUE_AUTH_HANDLE_ASSEMBLERS``
# keyed by the URI scheme prefix the source_proposed flow uses. We avoid
# importing source_handle_provider here to keep the builder module slim
# and free of optional-dep coupling. Drift-pinned by
# ``test_credential_ref_threading.py::test_opaque_kinds_match_provider``.

_OPAQUE_URI_SCHEMES: frozenset[str] = frozenset({
    "stripe", "salesforce", "hubspot", "gsheets",
})


def _looks_opaque_secret(proposed_uri: str) -> bool:
    """Best-effort: does this proposed_uri reference an opaque-secret kind?

    Used purely to decide whether a missing ``credential_ref`` deserves
    a warning at connect()-time. Never raises; defaults to False on any
    parse failure (URI-shaped kinds default to silently accepting None).
    """
    if not proposed_uri:
        return False
    try:
        scheme = proposed_uri.split(":", 1)[0].lower()
    except (AttributeError, IndexError):
        return False
    return scheme in _OPAQUE_URI_SCHEMES


def _maybe_warn_missing_credential_ref(
    *,
    connection_ref: str,
    correlation_id: str,
    proposed_uri: str,
) -> None:
    """Log a warning when an opaque-secret kind is connected without a ref.

    The entry is still written — sampler-side resolution returns None
    (honest-empty), which preserves the Sampler activation default-OFF
    posture and the broker's read-only operator-provisioned model. The
    warning makes the gap auditable so an operator can paste the ref
    via the dashboard CredentialRefInput and re-emit on the next pass.
    """
    if not _looks_opaque_secret(proposed_uri):
        return
    logger.warning(
        "source_connected for opaque-secret URI %s (correlation_id=%s) "
        "has no credential_ref; sampler-side handle resolution will "
        "return None (honest-empty fallback). Operator action: provision "
        "the secret in the configured CredentialBroker and supply the "
        "ref via the dashboard CredentialRefInput or the connect() "
        "credential_ref kwarg. connection_ref=%s",
        proposed_uri, correlation_id, connection_ref,
    )


# ---------------------------------------------------------------------------
# Full-sequence helper with rollback
# ---------------------------------------------------------------------------


async def build_full_sequence(
    builder: SourceBuilder,
    proposal: SourceProposal,
    *,
    confirmer_id: UUID,
    domain_id: UUID,
    classification: Classification,
    connection_fn: Callable[[], Awaitable[str] | str],
    profile_fn: Callable[[], Awaitable[dict[str, Any]] | dict[str, Any]],
    credential_ref: str | None = None,
) -> CorrelationId:
    """Run propose → confirm → connect → profile, aborting on failure.

    ``credential_ref`` (additive 2026-06-10, default ``None``): forwarded
    to :meth:`SourceBuilder.connect` so opaque-secret flows can populate
    the ledger entry that :class:`LedgerSourceHandleProvider` later
    resolves via the broker. URI-shaped kinds ignore the field;
    callers that don't pass it preserve byte-identical behavior.
    """
    cid = await builder.propose(proposal)
    try:
        await builder.confirm(cid, confirmer_id, domain_id, classification)
        # connect
        conn_res = connection_fn()
        if inspect.isawaitable(conn_res):
            conn_res = await conn_res
        await builder.connect(cid, str(conn_res), credential_ref=credential_ref)
        # profile
        prof_res = profile_fn()
        if inspect.isawaitable(prof_res):
            prof_res = await prof_res
        if not isinstance(prof_res, dict):
            raise TypeError("profile_fn must return a dict")
        await builder.profile(
            cid,
            row_count=int(prof_res.get("row_count", 0)),
            column_count=int(prof_res.get("column_count", 0)),
            schema_hash=str(prof_res.get("schema_hash", "")),
            profile_ref=str(prof_res.get("profile_ref", "")),
        )
        return cid
    except Exception as exc:  # noqa: BLE001 — rollback on any failure
        last_stage = builder.current_stage(str(cid))
        with contextlib.suppress(Exception):
            await builder.abort(str(cid), reason=str(exc), stage_reached=last_stage)
        raise


__all__ = [
    "SourceBuilder",
    "SourceBuilderStateError",
    "SourceKind",
    "SourceProposal",
    "build_full_sequence",
]
