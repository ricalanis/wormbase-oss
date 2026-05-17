"""L1 lake-side source-candidate triage subpackage.

Public surface for the L1 Compounding axis (the **7th lake-side
axis**; **4th from-day-one consumer** of :class:`LakeLoopComposite`):

  * :class:`ProposedSourceCandidate` — strategy output dataclass;
    folds 1:1 onto a ``source_candidate_proposed`` ledger entry.
  * :class:`SourceCandidateStrategy` — Protocol every strategy
    implements (runtime_checkable).
  * :func:`make_candidate_id` — deterministic SHA-256-prefix hash
    re-exported from :mod:`wormbase_ledger` (INCLUDES strategy in the
    hash — kept-separate-by-strategy posture; mirrors L6, diverges
    from L5/L8).
  * **3 NEW lightweight Reader Protocols** (NOT cross-axis chains —
    they read first-class platform projections, not peer L-axis
    projections; per spec §4.6):
      * :class:`ConnectedSourceReader` + :class:`ConnectedSourceRecord`
        — reads ``projection_sources``.
      * :class:`KpiNodeReader` + :class:`KpiNodeRecord` — reads
        ``projection_kpi_nodes`` (filtered to unbacked nodes).
      * :class:`SilverConversationReader` +
        :class:`SilverConversationRecord` — reads the silver-layer
        conversation projection (concretely ``projection_conversations``
        — see protocol.py "Verified projection name" note).
  * :class:`KpiGapAcquisitionStrategy` — productive today on unbacked
    KPI nodes; honest stub when KPI tree is empty.
  * :class:`ChannelMentionAcquisitionStrategy` — configured ·
    empty-upstream today (Sub-wave A handoff concern #1); productive
    once silver-conversations have rows.
  * :class:`ComplementaritySourceStrategy` — productive today as soon
    as ≥1 source is connected; static portfolio heuristics.
  * :func:`make_composite_source_candidate_service` — Optional-Effect
    Injection composition over the 3 strategies via
    :class:`LakeLoopComposite` (doctrine case 15 — **fourth from-day-one
    consumer** of the abstraction, after L5 + L6 + L8). ~14 LOC factory
    instead of a ~250 LOC custom composite class.

Sub-wave B (2026-06-08) ships these. Sub-wave C wires concrete
``LedgerConnectedSourceReader`` / ``LedgerKpiNodeReader`` /
``LedgerSilverConversationReader`` impls + the
``make_source_candidate_discovery_reactivity`` factory + 2 admin
endpoints; Sub-wave D ships the admin ``/lake/source-candidates``
dashboard surface.

Cross-axis chain count: stays at **3** (L4→L3, L6→L5, L8→L5). L1's
Reader Protocols are "platform readers" — distinct category per spec
§4.6 doctrine clarification.
"""
from __future__ import annotations

from .composite import make_composite_source_candidate_service
from .protocol import (
    ConnectedSourceReader,
    ConnectedSourceRecord,
    KpiNodeReader,
    KpiNodeRecord,
    ProposedSourceCandidate,
    SilverConversationReader,
    SilverConversationRecord,
    SourceCandidateStrategy,
    make_candidate_id,
)
from .strategies import (
    ChannelMentionAcquisitionStrategy,
    ComplementaritySourceStrategy,
    KpiGapAcquisitionStrategy,
)

__all__ = [
    "ChannelMentionAcquisitionStrategy",
    "ComplementaritySourceStrategy",
    "ConnectedSourceReader",
    "ConnectedSourceRecord",
    "KpiGapAcquisitionStrategy",
    "KpiNodeReader",
    "KpiNodeRecord",
    "ProposedSourceCandidate",
    "SilverConversationReader",
    "SilverConversationRecord",
    "SourceCandidateStrategy",
    "make_candidate_id",
    "make_composite_source_candidate_service",
]
