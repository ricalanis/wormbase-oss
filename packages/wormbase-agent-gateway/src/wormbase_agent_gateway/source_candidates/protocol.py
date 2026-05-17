"""L1 source-candidate triage — Protocol + dataclasses + 3 lightweight Reader Protocols.

Surfaces:

  * :class:`ProposedSourceCandidate` — strategy output dataclass; folds
    1:1 onto a ``source_candidate_proposed`` ledger entry.
  * :class:`SourceCandidateStrategy` — the runtime
    :class:`typing.Protocol` every strategy + the composite implements.
    Optional-Effect Injection compatible (the composite accepts ``None``
    for any strategy slot).
  * :class:`ConnectedSourceReader` + :class:`ConnectedSourceRecord` —
    lightweight Protocol over the **first-class platform projection**
    ``projection_sources``. Used by
    :class:`.strategies.ComplementaritySourceStrategy` for portfolio-gap
    heuristics.
  * :class:`KpiNodeReader` + :class:`KpiNodeRecord` — lightweight
    Protocol over the first-class projection ``projection_kpi_nodes``.
    Used by :class:`.strategies.KpiGapAcquisitionStrategy`.
  * :class:`SilverConversationReader` +
    :class:`SilverConversationRecord` — lightweight Protocol over the
    silver conversations projection (concretely
    ``projection_conversations`` — see §"Verified projection name"
    below). Used by
    :class:`.strategies.ChannelMentionAcquisitionStrategy` for
    regex-based source-mention scanning.
  * :func:`make_candidate_id` — re-exported from :mod:`wormbase_ledger`
    so callers and tests see a single deterministic-hash entry point.

Structurally mirrors :mod:`wormbase_agent_gateway.entity_stitch.protocol`
(L8), :mod:`wormbase_agent_gateway.column_classification.protocol` (L6),
:mod:`wormbase_agent_gateway.semantic_type.protocol` (L5), and the L3 /
L4 / L7 protocol modules.

Doctrine: Optional-Effect Injection case 15 — **fourth lake-side axis
built on top of** :class:`wormbase_agent_gateway.lake_loop.LakeLoopComposite`
**from day one** (after L5 case 12, L6 case 13, L8 case 14). Continues
the zero-friction streak — the composite is ~12-14 LOC of factory code
instead of ~250 LOC of a duplicated composite class.

**NOT a cross-axis chain** (per spec §4.6). The L4→L3, L6→L5, L8→L5
chains read **peer lake-axis projections**. L1's three Reader Protocols
read **first-class platform projections** (sources, KPI tree, silver
conversations) that predate the lake-side axes entirely; the producers
are substrate, not Compounding loops. Cross-axis chain count stays at
3. The runbook documents the distinction so future axes don't inflate
the chain count by reading e.g. ``projection_persons``.

If/when L2 reads L1's ``projection_source_candidates`` directly, that
**would** be a true cross-axis chain (4th) — deferred until L2 design.

Verified projection name (Sub-wave A handoff concern #2): the canonical
silver-conversations table in the WormBase ledger schema is
``projection_conversations`` (one row per (company_id, channel_id,
message_id) carrying ``text`` + ``classification`` + ``domain_id``
columns; folded from ``chat_received`` PEVR cycles). The spec's
``projection_silver_conversations`` is a forward-looking name in case
the silver layer is ever split into its own table. The
:class:`SilverConversationReader` Protocol is named for the role
("silver conversation" = the silver-layer projection of conversation
ingest); the concrete adapter in Sub-wave C will read
``projection_conversations``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from wormbase_ledger import make_candidate_id

__all__ = [
    "ConnectedSourceReader",
    "ConnectedSourceRecord",
    "KpiNodeReader",
    "KpiNodeRecord",
    "ProposedSourceCandidate",
    "SilverConversationReader",
    "SilverConversationRecord",
    "SourceCandidateStrategy",
    "make_candidate_id",
]


# ---------------------------------------------------------------------------
# Proposal dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProposedSourceCandidate:
    """A candidate data-source proposal from an L1 acquisition strategy.

    Designed to fold one-to-one onto a ``source_candidate_proposed``
    ledger entry: every field has a direct payload counterpart (see
    :class:`wormbase_ledger.entries.SourceCandidateProposedPayload`).

    The composite returns a deduplicated list of these; the Compounding
    factory's promotion_action writes one ledger entry per
    :class:`ProposedSourceCandidate`.

    Fields:

      * ``candidate_id`` — deterministic SHA-256 prefix hash of
        ``(proposed_kind, proposed_identifier, strategy)`` minted via
        :func:`make_candidate_id`. Same strategy proposing the same
        source twice → same hash → folds onto the same projection row
        (natural dedup). Different strategies proposing the same source
        → distinct hashes → distinct rows so each strategy's case to
        the admin surfaces independently (kept-separate-by-strategy
        posture; mirrors L6, diverges from L5/L8 merge-on-pair). Per
        spec §4.7.
      * ``proposed_kind`` — connector-registry kind string (e.g.
        ``"csv_local"``, ``"postgres"``, ``"stripe"``, ``"mcp:notion"``).
        Validated at ledger boundary against
        :func:`wormbase_connectors.registry.default_registry`. NOT a
        Literal — connector registry kinds are configuration, not
        KIND_REGISTRY entries (per spec §4.2 + Addendum 4 §B).
      * ``proposed_identifier`` — free-form identifier carrying enough
        hint for the admin to recognise the source (e.g. database
        name, file path hint, OAuth account hint, vendor URL).
      * ``domain_id_hint`` — inferred WormBase domain when upstream
        signal supports it (KPI-gap strategy threads the gap's owning
        domain; the other strategies typically leave it ``None``).
      * ``confidence`` — strategy-emitted score in [0.0, 1.0]. Validated
        at the ledger boundary. L1 floor is 0.4 (lower than other axes'
        0.6) because candidate-triage is the right place for
        low-confidence noise — per spec §4.8.
      * ``strategy`` — open-enum identifier (``"kpi_gap"`` |
        ``"channel_mention"`` | ``"complementarity"`` | future
        plug-ins).
      * ``reasoning`` — human-readable explanation surfaced on the
        admin ``/lake/source-candidates`` detail panel.
      * ``evidence`` — strategy-specific structured payload preserved
        verbatim through the fold (KPI gap carries
        ``{"kpi_node_id": ...}``; channel-mention carries
        ``{"message_refs": [...], "matched_pattern": "..."}``;
        complementarity carries ``{"portfolio_snapshot": [...]}``).
    """

    candidate_id: str
    proposed_kind: str
    proposed_identifier: str
    domain_id_hint: str | None
    confidence: float
    strategy: str
    reasoning: str
    evidence: dict[str, Any]


# ---------------------------------------------------------------------------
# Strategy Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SourceCandidateStrategy(Protocol):
    """Proposes candidate data sources for admin triage.

    Composable via Optional-Effect Injection (doctrine case 15). Each
    concrete strategy can be independently ``None`` on the composite;
    missing strategies fall back to empty proposal lists and increment
    the composite's no-op telemetry counter.

    All implementations are async + non-mutating; calling
    :meth:`propose` twice on the same inputs returns the same outputs
    modulo set semantics (replay stability).

    Unlike L3 / L4 / L5 / L6 / L7 / L8 strategies which are
    *pair-* / *table-* / *snapshot-scoped*, L1 strategies are
    **company-scoped** — they read the company's connected sources / KPI
    tree / silver-conversation stream and emit zero-or-many
    company-wide source-candidate proposals per fire. The composite
    invokes them once per Compounding cycle, not once per
    cross-source pair.
    """

    name: str  # strategy identifier (``"kpi_gap"`` etc.)

    async def propose(
        self,
        *,
        company_id: UUID,
    ) -> list[ProposedSourceCandidate]:
        """Return the proposed source candidates for ``company_id``.

        Strategies MAY return an empty list (the honest stub posture
        when upstream signal is missing — e.g. KPI gap fires but the
        KPI tree is empty; channel-mention fires but the silver
        conversation projection has no rows). The composite is
        designed for this: a wired strategy returning ``[]`` does NOT
        increment the ``no_op`` counter (that's reserved for the
        all-None Optional-Effect-absent path).
        """
        ...


# ---------------------------------------------------------------------------
# Lightweight Reader Protocol 1 — ConnectedSourceReader
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConnectedSourceRecord:
    """Minimum projection of a row from ``projection_sources`` that L1 needs.

    Fields:

      * ``source_id`` — opaque source identifier (per L3 source
        grammar).
      * ``kind`` — connector kind string (e.g. ``"csv_local"``,
        ``"stripe"``) — matches the ``proposed_kind`` shape on a
        :class:`ProposedSourceCandidate`.
      * ``domain_id`` — owning domain UUID-string when present.
        ``None`` for sources that don't carry a domain assignment.
      * ``classification`` — governance classification string (e.g.
        ``"public"``, ``"internal"``, ``"confidential"``, ``"pii"``,
        ``"regulated"``) — used by ComplementarityStrategy for
        portfolio-balance heuristics without re-reading governance
        projections.

    Lightweight on purpose — :class:`ComplementaritySourceStrategy`
    only needs (kind, domain, classification) to compute portfolio gaps.
    Sub-wave C's :class:`LedgerConnectedSourceReader` projects this
    subset out of the wider ``projection_sources`` row.
    """

    source_id: str
    kind: str
    domain_id: str | None
    classification: str | None


@runtime_checkable
class ConnectedSourceReader(Protocol):
    """Reads existing ``projection_sources`` for portfolio-gap heuristics.

    Consumed by :class:`.strategies.ComplementaritySourceStrategy`.

    **NOT a cross-axis chain** — ``projection_sources`` is a
    first-class platform projection (folded from
    ``source_connected`` PEVR cycles written by the source-builder
    flows), not a peer lake-axis projection. The producer is substrate,
    not a Compounding loop. Per spec §4.6 doctrine clarification.
    """

    async def list_connected_sources(
        self, *, company_id: UUID,
    ) -> list[ConnectedSourceRecord]:
        """Return all connected sources for the company.

        Implementations SHOULD return an empty list when the company
        has no connected sources yet (the honest stub posture). The
        ComplementarityStrategy treats empty → no proposals (zero
        portfolio to balance).
        """
        ...


# ---------------------------------------------------------------------------
# Lightweight Reader Protocol 2 — KpiNodeReader
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KpiNodeRecord:
    """Minimum projection of a row from ``projection_kpi_nodes`` that L1 needs.

    Fields:

      * ``kpi_node_id`` — opaque KPI node identifier (per KPI tree
        grammar).
      * ``name`` — human-readable KPI name (e.g.
        ``"q3_net_revenue"``, ``"daily_active_users"``,
        ``"pipeline_value"``). Used by
        :class:`.strategies.KpiGapAcquisitionStrategy` to pattern-match
        against connector kinds.
      * ``domain_id`` — owning domain UUID-string when present.
        Threaded through to the proposal's ``domain_id_hint`` so the
        admin surface groups candidate sources by their KPI-anchored
        domain.

    Lightweight on purpose — KpiGapStrategy only needs (name, domain)
    for the regex bank + domain threading. Sub-wave C's
    :class:`LedgerKpiNodeReader` filters to nodes WITHOUT a backing
    data source (i.e. no ``source_id`` reference in lineage) before
    returning rows — that's the "unbacked KPI" notion the spec §4.3
    KpiGap strategy targets.
    """

    kpi_node_id: str
    name: str
    domain_id: str | None


@runtime_checkable
class KpiNodeReader(Protocol):
    """Reads KPI nodes without a backing data source for KPI-gap detection.

    Consumed by :class:`.strategies.KpiGapAcquisitionStrategy`.

    **NOT a cross-axis chain** — ``projection_kpi_nodes`` is a
    first-class platform projection (folded from KPI tree PEVR cycles
    written by KPI definition flows), not a peer lake-axis projection.
    The producer is substrate, not a Compounding loop. Per spec §4.6
    doctrine clarification.
    """

    async def list_kpi_nodes_without_source(
        self, *, company_id: UUID,
    ) -> list[KpiNodeRecord]:
        """Return KPI nodes that have no backing data source.

        The Reader's responsibility is the "without source" filter —
        the strategy only sees the gap candidates, not the full KPI
        tree. Implementations SHOULD return an empty list when the KPI
        tree is empty OR when every node is already backed (the honest
        stub posture: KpiGap → no proposals).
        """
        ...


# ---------------------------------------------------------------------------
# Lightweight Reader Protocol 3 — SilverConversationReader
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SilverConversationRecord:
    """Minimum projection of a row from the silver-conversations projection.

    The canonical silver-conversations table in the WormBase ledger
    schema is ``projection_conversations`` — see the module docstring
    "Verified projection name" section for the discrepancy with the
    spec's forward-looking ``projection_silver_conversations`` name.

    Fields:

      * ``message_id`` — opaque platform-side message id; threaded into
        ``evidence.message_refs`` on a proposal so the admin can
        navigate to the originating message.
      * ``channel_id`` — channel identifier the message landed in.
      * ``text`` — message text body (the regex-scan target for
        :class:`.strategies.ChannelMentionAcquisitionStrategy`).
      * ``domain_id`` — owning domain UUID-string when classified.
        Threaded into ``domain_id_hint`` on the proposal when the
        regex match carries domain signal.
      * ``classification`` — governance classification string
        (``"public"`` / ``"internal"`` / ``"confidential"`` / ``"pii"``
        / ``"regulated"``) — strategies SHOULD honour this and skip
        mention-scanning ``pii`` / ``regulated`` rows by default. The
        reader returns the field; the strategy decides the policy.

    Lightweight on purpose — ChannelMentionStrategy only needs (text,
    refs, domain, classification) to do the regex scan and emit
    proposals with proper provenance. Sub-wave C's
    :class:`LedgerSilverConversationReader` projects this subset out of
    the wider ``projection_conversations`` row.
    """

    message_id: str
    channel_id: str
    text: str
    domain_id: str | None
    classification: str | None


@runtime_checkable
class SilverConversationReader(Protocol):
    """Reads recent silver-conversation rows for channel-mention scanning.

    Consumed by :class:`.strategies.ChannelMentionAcquisitionStrategy`.

    **NOT a cross-axis chain** — the silver-conversations projection
    is a first-class platform projection (folded from
    ``chat_received`` PEVR cycles written by the channel-adapter), not
    a peer lake-axis projection. The producer is substrate, not a
    Compounding loop. Per spec §4.6 doctrine clarification.

    The reader is responsible for the "recent" window cap (default
    last 1000 rows) — strategies should NOT regex-scan unbounded
    conversation history. Sub-wave A handoff concern #3 reserves the
    env knob ``WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_WINDOW``
    (capped at 1000) for Phase 2.
    """

    async def list_recent_conversations(
        self,
        *,
        company_id: UUID,
        since_seconds: int = 86400,
    ) -> list[SilverConversationRecord]:
        """Return recent silver-conversation rows for the company.

        ``since_seconds`` defaults to 86400 (24 hours). Implementations
        cap the returned row count at 1000 to bound regex-scan cost.
        SHOULD return an empty list when the silver-conversation
        projection has no rows (the honest stub posture: ChannelMention
        → no proposals; per Sub-wave A handoff concern #1).
        """
        ...
