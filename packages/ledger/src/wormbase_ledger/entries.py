"""Pydantic v2 models for the ledger entry envelope and every payload kind.

Twenty entry kinds in total (per Wave-2 plan + review resolutions):

Canonical (4)
    propose, execute, verify, resolve

Domain-specific (15)
    source_proposed, source_confirmed, source_connected, source_profiled,
    ingest_landed, ingest_profiled,
    memory_written, concept_proposed, concept_confirmed,
    chat_received, chat_sent, gate_fired, kpi_answered,
    heuristic_experiment, policy_applied

Inference (1)
    inference_served (added by 2B review for cache provenance)

Medallion lake (Step 2 of the canonical product arc, see
``docs/superpowers/specs/2026-04-26-wormbase-product-arc.md``):
    source_bronzed, source_silvered, source_golded, kpi_proposed,
    lake_discovered

Each payload subclass auto-registers in `KIND_REGISTRY`. The base
`LedgerEntry` validates kind ∈ registry, quadrant ∈ enum, ts is tz-aware,
and prev_hash/hash are exactly 32 bytes.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Quadrant enum (review resolution: every entry carries a quadrant tag).
# ---------------------------------------------------------------------------
QUADRANT_VALUES: tuple[str, ...] = (
    "passive_deterministic",
    "passive_probabilistic",
    "active_deterministic",
    "active_probabilistic",
)
Quadrant = Literal[
    "passive_deterministic",
    "passive_probabilistic",
    "active_deterministic",
    "active_probabilistic",
]

Classification = Literal["public", "internal", "confidential", "pii", "regulated"]
AddedViaFlow = Literal[
    "drop_and_profile",
    "credential_offered_in_dm",
    "mentioned_in_conversation",
    "dashboard_form",
    "kpi_gap_triggered",
    "lake_discovery",
    "provisioned_at_install",
]
SpeechAct = Literal["introduction", "clarification", "proposal", "answer", "digest"]

KIND_REGISTRY: dict[str, type[EntryPayload]] = {}
ALL_KINDS: set[str] = set()


class EntryPayload(BaseModel):
    """Base for every payload subclass; auto-registers via __init_subclass__."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        k = getattr(cls, "kind", None)
        if k:
            if k in KIND_REGISTRY and KIND_REGISTRY[k] is not cls:
                raise RuntimeError(f"duplicate kind {k}")
            KIND_REGISTRY[k] = cls
            ALL_KINDS.add(k)


class LedgerEntry(BaseModel):
    """The on-the-wire (and on-disk) envelope. Validated against the registry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: UUID
    company_id: UUID
    seq: int = Field(ge=0)
    ts: datetime
    kind: str
    quadrant: Quadrant
    payload: dict[str, Any]
    prev_hash: bytes = Field(min_length=32, max_length=32)
    hash: bytes = Field(min_length=32, max_length=32)

    @field_validator("ts")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("ts must be tz-aware")
        return v

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in ALL_KINDS:
            raise ValueError(f"unknown kind {v}")
        return v


# ---------------------------------------------------------------------------
# Canonical kinds (4)
# ---------------------------------------------------------------------------


class ProposePayload(EntryPayload):
    kind: ClassVar[str] = "propose"
    target_kind: str
    ref_id: UUID
    reason: str
    proposed_by: str


class ExecutePayload(EntryPayload):
    kind: ClassVar[str] = "execute"
    propose_entry_id: UUID
    tool: str
    args: dict[str, Any]
    result_ref: str


class VerifyPayload(EntryPayload):
    kind: ClassVar[str] = "verify"
    execute_entry_id: UUID
    checks: list[dict[str, Any]]
    passed: bool


class ResolvePayload(EntryPayload):
    kind: ClassVar[str] = "resolve"
    verify_entry_id: UUID
    outcome: Literal["keep", "discard"]
    rationale: str


# ---------------------------------------------------------------------------
# v2.B Phase 3 — clock-tick (2026-05-12).
#
# Periodic ledger-resident tick written by ``ClockTickEmitter``. Drives
# time-based Reactivities via the ``Periodic(every_seconds=N)`` predicate.
# Wire-replay determinism: a tick is just another entry in the chain, so
# the gap-escalation cluster decision is reproducible from
# ``(tick_time, ledger_state_at_tick_time)`` alone. Quadrant is
# ``passive_deterministic`` — emitter output is fully a function of
# ``(company_id, tick_interval_s, prior_count)``.
#
# Additive per the schema-evolution doctrine (Rule 2). Net +1 →
# KIND_REGISTRY=100, under the 120 ceiling raised by Wave F Addendum 1.
# ---------------------------------------------------------------------------


class ClockTickPayload(EntryPayload):
    """A periodic clock tick written by ClockTickEmitter.

    Drives time-based Reactivities (``Periodic`` predicate). One
    ``clock_tick`` row per tick interval per company, written by the
    emitter daemon. Wire-replay replays these like any other entry,
    preserving deterministic firing of the gap-escalation axis.

    ``tick_interval_s`` is self-describing: the ``every_seconds`` value
    the emitter was configured with. Multiple emitters with different
    cadences can run in parallel (hourly for gap-escalation, daily for
    digest reactivities) without colliding — the predicate filters on
    matching cadence.

    ``sequence_number`` is 0-indexed monotonic per-tenant per-cadence.
    Resets only on tenant wipe. Recovery is automatic: a restarted
    emitter reads the prior max ``sequence_number`` for its
    ``(company_id, tick_interval_s)`` slot and continues.
    """

    kind: ClassVar[str] = "clock_tick"
    tick_interval_s: int
    sequence_number: int


# ---------------------------------------------------------------------------
# Source-lifecycle kinds (4)
#
# Note: The source's *medium* (file / database / blob) is named `source_kind`
# here to avoid shadowing the envelope-level `kind` (= "source_proposed").
# ---------------------------------------------------------------------------


class SourceProposedPayload(EntryPayload):
    kind: ClassVar[str] = "source_proposed"
    source_id: UUID
    source_kind: str  # "file" | "database" | "blob" | ...
    uri: str
    added_via_flow: AddedViaFlow
    suggested_domain: str
    suggested_classification: Classification


class SourceConfirmedPayload(EntryPayload):
    kind: ClassVar[str] = "source_confirmed"
    source_id: UUID
    confirmed_by_person: UUID
    domain_id: UUID
    classification: Classification


class SourceConnectedPayload(EntryPayload):
    """A connector has been wired with usable credentials for this source.

    ``credential_ref`` (additive 2026-06-10, per Schema-Evolution Doctrine
    Rule 2 — field changes are additive only): an opaque, non-secret
    identifier that the :class:`CredentialBroker` understands as the
    ``install_id`` slot under which the opaque secret material lives.
    For brokers shipped with WormBase (Vault, Env), this is the
    ``install_id`` arg to :meth:`CredentialBroker.hold_data_account` —
    secret payload lives at ``data/<connector_kind>/<credential_ref>``
    in the broker's backing store.

    Defaults to ``None`` for back-compat: pre-2026-06-10 entries on the
    ledger fold byte-identically (the
    :class:`wormbase_core.source_handle_provider.LedgerSourceHandleProvider`
    treats a missing ``credential_ref`` as "no broker resolution path",
    preserving the honest-stub posture for opaque-secret connector
    kinds). Connectors whose authentication is path-shaped or DSN-shaped
    (``csv_local``, ``postgres``, ``snowflake``, ``bigquery``, ``s3_csv``,
    ``http_csv``) reconstruct from ``uri`` and ignore ``credential_ref``.
    """

    kind: ClassVar[str] = "source_connected"
    source_id: UUID
    connection_ref: str
    connected_at: datetime
    credential_ref: str | None = None

    @field_validator("connected_at")
    @classmethod
    def _tz_aware_connected(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("connected_at must be tz-aware")
        return v


class SourceProfiledPayload(EntryPayload):
    kind: ClassVar[str] = "source_profiled"
    source_id: UUID
    row_count: int
    column_count: int
    schema_hash: str
    profile_ref: str


# ---------------------------------------------------------------------------
# Ingest kinds (2)
# ---------------------------------------------------------------------------


class IngestLandedPayload(EntryPayload):
    kind: ClassVar[str] = "ingest_landed"
    source_id: UUID
    object_uri: str
    bytes: int
    row_count: int


class IngestProfiledPayload(EntryPayload):
    """DEPRECATED (per 2026-06-04 doctrine review Addendum 4 §C).

    No producer and no consumer in current code. Superseded by
    `source_profiled` (per the Wave 1 catalog mirror + agentic-source-building
    flow). Class remains registered to honor Rule 1 (kinds-forever); the
    DEPRECATED marker exists for documentation hygiene so future contributors
    don't wire it. Do not emit `ingest_profiled`; emit `source_profiled` instead.
    """

    kind: ClassVar[str] = "ingest_profiled"
    source_id: UUID
    profile_ref: str
    columns: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Memory + concept (3)
# ---------------------------------------------------------------------------


class MemoryWrittenPayload(EntryPayload):
    kind: ClassVar[str] = "memory_written"
    memory_id: UUID
    content: str
    tags: list[str]


class ConceptProposedPayload(EntryPayload):
    kind: ClassVar[str] = "concept_proposed"
    concept_id: UUID
    name: str
    definition: str
    proposed_by: str


class ConceptConfirmedPayload(EntryPayload):
    kind: ClassVar[str] = "concept_confirmed"
    concept_id: UUID
    confirmed_by_person: UUID


# ---------------------------------------------------------------------------
# Chat (2) — chat_sent carries speech_act enum (per 2C review resolution)
# ---------------------------------------------------------------------------


class ChatReceivedPayload(EntryPayload):
    """One inbound channel message captured in the ledger.

    Provenance fields (additive, defaulted for back-compat):

    * ``delivery_mode`` — "push" (live wire event, default) vs
      "history_sync" (replayed during a bulk reconnect / initial-connect /
      channel-join). Speak-path Reactivities (F1/F2/F4) are gated by
      ``LiveOnly``, which reads this field plus ``platform_ts``.
    * ``platform_ts`` — the platform's authoritative wall-clock for the
      message (Slack ``ts``, WhatsApp ``messageTimestamp``). ``None`` when
      the platform doesn't surface one or the field is missing on a
      pre-provenance entry.
    * ``history_sync_id`` — UUID string referencing the
      ``conversation_sync`` lineage entry that brought this message in.
      ``None`` for live (push) events.
    * ``mentioned_jids`` — list of WhatsApp jids explicitly mentioned in
      the message (Baileys'
      ``message.extendedTextMessage.contextInfo.mentionedJid``). Slack and
      other platforms leave this ``None``; WhatsApp messages without
      mentions surface it as an empty list. Read by
      ``MentionsWorm._match_whatsapp`` to decide whether the bot was
      addressed without scanning the raw payload. (Wave B1.1, 2026-05-06.)
    * ``platform_user_id`` — the platform-native user identifier for the
      sender (Slack ``U0AV…`` id; WhatsApp DM jid like ``<digits>@s.whatsapp.net``).
      Distinct from ``sender_person`` (which is a UUIDv5 hash of this for
      stable cross-platform identity joins). Read by
      ``WhatsAppOrganicDiscoveryReactivity`` to fire ``person_proposed`` on
      previously-unseen jids. ``None`` for pre-provenance Slack entries
      (pre-2026-05-07); writers populate it going forward. (Wave 2026-05-07
      morning, post-wire-fix.)

    All five provenance fields default so historical entries
    (pre-2026-05-05 / pre-2026-05-06 / pre-2026-05-07) parse cleanly via
    ``model_validate`` per the schema-evolution doctrine's Rule 2
    (additive-only).
    """

    kind: ClassVar[str] = "chat_received"
    channel_id: str
    message_id: str
    sender_person: UUID
    text: str
    classification: Classification
    delivery_mode: Literal["push", "history_sync"] = "push"
    platform_ts: datetime | None = None
    history_sync_id: str | None = None
    mentioned_jids: list[str] | None = None
    platform_user_id: str | None = None


class ChatSentPayload(EntryPayload):
    kind: ClassVar[str] = "chat_sent"
    channel_id: str
    message_id: str
    text: str
    in_reply_to: str | None = None
    attribution: dict[str, Any]
    speech_act: SpeechAct = "answer"


# ---------------------------------------------------------------------------
# Conversation sync — lineage for bulk historical-message imports.
#
# One PEVR cycle per reconnect / initial-connect / channel-join event from a
# channel platform. Per-message ``ChatReceivedPayload`` entries from the
# sync carry ``history_sync_id`` pointing back at this entry's ref_id, so
# replay-by-sync_id queries can scope to "all 50 messages from that
# WhatsApp reconnect" without scanning the full chat_received stream.
# ---------------------------------------------------------------------------


class ConversationSyncPayload(EntryPayload):
    """Lineage for a bulk import of historical messages from a channel platform.

    Emitted as one PEVR cycle per reconnect / initial-connect / channel-join.
    Per-message ``ChatReceivedPayload`` entries from the sync carry
    ``history_sync_id`` pointing back at this sync's ``ref_id``.

    Quadrant: ``passive_deterministic`` — sync sessions are background
    bookkeeping, not user-initiated probabilistic actions.

    Status transitions:
      * ``in_progress`` — sync session opened, messages still flowing.
      * ``completed`` — quiet-window elapsed or platform signaled done.
      * ``interrupted`` — connection dropped mid-sync; partial.

    Per the schema-evolution doctrine (Addendum 2, Section A), this is
    the 75th concrete kind in KIND_REGISTRY; well under the 100 freeze-pause
    threshold.
    """

    kind: ClassVar[str] = "conversation_sync"
    sync_id: UUID
    platform: str  # "slack" | "whatsapp" | "discord" | ...
    install_id: str | None = None
    channels: list[str] = Field(default_factory=list)
    trigger: Literal["initial_connect", "reconnect", "channel_join"]
    started_at: datetime
    completed_at: datetime | None = None
    message_count: int = 0
    earliest_ts: datetime | None = None
    latest_ts: datetime | None = None
    status: Literal["in_progress", "completed", "interrupted"] = "in_progress"

    @field_validator("started_at")
    @classmethod
    def _tz_aware_started_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("started_at must be tz-aware")
        return v

    @field_validator("completed_at")
    @classmethod
    def _tz_aware_completed_at(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("completed_at must be tz-aware")
        return v

    @field_validator("earliest_ts")
    @classmethod
    def _tz_aware_earliest_ts(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("earliest_ts must be tz-aware")
        return v

    @field_validator("latest_ts")
    @classmethod
    def _tz_aware_latest_ts(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("latest_ts must be tz-aware")
        return v


# ---------------------------------------------------------------------------
# Chat reply PEVR (4) — the worm's send-a-message cycle
#
# One PEVR cycle per outbound reply attempt: propose → execute → verify →
# resolve. All four entries share `chat_reply_id` for join. Audit-only at v1
# (no projection table fold; the projection-builder folds them as no-ops per
# Doctrine Rule 4).
# ---------------------------------------------------------------------------


class ChatReplyProposedPayload(EntryPayload):
    """Worm-side intent to send a chat reply (P of the chat-reply PEVR cycle).

    Auto-registers in KIND_REGISTRY via __init_subclass__.

    target_kind = "chat_reply_proposed".
    Fields:
        chat_reply_id   - UUID, distinguishes one reply attempt from another
        channel_id      - destination channel (string id, native to the platform)
        speech_act      - Literal["answer", "proposal", "clarification"]
        text            - what the worm intends to say
        in_reply_to     - optional message_id this reply threads under
        domain_id       - optional domain context (for trace + governance)
    """

    kind: ClassVar[str] = "chat_reply_proposed"
    chat_reply_id: UUID
    channel_id: str
    speech_act: SpeechAct
    text: str
    in_reply_to: str | None = None
    domain_id: UUID | None = None


class ChatReplyExecutedPayload(EntryPayload):
    """The actual ChannelAdapter.send call (E of the chat-reply PEVR cycle).

    target_kind = "chat_reply_executed".
    Fields:
        chat_reply_id           - joins to the propose entry
        channel_id              - same as propose
        platform                - "slack" | "discord" | "teams" | ...
        adapter_call_started_at - when the send began
        adapter_call_ended_at   - when the send returned
    """

    kind: ClassVar[str] = "chat_reply_executed"
    chat_reply_id: UUID
    channel_id: str
    platform: str
    adapter_call_started_at: datetime
    adapter_call_ended_at: datetime


class ChatReplyVerifiedPayload(EntryPayload):
    """The send-succeeded-or-failed observation (V of the chat-reply PEVR cycle).

    target_kind = "chat_reply_verified".
    Fields:
        chat_reply_id - joins to propose
        passed        - True iff ChannelAdapter.send returned a MessageRef
        message_ref   - the platform-native id of the sent message (None on fail)
        error         - failure reason (when passed=False)
    """

    kind: ClassVar[str] = "chat_reply_verified"
    chat_reply_id: UUID
    passed: bool
    message_ref: str | None = None
    error: str | None = None


class ChatReplyResolvedPayload(EntryPayload):
    """Keep-or-discard outcome (R of the chat-reply PEVR cycle).

    target_kind = "chat_reply_resolved".
    Fields:
        chat_reply_id - joins to propose
        outcome       - "keep" | "discard"
        rationale     - intent-conveying prose
    """

    kind: ClassVar[str] = "chat_reply_resolved"
    chat_reply_id: UUID
    outcome: Literal["keep", "discard"]
    rationale: str


# ---------------------------------------------------------------------------
# Gate / kpi / experiment / policy (4)
# ---------------------------------------------------------------------------


class GateFiredPayload(EntryPayload):
    kind: ClassVar[str] = "gate_fired"
    gate: str
    outcome: Literal["allowed", "blocked", "warned"]
    subject_ref: str
    reason: str


class KpiAnsweredPayload(EntryPayload):
    kind: ClassVar[str] = "kpi_answered"
    question: str
    answer: str
    sql_ref: str
    answer_hash: str
    sources: list[UUID]


class HeuristicExperimentPayload(EntryPayload):
    """DEPRECATED — no longer emitted; retained for replay compatibility.

    The original emitter (``wormbase_core.heuristic_loop.HeuristicLoop``)
    was deleted in Wave C₁ of the research-worm extraction (zero production
    callers at deletion time). Historical ledgers in deployed tenants may
    still contain ``heuristic_experiment`` entries, so the payload schema
    remains unchanged and replays continue to deserialize cleanly.

    New autoresearch work emits the canonical ``propose → execute → verify
    → resolve`` sequence via ``wormbase_research_loop`` instead.
    """

    DEPRECATED: ClassVar[bool] = True
    kind: ClassVar[str] = "heuristic_experiment"
    experiment_id: UUID
    metric: str
    before: str
    after: str
    kept: bool


class PolicyAppliedPayload(EntryPayload):
    kind: ClassVar[str] = "policy_applied"
    policy_id: UUID
    applied_to_ref: str
    outcome: Literal["masked", "redacted", "rejected", "applied"]


# ---------------------------------------------------------------------------
# Inference (1) — added by 2B review for cache provenance
# ---------------------------------------------------------------------------


class InferenceServedPayload(EntryPayload):
    kind: ClassVar[str] = "inference_served"
    request_id: UUID
    served_by: Literal["kimi", "gemma", "claude", "cache"]
    is_fallback: bool
    cache_key: str
    latency_ms: int


class InferenceCacheRefreshedPayload(EntryPayload):
    """Audit entry for ``make refresh-inference-cache``.

    Inference responses are cached for hash-stable replays of demo runs
    (an ``inference_served`` row tagged ``served_by="cache"`` proves
    a cache hit). When the cache is rotated — at the start of a fresh
    demo, after a model upgrade, or via the Makefile target — the
    refresh writes one of these rows so the substrate carries provenance
    for the cache turnover. ``entries_invalidated`` is the row count
    that was deleted; ``reason`` is intent-conveying prose.

    Phase 1 Task 1A: registry 76 → 77, well under the Rule-5 freeze
    threshold (100 in Doctrine Addendum 2 §A).
    """

    kind: ClassVar[str] = "inference_cache_refreshed"
    cache_path: str
    entries_invalidated: int = Field(ge=0)
    reason: str
    refreshed_by: str


# ---------------------------------------------------------------------------
# Medallion lake (5) — Step 2 of the canonical product arc.
#
# Bronze profiles raw bytes (hash-stable, replayable). Silver applies inferred
# schema, types, classification, and join candidates. Gold materializes
# business-ready aggregates. KpiProposed is the bridge from gold into the
# Step 3a KPI tree. LakeDiscovery is the catalog-walk summary written by the
# new sixth source-building flow.
# ---------------------------------------------------------------------------


class SourceBronzedPayload(EntryPayload):
    """Bronze: raw bytes captured + hashed for a source.

    Written by the medallion cascade after a source is first proposed; the
    entry carries the deterministic profile (byte/row/col counts, schema
    hash, mime, raw URI). Hash-stable so replay reproduces the same entry.
    """

    kind: ClassVar[str] = "source_bronzed"
    source_id: UUID
    byte_count: int
    row_count: int
    col_count: int
    schema_hash: str
    mime: str
    raw_uri: str
    profiled_at: datetime

    @field_validator("profiled_at")
    @classmethod
    def _tz_aware_profiled(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("profiled_at must be tz-aware")
        return v


class SourceSilveredPayload(EntryPayload):
    """Silver: typed schema + classification + join candidates for a source.

    Inferred-column metadata (name, type, nullable, distinct_count,
    classification) and discovered join candidates against other sources in
    the lake. Written after the bronze layer fires.
    """

    kind: ClassVar[str] = "source_silvered"
    source_id: UUID
    inferred_columns: list[dict[str, Any]]
    join_candidates: list[UUID]
    silvered_at: datetime

    @field_validator("silvered_at")
    @classmethod
    def _tz_aware_silvered(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("silvered_at must be tz-aware")
        return v


class SourceGoldedPayload(EntryPayload):
    """Gold: business-ready aggregate / chart_data / kpi for a source.

    Wraps a single derived artifact (sum, mean, count distinct, etc.) with
    a stable ``gold_artifact_id`` so downstream consumers (KPI tree, charts)
    can reference it. Written after silver fires.
    """

    kind: ClassVar[str] = "source_golded"
    source_id: UUID
    gold_artifact_id: UUID
    artifact_kind: Literal["kpi", "aggregate", "chart_data"]
    value: dict[str, Any]
    computed_at: datetime

    @field_validator("computed_at")
    @classmethod
    def _tz_aware_computed(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("computed_at must be tz-aware")
        return v


class KpiProposedPayload(EntryPayload):
    """KPI proposal: bridge from a gold aggregate into the Step 3a KPI tree.

    Written when the gold layer detects KPI-shaped aggregate (e.g. monthly
    revenue) and proposes a KPI node so the tree builder can pick it up.
    """

    kind: ClassVar[str] = "kpi_proposed"
    kpi_id: UUID
    label: str
    formula: str
    source_ids: list[UUID]
    unit: str
    owner_position: str | None = None
    proposed_at: datetime

    @field_validator("proposed_at")
    @classmethod
    def _tz_aware_proposed(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("proposed_at must be tz-aware")
        return v


class LakeDiscoveryPayload(EntryPayload):
    """Lake-discovery summary: catalog walk over an existing data lake.

    Written once per ``lake_discovery`` flow invocation summarising how
    many tables were seen and how many ``source_proposed`` entries were
    emitted as a result.
    """

    kind: ClassVar[str] = "lake_discovered"
    lake_kind: Literal["snowflake", "postgres", "s3"]
    root_uri: str
    tables_seen: int
    sources_proposed: int
    classified_at: datetime

    @field_validator("classified_at")
    @classmethod
    def _tz_aware_classified(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("classified_at must be tz-aware")
        return v


# ---------------------------------------------------------------------------
# === Step 3c: process retrieval ===
#
# The worm reads its own conversation lake (chat_received entries from the
# channel-adapter) and extracts four kinds of organisational artefacts:
#
#   * decision records  ("we decided to push the Q3 close to Friday")
#   * process maps       ("Q3 close: Bob exports → Alice reviews → ...")
#   * system map nodes   (org graph: who-asks-whom / what-channels-do-what)
#   * recurring questions ("Carol asked Q3 revenue 4 times this quarter")
#
# These payloads back the dashboard surfaces /decisions, /processes, and
# /system-map. Each entry is a normal execute-args body — the writer pairs
# it with the canonical PEVR cycle (see process_extractor.py).
# ---------------------------------------------------------------------------


class DecisionRecordedPayload(EntryPayload):
    """A decision the worm extracted from channel chatter."""

    kind: ClassVar[str] = "decision_recorded"
    decision_id: UUID
    decision_text: str
    decision_at: datetime
    channel_id: str
    decided_by_persons: list[UUID]
    evidence_message_ids: list[str]
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("decision_at")
    @classmethod
    def _tz_aware_decision_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("decision_at must be tz-aware")
        return v


class ProcessMapProposedPayload(EntryPayload):
    """A process map (ordered actor → action steps) extracted from chat."""

    kind: ClassVar[str] = "process_map_proposed"
    process_id: UUID
    process_name: str
    steps: list[dict[str, Any]]  # {order:int, actor:str, action:str, source_message_id:str}
    domain: str
    confidence: float = Field(ge=0.0, le=1.0)


class SystemMapNodePayload(EntryPayload):
    """A node in the org system map: a person, channel, or role.

    Each node carries weighted edges to other nodes (target_id may be a
    person UUID, channel id, or role name; resolution happens at read time).
    """

    kind: ClassVar[str] = "system_map_node"
    node_kind: Literal["person", "channel", "role"]
    node_id: str
    edges: list[dict[str, Any]]  # {kind:str, target_id:str, weight:float}


class RecurringQuestionPayload(EntryPayload):
    """A normalized question that's been asked ≥2 times in the lake."""

    kind: ClassVar[str] = "recurring_question"
    question_id: UUID
    normalized_question: str
    asked_by_persons: list[UUID]
    occurrences: int = Field(ge=1)
    first_seen_at: datetime
    last_seen_at: datetime
    suggested_automation: str | None = None

    @field_validator("first_seen_at", "last_seen_at")
    @classmethod
    def _tz_aware_seen(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("seen-at fields must be tz-aware")
        return v


class TopicProposedPayload(EntryPayload):
    """A silver-tier topic cluster proposed from raw chat similarity.

    Phase-2 promotion of the F.1 stub. ``TopicSynthesisReactivity``
    accumulates per-tenant chat-text clusters (using the same Jaccard +
    Levenshtein machinery as ``recurring.py``) and emits this payload
    when a cluster crosses the topic-promotion threshold (≥2 messages
    by default). The cluster signature is the normalized canonical text;
    ``topic_id`` is derived deterministically (uuid5 over the
    signature) so re-emit on a growing cluster is idempotent on the
    projection layer.

    ``label`` is the human-readable topic label, produced by the
    inference router (``call_type="summarize"``, default Gemma) on
    cluster promotion. When the router is unavailable, the heuristic
    fallback uses the canonical signature truncated to a usable size
    and ``served_by="heuristic"``; ``confidence`` correspondingly
    reflects whether the label is router-blessed or heuristic-only.

    The /topics dashboard tab (Phase 3) reads ``projection_topics``,
    which folds these entries.
    """

    kind: ClassVar[str] = "topic_proposed"
    topic_id: UUID
    label: str = Field(min_length=1, max_length=256)
    cluster_signature: str = Field(min_length=1, max_length=512)
    cluster_size: int = Field(ge=2)
    member_message_ids: list[str]
    first_seen_at: datetime
    last_seen_at: datetime
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    # Mirrors ``InferenceServedPayload.served_by`` so the projection
    # layer can attribute label provenance without joining tables.
    served_by: Literal["kimi", "gemma", "claude", "cache", "heuristic"] = "heuristic"

    @field_validator("first_seen_at", "last_seen_at")
    @classmethod
    def _tz_aware_topic_seen(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("seen-at fields must be tz-aware")
        return v


# ---------------------------------------------------------------------------
# === Step 5: user structure + per-user autoresearch ===
#
# Step 5 of the canonical product arc — see
# ``docs/superpowers/specs/2026-04-26-wormbase-product-arc.md``. Each tenant
# accumulates a set of (Person × Position) pairs; the worm runs a Karpathy
# autoresearch loop *per pair* (modify code → train → evaluate → keep/discard).
#
# Eight new payloads:
#   * person_registered            — onboarded person + role
#   * position_assigned            — person ↔ position mapping
#   * position_metric_added        — extending a position's metric set
#   * position_question_pattern    — observed question pattern for a position
#   * experiment_proposed          — autoresearch step 3: a per-user proposal
#   * experiment_run               — autoresearch step 4: the (mock) run log
#   * experiment_resolved          — autoresearch step 5: keep|discard outcome
#   * metric_observed              — periodic headline-metric sample for a
#                                    position; powers the per-user sparkline
#
# Position is a free-form string (e.g. "cfo", "data_engineer") rather than a
# Literal so customers can extend the set without a schema migration. The
# canonical seed set lives in
# ``apps/worm-core/src/wormbase_core/positions.py``.
# ---------------------------------------------------------------------------


PersonRole = Literal["admin", "owner", "member", "observer"]
ExperimentOutcome = Literal["keep", "discard"]


class PersonRegisteredPayload(EntryPayload):
    """A person was registered for this tenant (onboarding installer, invitee)."""

    kind: ClassVar[str] = "person_registered"
    person_id: UUID
    name: str
    email: str | None = None
    role: PersonRole = "member"
    registered_at: datetime

    @field_validator("registered_at")
    @classmethod
    def _tz_aware_registered_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("registered_at must be tz-aware")
        return v


class PositionAssignedPayload(EntryPayload):
    """Person ↔ Position assignment.

    The first ``position_assigned`` for a person seeds Step 5's autoresearch
    scope; subsequent assignments overwrite (latest wins).
    """

    kind: ClassVar[str] = "position_assigned"
    person_id: UUID
    position: str
    assigned_by_person_id: UUID | None = None
    at: datetime

    @field_validator("at")
    @classmethod
    def _tz_aware_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("at must be tz-aware")
        return v


class PositionMetricAddedPayload(EntryPayload):
    """DEPRECATED (per 2026-06-04 doctrine review Addendum 4 §C).

    Intent-doc-only kind: declared at module load but never wired to a
    producer or consumer. The "extending the metric set for a position"
    intent has not materialized into a shipped pipeline; if it does in
    the future, prefer a new fresh kind name with clearer semantic
    (e.g. `position_metric_proposed` matching the lake-side triple pattern).
    Class remains registered to honor Rule 1 (kinds-forever).

    Weight is a 0..1 importance dial used by the autoresearch loop when
    picking the headline metric to optimise.
    """

    kind: ClassVar[str] = "position_metric_added"
    position: str
    metric_id: str
    weight: float = Field(ge=0.0, le=1.0)
    by_person_id: UUID | None = None


class PositionQuestionPatternPayload(EntryPayload):
    """DEPRECATED (per 2026-06-04 doctrine review Addendum 4 §C).

    Intent-doc-only kind: declared at module load but never wired to a
    producer or consumer. The "observed question pattern for a position"
    intent has not materialized into a shipped pipeline. Class remains
    registered to honor Rule 1 (kinds-forever).

    An observed question pattern for a position (e.g. CFO: "what's our…").
    """

    kind: ClassVar[str] = "position_question_pattern"
    position: str
    pattern: str
    frequency_observed: int = Field(ge=1)
    last_seen_at: datetime

    @field_validator("last_seen_at")
    @classmethod
    def _tz_aware_last_seen_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("last_seen_at must be tz-aware")
        return v


class ExperimentProposedPayload(EntryPayload):
    """Autoresearch step 3: an experiment proposed for a (person × position).

    W5.A4 adds the ``audience`` field so the same payload covers Person-,
    Team-, and Company-scoped experiments. Format:

        ``"person:<uuid>"`` — Person-scoped (default for backward compat).
        ``"team:<domain_uuid>"`` — Team-Domain-scoped.
        ``"company"`` — top-level KPI tree, no UUID suffix.

    Existing rows written before W5.A4 are missing the field on the wire;
    those deserialise as ``None`` and the autoresearch loop interprets
    ``None`` as ``f"person:{for_person_id}"`` (see
    ``packages/wormbase-research-loop/src/wormbase_research_loop/loop.py``).
    This avoids a
    backfill migration: pre-W5.A4 ledgers replay byte-identically.
    """

    kind: ClassVar[str] = "experiment_proposed"
    experiment_id: UUID
    for_person_id: UUID
    position: str
    headline_metric: str
    proposed_change: dict[str, Any]
    expected_delta: float
    proposed_at: datetime
    audience: str | None = None

    @field_validator("proposed_at")
    @classmethod
    def _tz_aware_proposed_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("proposed_at must be tz-aware")
        return v

    @field_validator("audience")
    @classmethod
    def _audience_format_valid(cls, v: str | None) -> str | None:
        """Accept ``None``, ``"company"``, ``"person:<uuid>"``, or ``"team:<uuid>"``.

        ``None`` is the migration-safe default for pre-W5.A4 rows. The loop
        coerces None → ``f"person:{for_person_id}"`` at read time.
        """
        if v is None:
            return v
        if v == "company":
            return v
        if v.startswith("person:") or v.startswith("team:"):
            uuid_part = v.split(":", 1)[1]
            try:
                UUID(uuid_part)
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"invalid audience UUID suffix in {v!r}; "
                    f"expected 'person:<uuid>' or 'team:<uuid>'",
                ) from exc
            return v
        raise ValueError(
            f"invalid audience {v!r}; expected None, 'company', "
            f"'person:<uuid>', or 'team:<uuid>'",
        )


class ExperimentRunPayload(EntryPayload):
    """Autoresearch step 4: an experiment was run (mocked or real)."""

    kind: ClassVar[str] = "experiment_run"
    experiment_id: UUID
    started_at: datetime
    finished_at: datetime
    log: dict[str, Any]

    @field_validator("started_at", "finished_at")
    @classmethod
    def _tz_aware_run_times(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("run timestamps must be tz-aware")
        return v


class ExperimentResolvedPayload(EntryPayload):
    """Autoresearch step 5: keep / discard with observed_delta + rationale."""

    kind: ClassVar[str] = "experiment_resolved"
    experiment_id: UUID
    outcome: ExperimentOutcome
    observed_delta: float
    rationale: str
    resolved_at: datetime

    @field_validator("resolved_at")
    @classmethod
    def _tz_aware_resolved_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("resolved_at must be tz-aware")
        return v


class MetricObservedPayload(EntryPayload):
    """A headline metric sample for a position (powers per-user sparklines)."""

    kind: ClassVar[str] = "metric_observed"
    metric_id: str
    position: str
    value: float
    observed_at: datetime
    source_id: UUID | None = None

    @field_validator("observed_at")
    @classmethod
    def _tz_aware_observed_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("observed_at must be tz-aware")
        return v


# ---------------------------------------------------------------------------
# === Identity model (Block A1 of the production-dashboard PRD) ===
#
# Three durable concepts, each backed by a ledger-projected table:
#
#   Person         — one row per real human (or service account) per tenant.
#   PersonIdentity — fan-out of platform-native ids ({platform, platform_user_id})
#                    pointing at one Person.
#   Install        — one OAuth grant per (tenant, platform).
#
# Seven payload kinds drive the lifecycle:
#
#   * person_proposed        — auto-discovery proposes a Person from chatter
#                              or admin proposes via /people.
#   * person_confirmed       — admin confirms; status flips "proposed" → "active".
#   * person_archived        — admin archives (e.g. after a merge).
#   * identity_linked        — attach a {platform, platform_user_id} to a Person.
#   * identity_unlinked      — detach (used by merge/split).
#   * install_completed      — OAuth handshake completed; oauth_grant_ref is a
#                              KMS / Vault reference, NEVER the raw token.
#   * install_revoked        — OAuth grant revoked / Person uninstalled.
#
# OAuth-grant safety: we accept only `kms://` or `vault://` prefixes for
# `oauth_grant_ref`. Raw bearer tokens, signed-JWTs, and any cleartext secret
# format are rejected at construction time so they never enter the ledger.
# ---------------------------------------------------------------------------


_OAUTH_GRANT_REF_PREFIXES: tuple[str, ...] = ("kms://", "vault://")


class PersonProposedPayload(EntryPayload):
    """A Person was proposed (worm auto-discovery or admin invitation).

    `proposed_by` is intentionally a free-form string: the worm's own
    discovery loop writes ``"worm"`` here while admin-initiated proposals
    carry the admin's UUID-as-str. The projection collapses both forms into
    a single ``proposed_by`` column.
    """

    kind: ClassVar[str] = "person_proposed"
    person_id: UUID
    tenant_id: UUID
    name: str
    email: str | None = None
    platform: str
    platform_user_id: str
    proposed_by: str  # "worm" | UUID-as-str of the proposing admin
    position: str | None = None


class PersonConfirmedPayload(EntryPayload):
    """An admin confirmed a proposed Person; status flips to "active"."""

    kind: ClassVar[str] = "person_confirmed"
    person_id: UUID
    confirmed_by: UUID


class PersonArchivedPayload(EntryPayload):
    """An admin archived a Person (e.g. after a merge or offboarding)."""

    kind: ClassVar[str] = "person_archived"
    person_id: UUID
    archived_by: UUID
    reason: str


class PersonInvitedPayload(EntryPayload):
    """Real co-admin invite emit — Onboarding Sub-wave C (2026-05-30).

    Wires Tier 2's previously-synthetic invite affordance. The invitee
    receives an email or @notify in a connected channel with a signed
    acceptance URL. Acceptance produces a confirmed Person via the
    existing ``person_proposed`` → ``person_confirmed`` flow; this
    entry records the invite intent + audit trail, not the eventual
    Person identity.

    At least one of ``invitee_email`` or ``invitee_platform_id`` MUST
    be supplied — the handler enforces this with HTTP 400 and the
    surrounding write_action helper enforces it with ``ValueError``.
    Both fields are typed ``str | None`` here so the payload class
    itself stays minimally restrictive; the at-least-one rule belongs
    at the call site (it is not a per-field validity check).

    ``role_intent`` is the admin's intended grant when the invitee
    accepts. The role_assigned PEVR is written AT acceptance time, not
    at invite time — so this field is a hint, not a binding grant.

    Quadrant: ``active_deterministic`` — admin-driven, deterministic
    output given (invitee, inviter, role_intent).

    Additive per the schema-evolution doctrine (Rule 2). Net +1 →
    KIND_REGISTRY 109 → 110 (paired with ``DomainPackSelectedPayload``
    in the same sub-wave for the 109 → 111 trajectory).
    """

    kind: ClassVar[str] = "person_invited"
    invitee_email: str | None = None
    invitee_platform_id: str | None = None  # e.g. "slack:U01ABC..."
    invited_by_person_id: UUID
    role_intent: Literal["admin", "member", "observer"] = "member"
    notes: str | None = None


class IdentityLinkedPayload(EntryPayload):
    """Attach a {platform, platform_user_id} to an existing Person.

    Written by the auto-discovery loop when an unknown platform_user_id
    matches a confirmed Person by email, and by the admin merge flow when
    two Persons collapse into one.
    """

    kind: ClassVar[str] = "identity_linked"
    person_id: UUID
    platform: str
    platform_user_id: str
    linked_by: UUID


class IdentityUnlinkedPayload(EntryPayload):
    """Detach a {platform, platform_user_id} from a Person.

    Used by the admin merge/split flow on /people. Carries full audit trail
    via `unlinked_by`.
    """

    kind: ClassVar[str] = "identity_unlinked"
    person_id: UUID
    platform: str
    platform_user_id: str
    unlinked_by: UUID


class InstallCompletedPayload(EntryPayload):
    """OAuth handshake completed for {tenant, platform}.

    The `oauth_grant_ref` MUST be an opaque KMS or Vault reference (e.g.
    ``kms://wormbase/install/abc123``), never a raw bearer token. Construction
    fails fast if the prefix is wrong so cleartext secrets cannot reach the
    ledger.
    """

    kind: ClassVar[str] = "install_completed"
    install_id: UUID
    tenant_id: UUID
    platform: str
    installer_person_id: UUID
    oauth_grant_ref: str
    scopes: list[str]
    bot_user_id: str

    @field_validator("oauth_grant_ref")
    @classmethod
    def _grant_ref_is_opaque(cls, v: str) -> str:
        if not any(v.startswith(p) for p in _OAUTH_GRANT_REF_PREFIXES):
            raise ValueError(
                "oauth_grant_ref must be an opaque reference; "
                f"expected one of {_OAUTH_GRANT_REF_PREFIXES}, got {v!r}"
            )
        return v


class InstallRevokedPayload(EntryPayload):
    """OAuth grant revoked or Person uninstalled the worm."""

    kind: ClassVar[str] = "install_revoked"
    install_id: UUID
    revoked_by: UUID


# ---------------------------------------------------------------------------
# === Roles — three independent facets (Block A2 of the production-dashboard PRD) ===
#
# A Person holds N grants across three facets simultaneously, all composable:
#
#   * tenancy   — installer | admin | member | observer
#   * domain    — owner | contributor (scoped to a domain_id)
#   * resource  — maintainer | contributor (scoped to a resource_id + resource_type)
#
# Four payload kinds drive role lifecycle:
#
#   * role_assigned             — a tenancy-facet grant (installer/admin/member/observer)
#   * role_revoked              — revoke a tenancy-facet grant for (person_id, role)
#   * domain_role_assigned      — a domain-facet grant scoped to a domain_id
#   * resource_role_assigned    — a resource-facet grant scoped to {resource_id, resource_type}
#
# Domain/resource revoke entries are intentionally absent until a downstream
# task requires them; merge/split flows on /people use ``person_archived``
# from A1 instead.
# ---------------------------------------------------------------------------


_TENANCY_ROLES: frozenset[str] = frozenset(
    {"installer", "admin", "member", "observer"},
)
_DOMAIN_ROLES: frozenset[str] = frozenset({"owner", "contributor"})
_RESOURCE_ROLES: frozenset[str] = frozenset({"maintainer", "contributor"})
_RESOURCE_TYPES: frozenset[str] = frozenset(
    {"source", "table", "kpi", "process", "policy", "domain"},
)

TenancyRole = Literal["installer", "admin", "member", "observer"]
DomainRole = Literal["owner", "contributor"]
ResourceRole = Literal["maintainer", "contributor"]
ResourceType = Literal["source", "table", "kpi", "process", "policy", "domain"]


class RoleAssignedPayload(EntryPayload):
    """Tenancy-facet role grant for a Person.

    The role must be one of the four tenancy roles. The granter is recorded
    for audit; the projection joins this with the person + the tenant.
    """

    kind: ClassVar[str] = "role_assigned"
    person_id: UUID
    role: str
    granted_by: UUID

    @field_validator("role")
    @classmethod
    def _tenancy_role_valid(cls, v: str) -> str:
        if v not in _TENANCY_ROLES:
            raise ValueError(
                f"invalid tenancy role {v!r}; expected one of "
                f"{sorted(_TENANCY_ROLES)}"
            )
        return v


class RoleRevokedPayload(EntryPayload):
    """Revoke a tenancy-facet grant for a (person_id, role) pair.

    The projection finds the matching unrevoked grant and stamps
    ``revoked_at``. The role string must still be a valid tenancy role.
    """

    kind: ClassVar[str] = "role_revoked"
    person_id: UUID
    role: str
    revoked_by: UUID

    @field_validator("role")
    @classmethod
    def _tenancy_role_valid(cls, v: str) -> str:
        if v not in _TENANCY_ROLES:
            raise ValueError(
                f"invalid tenancy role {v!r}; expected one of "
                f"{sorted(_TENANCY_ROLES)}"
            )
        return v


class DomainRoleAssignedPayload(EntryPayload):
    """Domain-facet role grant: a Person owns or contributes to a domain."""

    kind: ClassVar[str] = "domain_role_assigned"
    person_id: UUID
    domain_id: UUID
    role: str
    granted_by: UUID

    @field_validator("role")
    @classmethod
    def _domain_role_valid(cls, v: str) -> str:
        if v not in _DOMAIN_ROLES:
            raise ValueError(
                f"invalid domain role {v!r}; expected one of "
                f"{sorted(_DOMAIN_ROLES)}"
            )
        return v


class DomainPackSelectedPayload(EntryPayload):
    """Tier 2 installer picks a pre-seeded domain pack — Onboarding Sub-wave C.

    Records the parent intent of a pack-pick. The pack contents
    (domains, classifications, policies) are seeded via the existing
    ``emit_domain_registered`` + ``emit_policy_applied`` propose/execute
    cycles written by ``pack_seeder.seed_pack`` in the same PEVR batch
    sequence. This entry is the audit anchor: replay-of-record for which
    pack the installer chose, when, and at what pack_version.

    Wire-replay determinism: pack-seed fan-out is fully a function of
    ``(pack_id, pack_version)`` — the loader reads from declarative YAML
    bundled with the worm-core package. Re-running ``seed_pack`` against
    the same ``(pack_id, pack_version)`` on a fresh tenant produces the
    same domain/policy entries.

    ``pack_version`` is bumped if the bundled YAML contents change so
    audit trails distinguish installs done against different baselines.

    Quadrant: ``active_deterministic`` — admin-driven, deterministic
    output given the bundled pack YAML.

    Additive per the schema-evolution doctrine (Rule 2). Net +1 →
    KIND_REGISTRY 110 → 111 (paired with ``PersonInvitedPayload`` in
    the same sub-wave for the 109 → 111 trajectory).
    """

    kind: ClassVar[str] = "domain_pack_selected"
    pack_id: str  # "generic" | "saas" | "marketplace" | "fintech"
    pack_version: str  # e.g. "v1.0" — bumps if pack contents change
    selected_by_person_id: UUID
    notes: str | None = None


class ResourceRoleAssignedPayload(EntryPayload):
    """Resource-facet role grant: a Person maintains or contributes to a resource.

    ``resource_type`` discriminates which resource registry the
    ``resource_id`` belongs to (source / table / kpi / process / policy /
    domain). The projection stores both so downstream consumers can resolve
    against the right registry without an extra round-trip.
    """

    kind: ClassVar[str] = "resource_role_assigned"
    person_id: UUID
    resource_id: UUID
    resource_type: str
    role: str
    granted_by: UUID

    @field_validator("role")
    @classmethod
    def _resource_role_valid(cls, v: str) -> str:
        if v not in _RESOURCE_ROLES:
            raise ValueError(
                f"invalid resource role {v!r}; expected one of "
                f"{sorted(_RESOURCE_ROLES)}"
            )
        return v

    @field_validator("resource_type")
    @classmethod
    def _resource_type_valid(cls, v: str) -> str:
        if v not in _RESOURCE_TYPES:
            raise ValueError(
                f"invalid resource_type {v!r}; expected one of "
                f"{sorted(_RESOURCE_TYPES)}"
            )
        return v


# ---------------------------------------------------------------------------
# === Wave B.5 — propose-step kinds for inferred role + resource grants ===
#
# Two new kinds back PositionInferenceReactivity (G.4) and
# ResourceOwnershipReactivity (G.5). Both are *propose-step* kinds: they
# carry a confidence + signals tuple so the trace UI can explain *why* the
# worm is asking. Admin confirm-step kinds (`position_assigned`,
# `resource_role_assigned`) already exist above; the propose-step gap is
# the addition. Per Doctrine Addendum 2 §E, no adjacent kind covers the
# propose-step shape, so distinct kinds are warranted (Rule 1 verified).
# ---------------------------------------------------------------------------


class PositionProposedPayload(EntryPayload):
    """Worm-inferred position proposal for a Person.

    Emitted by ``PositionInferenceReactivity`` (G.4) when chat-signal
    scoring crosses threshold. After PEVR resolve(keep), the projection
    fold updates ``state["persons"][pid]["position"]``. The companion
    confirm-step kind is ``position_assigned`` (admin-driven assignment).

    Field semantics:
        person_id — canonical Person UUID (resolved via IdentityResolver
            before the Reactivity emits).
        position — slug-cased role name from the static positions registry
            (e.g. ``"senior_engineer"``, ``"data_analyst"``).
        confidence — float in [0.0, 1.0]. Reactivity threshold for firing
            propose is typically ≥ 0.5.
        signals — tuple of signal-token names that contributed to the
            score (e.g. ``("commit_msg", "design_doc")``). Surfaced to
            the trace UI for explainability. Default empty.
    """

    kind: ClassVar[str] = "position_proposed"
    person_id: UUID
    position: str
    confidence: float = Field(ge=0.0, le=1.0)
    signals: tuple[str, ...] = ()


class ResourceRoleProposedPayload(EntryPayload):
    """Worm-inferred resource-role proposal for a Person.

    Emitted by ``ResourceOwnershipReactivity`` (G.5) when chatter +
    data-product-consumption signals cross threshold for a
    (person, resource) pair. After PEVR resolve(keep), the projection
    fold writes a row into ``state["roles"]`` with ``facet='resource'``.
    The companion confirm-step kind is ``resource_role_assigned``.

    Field semantics:
        person_id — canonical Person UUID.
        resource_id — UUID of the resource being bound to.
        role — one of {"maintainer", "contributor"} per the resource-facet
            of the role model (CLAUDE.md §5).
        confidence — float in [0.0, 1.0].
        signals — tuple of signal-token names that contributed
            (e.g. ``("chat_mention", "data_product_consumed")``).
            Default empty.
        proposed_by — UUID of the proposer. The Reactivity passes the
            worm's own Person id; admin-driven manual proposals carry the
            admin's id. Mirrors the propose-step convention used by
            ``PersonProposedPayload`` (which uses a free-form str), but
            tightens to UUID since this propose-step always has a
            resolvable identity behind it.
    """

    kind: ClassVar[str] = "resource_role_proposed"
    person_id: UUID
    resource_id: UUID
    role: str
    confidence: float = Field(ge=0.0, le=1.0)
    signals: tuple[str, ...] = ()
    proposed_by: UUID

    @field_validator("role")
    @classmethod
    def _resource_role_valid(cls, v: str) -> str:
        if v not in _RESOURCE_ROLES:
            raise ValueError(
                f"invalid resource role {v!r}; expected one of "
                f"{sorted(_RESOURCE_ROLES)}"
            )
        return v


# ---------------------------------------------------------------------------
# === Wave H Phase 2 Task 2C — admin review of position proposals ===
#
# ``PositionInferenceReactivity`` (G.4) emits ``position_proposed`` when its
# chat-signal scoring crosses threshold; the propose-step's PEVR resolve
# updates ``state["persons"][pid]["position"]`` immediately (the projection
# is optimistic-write so the worm can speak about the inferred position
# before an admin reviews it). The admin queue surface at
# ``/people/proposals`` then lets a tenancy.admin confirm or reject the
# proposal; both outcomes write a ledger entry that the projection folds
# into ``position_review_status``.
#
# Per Doctrine §4: Rule 1 verification — no adjacent kind covers this.
# ``position_assigned`` is the *direct admin assignment* path (no
# propose precursor; admin-driven from /people).
# ``position_confirmed`` always references a prior ``position_proposed``
# entry and unlocks the ``position_review_status="confirmed"`` projection
# field. ``position_rejected`` does the inverse and clears the
# optimistic-write so the worm can re-propose later from richer signal.
# ---------------------------------------------------------------------------


class PositionConfirmedPayload(EntryPayload):
    """An admin confirmed a worm-proposed position for a Person.

    Companion to ``position_proposed`` (Wave B.5 G.3). Written via
    ``write_actions.confirm_position_proposal`` from the
    ``/people/proposals`` queue surface. Carries the position string to
    pin the confirmation to a specific proposal (a Person can have only
    one position-in-flight at any time; the latest propose-step's
    position field is the one being confirmed).

    Field semantics:
        person_id — canonical Person UUID (the one carrying the inferred
            position on the projection).
        position — the slug-cased role being confirmed; matches the
            propose-step's ``position`` field. Pinned in the entry for
            replay-time reconstruction without joining to the propose
            row.
        confirmed_by — UUID of the admin who reviewed and confirmed.
    """

    kind: ClassVar[str] = "position_confirmed"
    person_id: UUID
    position: str
    confirmed_by: UUID


class PositionRejectedPayload(EntryPayload):
    """An admin rejected a worm-proposed position for a Person.

    Companion to ``position_proposed`` (Wave B.5 G.3). Written via
    ``write_actions.reject_position_proposal`` from the
    ``/people/proposals`` queue surface. After PEVR resolve(keep), the
    projection clears the optimistic ``position`` write and flips
    ``position_review_status`` to ``"rejected"``, freeing the
    Reactivity's dedup gate so a richer-signal proposal can be made
    later.

    Field semantics:
        person_id — canonical Person UUID whose proposed position is
            being rejected.
        position — the slug-cased role being rejected; matches the
            propose-step's ``position`` field. Pinned for replay.
        rejected_by — UUID of the admin who reviewed and rejected.
        reason — optional free-form rationale (e.g. "joined as analyst,
            not engineer"). Surfaced to the trace UI for explainability.
    """

    kind: ClassVar[str] = "position_rejected"
    person_id: UUID
    position: str
    rejected_by: UUID
    reason: str | None = None


# ---------------------------------------------------------------------------
# === Data products + notebooks (Block F of the production-dashboard PRD) ===
#
# Eight payloads back the data-product / notebook surfaces (/data-products,
# /notebooks). Per PRD §16.2:
#
#   * data_product_proposed   — admin or worm proposes a new artifact
#   * data_product_generated  — artifact bytes materialized at contents_uri
#   * data_product_consumed   — a Person viewed / shared / exported the artifact
#   * data_product_archived   — admin retired a stale or duplicate artifact
#   * notebook_proposed       — multi-cell YAML notebook proposed
#   * notebook_run            — one execution of a notebook (ok | error)
#   * notebook_published      — promote a run to canonical (versioned)
#   * notebook_archived       — admin retired a notebook
#
# Cell outputs are inline JSON for primitives; large outputs (DataFrames,
# plots) materialize to object storage and the entry carries the
# `contents_uri` + `content_hash`.
# ---------------------------------------------------------------------------


_DATA_PRODUCT_KINDS: frozenset[str] = frozenset(
    {"chart", "table", "report", "process_map"},
)
_DATA_PRODUCT_SURFACES: frozenset[str] = frozenset(
    # NOTE: surfaces are additive-only per schema-evolution doctrine Rule 2.
    # "mcp", "agent", "api" added 2026-05-11 (v1.1 Task 4) for agent-gateway
    # data_products.consume tool; existing surfaces unchanged.
    {"dashboard", "chat", "voice", "export", "mcp", "agent", "api"},
)
# Day-one kernels (PRD §16.5). Future kernels (sql_snowflake, python_databricks)
# slot into the same registry.
_NOTEBOOK_KERNELS: frozenset[str] = frozenset(
    {"python_local", "python_pandas", "sql_postgres"},
)
_NOTEBOOK_RUN_STATUSES: frozenset[str] = frozenset({"ok", "error"})

# ``process_map`` was added in P10 (2026-04-29 demo-day PRD §7) to model the
# gold artifact emitted from chatter by ``RecurringQuestionProcessMapperReactivity``.
# Treated as a regular data product (same propose/generate/consume/archive
# lifecycle), with the process-map structure (nodes/edges/window/confidence)
# carried in ``DataProductProposedPayload.parameters``.
DataProductKind = Literal["chart", "table", "report", "process_map"]
DataProductSurface = Literal["dashboard", "chat", "voice", "export"]
NotebookKernel = Literal["python_local", "python_pandas", "sql_postgres"]
NotebookRunStatus = Literal["ok", "error"]


class DataProductProposedPayload(EntryPayload):
    """A data product was proposed (worm autonomous, KPI-question, admin form)."""

    kind: ClassVar[str] = "data_product_proposed"
    data_product_id: UUID
    name: str
    kind_: str = Field(alias="kind", serialization_alias="kind")
    requested_by_person_id: UUID
    sources_required: list[UUID]
    domain_id: UUID | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    prompted_by_message_id: str | None = None

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @field_validator("kind_")
    @classmethod
    def _kind_valid(cls, v: str) -> str:
        if v not in _DATA_PRODUCT_KINDS:
            raise ValueError(
                f"invalid data product kind {v!r}; expected one of "
                f"{sorted(_DATA_PRODUCT_KINDS)}"
            )
        return v


class DataProductGeneratedPayload(EntryPayload):
    """Artifact bytes were materialized at contents_uri.

    `content_hash` is the sha256-hex of the artifact bytes; replay against
    the same source_hashes must produce a bit-identical content_hash.
    """

    kind: ClassVar[str] = "data_product_generated"
    data_product_id: UUID
    contents_uri: str
    content_hash: str
    artifact_kind: str = Field(alias="kind", serialization_alias="kind")
    source_hashes: list[str]
    generated_by: str  # "worm" | UUID-as-str of the admin who triggered
    duration_ms: int = Field(ge=0)

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @field_validator("artifact_kind")
    @classmethod
    def _kind_valid(cls, v: str) -> str:
        if v not in _DATA_PRODUCT_KINDS:
            raise ValueError(
                f"invalid data product kind {v!r}; expected one of "
                f"{sorted(_DATA_PRODUCT_KINDS)}"
            )
        return v


class DataProductConsumedPayload(EntryPayload):
    """A Person (or agent) viewed / shared / exported a data product.

    Surface ∈ {dashboard, chat, voice, export, mcp, agent, api}. Channel is
    optional and filled when the consumption surface is chat/voice.

    ``consumed_by_agent_id`` (added 2026-05-11, v1.1 Task 4, additive per
    schema-evolution doctrine Rule 2): when the consumer is an agent (e.g.
    via the agent-gateway ``data_products.consume`` MCP tool), this field
    carries the AgentID string. ``consumed_by_person_id`` remains required
    — agents are 1:1 with a Person row in v1, so the Person id stands in
    when no human consumer is present.
    """

    kind: ClassVar[str] = "data_product_consumed"
    data_product_id: UUID
    consumed_by_person_id: UUID
    consumed_by_agent_id: str | None = None
    surface: str
    channel: str | None = None

    @field_validator("surface")
    @classmethod
    def _surface_valid(cls, v: str) -> str:
        if v not in _DATA_PRODUCT_SURFACES:
            raise ValueError(
                f"invalid surface {v!r}; expected one of "
                f"{sorted(_DATA_PRODUCT_SURFACES)}"
            )
        return v


class DataProductArchivedPayload(EntryPayload):
    """An admin retired a stale or duplicate artifact."""

    kind: ClassVar[str] = "data_product_archived"
    data_product_id: UUID
    archived_by: UUID
    reason: str


class NotebookProposedPayload(EntryPayload):
    """A multi-cell YAML notebook was proposed.

    Cells are list of {kind: "code"|"markdown"|"sql", source: str,
    language?: str}. Kernel discriminates execution backend.
    """

    kind: ClassVar[str] = "notebook_proposed"
    notebook_id: UUID
    name: str
    cells: list[dict[str, Any]]
    kernel: str
    proposed_by_person_id: UUID
    domain_id: UUID | None = None

    @field_validator("kernel")
    @classmethod
    def _kernel_valid(cls, v: str) -> str:
        if v not in _NOTEBOOK_KERNELS:
            raise ValueError(
                f"invalid kernel {v!r}; expected one of "
                f"{sorted(_NOTEBOOK_KERNELS)}"
            )
        return v


class NotebookRunPayload(EntryPayload):
    """One execution of a notebook.

    `cell_outputs` is a list of per-cell JSON objects (stdout, value, etc.).
    `cell_hashes` is the per-cell sha256 over (source + sorted input
    hashes). `kernel_state_hash` summarises the post-run kernel state for
    determinism gating. Status `error` indicates a cell raised or a
    resource cap fired.
    """

    kind: ClassVar[str] = "notebook_run"
    notebook_id: UUID
    run_id: UUID
    cell_outputs: list[dict[str, Any]]
    cell_hashes: list[str]
    duration_ms: int = Field(ge=0)
    kernel_state_hash: str
    status: str
    run_by: str  # "worm" | UUID-as-str of the admin who triggered

    @field_validator("status")
    @classmethod
    def _status_valid(cls, v: str) -> str:
        if v not in _NOTEBOOK_RUN_STATUSES:
            raise ValueError(
                f"invalid notebook run status {v!r}; expected one of "
                f"{sorted(_NOTEBOOK_RUN_STATUSES)}"
            )
        return v


class NotebookPublishedPayload(EntryPayload):
    """Promote a run to canonical (versioned)."""

    kind: ClassVar[str] = "notebook_published"
    notebook_id: UUID
    run_id: UUID
    owner_person_id: UUID
    domain_id: UUID | None = None
    version: str
    published_by: UUID


class NotebookArchivedPayload(EntryPayload):
    """An admin retired a notebook."""

    kind: ClassVar[str] = "notebook_archived"
    notebook_id: UUID
    archived_by: UUID
    reason: str


# ---------------------------------------------------------------------------
# === Setup mode + progress (Block G of the production-dashboard PRD §17) ===
#
# SurfaceDriver-first onboarding lands the installer on a connector grid, not on
# a chat-platform OAuth button. After the first source connects and the
# medallion cascade fires, the installer chooses how to complete setup —
# wizard (dashboard GUI) or bot (worm DM-driven conversation). Both paths
# write the same downstream ledger entries; the only divergence is the
# surface that prompted the user.
#
# Three payloads model that fork:
#
#   * setup_mode_chosen   — installer picked wizard | bot in T2.
#   * setup_completed     — final step of either path; tenant fully onboarded.
#   * setup_step_advanced — bot path tracking; per-tenant cursor over the
#                            YAML-scripted conversation steps.
#
# All three are tenant-scoped; the projection folds them into the
# `projection_installs.setup_mode` / `setup_completed_at` columns plus a
# new `projection_setup_progress` table keyed on tenant_id.
# ---------------------------------------------------------------------------


SetupMode = Literal["wizard", "bot"]


class SetupModeChosenPayload(EntryPayload):
    """Installer picked wizard or bot to complete onboarding (PRD §17.4).

    Written when the user clicks "Continue setup" in T2 and selects a path.
    Tenant-level — one mode per tenant. Admins can switch later via
    /settings (G6); the projection always reflects the latest choice.
    """

    kind: ClassVar[str] = "setup_mode_chosen"
    tenant_id: UUID
    mode: SetupMode
    chosen_by_person_id: UUID


class SetupCompletedPayload(EntryPayload):
    """Final entry for either onboarding path; tenant is fully onboarded.

    Written by the wizard's last form submit (T3 Done) or by the bot loop's
    terminal YAML step. Sets ``projection_installs.setup_completed_at``.
    """

    kind: ClassVar[str] = "setup_completed"
    tenant_id: UUID
    completed_at: datetime

    @field_validator("completed_at")
    @classmethod
    def _tz_aware_completed_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("completed_at must be tz-aware")
        return v


class SetupStepAdvancedPayload(EntryPayload):
    """Bot-path cursor advance: an installer answered step ``step_id``.

    Written by ``SetupConversationLoop`` (G5) after parsing each installer
    DM reply. The projection folds this into ``projection_setup_progress``
    so the loop can resume from the last advanced step on restart.

    ``advanced_by_person_id`` is None when the worm advances the cursor on
    its own (e.g. timeout fallback); otherwise it's the installer's UUID.
    """

    kind: ClassVar[str] = "setup_step_advanced"
    tenant_id: UUID
    step_id: str
    advanced_by_person_id: UUID | None = None


# ---------------------------------------------------------------------------
# === MCP integration (Phase 0 spike — 2026-04-27 MCP integration spec) ===
#
# ``mcp_call_received`` is the single canonical audit entry for every external
# MCP-protocol tool invocation against the WormBase MCP server. The full PEVR
# cycle wraps this entry: the propose/execute/verify/resolve quartet provides
# the hash-chain, so the writeable surface stays uniform with every other
# domain entry.
#
# Privacy property: ``args_hash`` is the sha256 hex of the canonical-encoded
# args dict; raw args are NEVER stored in the ledger so that the audit log
# itself does not leak the contents of a denied query (e.g. an attempted PII
# read). Full args may be persisted to encrypted side-storage in Phase 3.
#
# ``caller_person_id`` is None when the call carried only a bearer token and
# the token does not resolve to a Person (anonymous v1 deployments) — but
# the entry STILL lands so that "who tried, when" remains auditable.
# ---------------------------------------------------------------------------


_MCP_OUTCOMES: frozenset[str] = frozenset({"ok", "error", "denied", "timeout"})

MCPOutcome = Literal["ok", "error", "denied", "timeout"]


class MCPCallReceivedPayload(EntryPayload):
    """A single external MCP tool invocation, audited end-to-end.

    Written by ``apps/worm-core/src/wormbase_core/mcp_server.py`` for every
    inbound MCP request. The full PEVR cycle wraps this entry; this payload
    is the ``execute`` body. Replay-stable because every field is either
    a UUID (deterministic), a string, or a deterministic hash.
    """

    kind: ClassVar[str] = "mcp_call_received"
    mcp_call_id: UUID
    tenant_id: UUID
    caller_person_id: UUID | None = None
    tool_name: str
    args_hash: str
    client_ua: str | None = None
    started_at: datetime
    outcome: str
    latency_ms: int = Field(ge=0)

    @field_validator("started_at")
    @classmethod
    def _tz_aware_started_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("started_at must be tz-aware")
        return v

    @field_validator("outcome")
    @classmethod
    def _outcome_valid(cls, v: str) -> str:
        if v not in _MCP_OUTCOMES:
            raise ValueError(
                f"invalid mcp outcome {v!r}; expected one of "
                f"{sorted(_MCP_OUTCOMES)}"
            )
        return v


# ---------------------------------------------------------------------------
# === Reactivity lifecycle (W5.A1 — Reactivity Protocol + Registry) ===
#
# Four payload kinds drive the reactivity-as-data lifecycle:
#
#   * reactivity_proposed   — admin or worm proposes a new Reactivity. The
#                              implementation may already be registered in
#                              ``proposed`` state; this entry is the audit
#                              record that the propose happened.
#   * reactivity_confirmed  — admin confirms a proposed Reactivity; the
#                              registry flips its state to ``active`` and
#                              future dispatches will fire it.
#   * reactivity_disabled   — admin disables an active Reactivity. It stops
#                              firing but its prior fire history is
#                              preserved for replay.
#   * reactivity_fired      — registry recorded that a Reactivity fired
#                              against a specific ledger entry. Carries
#                              enough provenance for /trace to render
#                              "this entry triggered this reactivity, which
#                              in turn caused these PEVR cycles".
#
# Per the W5.A1 brief: every write the registry performs is a full PEVR
# cycle wrapping one of these four kinds, so the entries are byte-equivalent
# to other reactivity-emitted entries on the same target_kind. Replay-safe.
# ---------------------------------------------------------------------------


_REACTIVITY_SCOPES: frozenset[str] = frozenset(
    {"company", "team", "domain", "person"},
)

ReactivityScopeLiteral = Literal["company", "team", "domain", "person"]


class ReactivityProposedPayload(EntryPayload):
    """A Reactivity was proposed (admin or worm).

    ``predicate_spec`` / ``condition_spec`` / ``action_spec`` are
    free-form dicts. They document the proposed behaviour for audit /
    eventual code-synthesis paths; today they're filled by the
    Reactivity author at registration time. Future Reactivities
    (chat-proposed) will populate them with structured rules.
    """

    kind: ClassVar[str] = "reactivity_proposed"
    reactivity_id: str
    name: str
    description: str
    scope: str
    predicate_spec: dict[str, Any] = Field(default_factory=dict)
    condition_spec: dict[str, Any] = Field(default_factory=dict)
    action_spec: dict[str, Any] = Field(default_factory=dict)
    proposed_by: str  # "worm" | UUID-as-str of the proposing admin

    @field_validator("scope")
    @classmethod
    def _scope_valid(cls, v: str) -> str:
        if v not in _REACTIVITY_SCOPES:
            raise ValueError(
                f"invalid reactivity scope {v!r}; expected one of "
                f"{sorted(_REACTIVITY_SCOPES)}"
            )
        return v


class ReactivityConfirmedPayload(EntryPayload):
    """An admin confirmed a proposed Reactivity; state flips to active."""

    kind: ClassVar[str] = "reactivity_confirmed"
    reactivity_id: str
    confirmed_by: str  # UUID-as-str (kept str for symmetry with proposed_by)


class ReactivityDisabledPayload(EntryPayload):
    """An admin disabled an active Reactivity.

    Disabled Reactivities stay in the registry and keep their fire
    history; they just don't fire on new entries. Re-confirmation can
    re-activate them via a separate ``reactivity_confirmed`` entry.
    """

    kind: ClassVar[str] = "reactivity_disabled"
    reactivity_id: str
    disabled_by: str  # UUID-as-str
    reason: str


class ReactivityFiredPayload(EntryPayload):
    """A Reactivity fired against ``source_seq``.

    ``action_seqs`` are the ledger seqs of the PEVR cycle the
    Reactivity emitted (typically four entries: propose, execute,
    verify, resolve). /trace renders this as a fan-out: source_seq →
    reactivity_id → action_seqs.

    ``budget_used`` is the per-axis count this fire charged against
    rolling-day budgets (e.g. ``{"per_owner": 1, "per_domain": 1,
    "per_tenant": 1}``). The dashboard's reactivity card shows this
    as "today's burn" against the cap.
    """

    kind: ClassVar[str] = "reactivity_fired"
    reactivity_id: str
    source_seq: int = Field(ge=0)
    novelty_key: str = ""
    action_seqs: list[int] = Field(default_factory=list)
    budget_used: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# === Phenomenon-gap detection (W5.A3 — phenomenon_gaps reactivities) ===
#
# Single polymorphic entry kind for the four phenomenon-gap detectors. When
# a chat statement references something the org doesn't have (KPI, Domain,
# Process, Reactivity), the corresponding detector fires this entry to
# audit the detection AND triggers the relevant ``propose_*`` PEVR cycle
# for admin confirmation.
#
# The single-kind-with-discriminator pattern is preferred over four parallel
# kinds because:
#
#   * /trace and /activity render a unified "phenomenon-gap" lane filterable
#     by ``kind``. Four kinds would force the dashboard to special-case each.
#   * The propose_* cycle that follows is ALWAYS the canonical proposer for
#     the gap kind (kpi_proposed / domain_proposed / process_map_proposed /
#     reactivity_proposed); the gap entry is the heads-up, the proposal is
#     the actual write.
#   * Future detectors (concept-gap, policy-gap) slot into the same kind
#     by extending the discriminator — no new entry kind, no new schema
#     migration.
# ---------------------------------------------------------------------------


_PHENOMENON_GAP_KINDS: frozenset[str] = frozenset(
    {"kpi", "domain", "process", "reactivity"},
)

PhenomenonGapKind = Literal["kpi", "domain", "process", "reactivity"]


# ---------------------------------------------------------------------------
# === Resource conversation lifecycle (W5.A2 — Statement-to-Owner) ===
#
# When the worm hears a statement in a channel that semantically references a
# resource owned by some Person (e.g. Bob says "our churn is up in Europe" →
# Carol owns retention), it opens a "resource conversation" with the owner. A
# resource conversation has three lifecycle entries:
#
#   * resource_conversation_proposed  — the worm proposed a DM to the owner
#                                        carrying the statement + pinned
#                                        resources. Written when the
#                                        StatementToOwnerReactivity fires.
#   * resource_conversation_replied   — the owner (or anyone in the thread)
#                                        replied. Written when channel-adapter
#                                        observes a reply targeting the
#                                        ``conversation_id``.
#   * resource_conversation_resolved  — the conversation reached an outcome:
#                                        a decision was extracted, a process
#                                        was updated, the owner muted, or no
#                                        action was taken. Written by the
#                                        owner via the dashboard or by an
#                                        admin via /people.
#
# All three entries are tenant-scoped and reference a stable ``conversation_id``
# UUID that ties them together. /trace renders the lifecycle as a single
# threaded artifact with the owner, statement, and pinned resources.
# ---------------------------------------------------------------------------


_RESOURCE_CONVERSATION_OUTCOMES: frozenset[str] = frozenset(
    {"decision", "process_update", "no_action", "muted"},
)

ResourceConversationOutcome = Literal[
    "decision", "process_update", "no_action", "muted",
]


class ResourceConversationProposedPayload(EntryPayload):
    """The worm proposed a resource-conversation DM to a Person (W5.A2).

    Written by ``StatementToOwnerReactivity.fire`` after it has:

      1. semantically matched a chat statement to a topic (KPI / source /
         domain / process), with confidence ≥ threshold (default 0.6),
      2. resolved the topic's owning Person via ``owner_lookup``,
      3. aggregated the topic's pinned resources via ``resource_aggregator``,
      4. sent the formatted DM via the channel adapter.

    ``conversation_id`` is the stable handle that ``replied`` and
    ``resolved`` entries reference. ``statement_seq`` points at the
    chat_received entry that triggered the reactivity (so /trace can render
    the original statement). ``resources`` is a free-form dict carrying the
    pinned-resource bundle (KPI / sources / decisions / processes / data
    products) — the dashboard's ResourceConversationsCard renders it.

    ``channel`` is the platform-specific channel ref of the DM the worm
    opened (e.g. ``slack:D012345``). The channel-adapter's send path
    populates this when the DM lands.
    """

    kind: ClassVar[str] = "resource_conversation_proposed"
    conversation_id: UUID
    topic: dict[str, Any]
    owner_id: UUID
    resources: dict[str, Any] = Field(default_factory=dict)
    statement_seq: int = Field(ge=0)
    channel: str


class ResourceConversationRepliedPayload(EntryPayload):
    """A reply landed in an active resource-conversation thread (W5.A2).

    Written when channel-adapter observes a Person reply targeting the
    ``conversation_id`` (typically the owner replying in the worm's DM
    thread). ``replier_id`` is the Person UUID; ``content`` is the raw
    reply text; ``seq`` is the ledger seq of the corresponding
    ``chat_received`` entry, so /trace can thread the reply back to the
    canonical chat envelope.
    """

    kind: ClassVar[str] = "resource_conversation_replied"
    conversation_id: UUID
    replier_id: UUID
    content: str
    seq: int = Field(ge=0)


class ResourceConversationResolvedPayload(EntryPayload):
    """A resource conversation reached a terminal outcome (W5.A2).

    Outcome ∈ {``decision``, ``process_update``, ``no_action``, ``muted``}:

      * ``decision``      — owner promoted the thread to a decision record;
                            ``decision_seq`` points at the
                            ``emit_decision_recorded`` entry.
      * ``process_update``— owner promoted the thread to a process-map
                            update; ``decision_seq`` points at the
                            corresponding ``emit_process_map_proposed``.
      * ``no_action``     — owner reviewed and acknowledged but didn't act.
      * ``muted``         — owner toggled
                            ``Person.preferences.resource_conversations`` so
                            future statements on this topic don't fire.

    ``decision_seq`` is optional and only present when the outcome links to
    another ledger entry. ``resolved_by`` is the Person UUID who resolved.
    """

    kind: ClassVar[str] = "resource_conversation_resolved"
    conversation_id: UUID
    outcome: str
    resolved_by: UUID
    decision_seq: int | None = None

    @field_validator("outcome")
    @classmethod
    def _outcome_valid(cls, v: str) -> str:
        if v not in _RESOURCE_CONVERSATION_OUTCOMES:
            raise ValueError(
                f"invalid resource_conversation outcome {v!r}; expected one "
                f"of {sorted(_RESOURCE_CONVERSATION_OUTCOMES)}"
            )
        return v

    @field_validator("decision_seq")
    @classmethod
    def _decision_seq_nonneg(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("decision_seq must be >= 0 if provided")
        return v


class PhenomenonGapDetectedPayload(EntryPayload):
    """A phenomenon gap was detected from chat (W5.A3).

    Discriminated on ``kind`` ∈ {kpi, domain, process, reactivity}. Carries
    enough provenance for an admin to understand:

      * what was referenced (``referenced_in_seq`` — the chat_received entry
        whose text triggered the detector)
      * what we propose to add (``suggested_proposal`` — a free-form dict
        whose shape depends on the gap kind; the corresponding propose_*
        write_action is the canonical consumer)
      * how confident the detector was (``confidence`` ∈ [0, 1])
      * a stable novelty_key so repeated detections of the same gap don't
        spam (e.g. ``"kpi:nps"`` or ``"reactivity:friday-quality-review"``)

    The proposal write that follows this entry is the actual ``propose_*``
    PEVR cycle; this entry is the audit trace pointing at it. /trace
    threads them via ``referenced_in_seq``.
    """

    kind: ClassVar[str] = "phenomenon_gap_detected"
    gap_kind: str = Field(alias="kind", serialization_alias="kind")
    referenced_in_seq: int = Field(ge=0)
    suggested_proposal: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    novelty_key: str

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @field_validator("gap_kind")
    @classmethod
    def _gap_kind_valid(cls, v: str) -> str:
        if v not in _PHENOMENON_GAP_KINDS:
            raise ValueError(
                f"invalid phenomenon gap kind {v!r}; expected one of "
                f"{sorted(_PHENOMENON_GAP_KINDS)}"
            )
        return v


# ---------------------------------------------------------------------------
# === Metrics publication (Demo-day P1 — composite_score + per-scope keep-rate) ===
#
# ``metrics_keep_rate_published`` is the audit entry written by the nightly
# ``keep_rate_publisher`` job in ``apps/worm-core/src/wormbase_core/
# keep_rate_publisher.py``. One entry per (scope, day) tuple. The job is
# idempotent — re-running for the same (scope, day) is a no-op (the
# projection layer dedupes on the natural key).
#
# Scope is one of ``person | team | company`` mirroring the autoresearch
# loop's audience scopes (W5.A4). The ratio is ``kept / total`` over
# ``experiment_resolved`` entries observed in the trailing 24h window
# anchored at ``day``.
#
# Per CLAUDE.md invariant 7 (auditable governance), the entry carries
# ``published_by`` (the actor that ran the job — typically ``"worm"`` for
# the nightly cron, or a UUID-as-str when triggered by an admin) and
# ``published_at`` (the wall-clock timestamp of the publication, distinct
# from the ``day`` window-anchor).
# ---------------------------------------------------------------------------


_KEEP_RATE_SCOPES: frozenset[str] = frozenset({"person", "team", "company"})

KeepRateScope = Literal["person", "team", "company"]


class MetricsKeepRatePublishedPayload(EntryPayload):
    """Per-scope per-day keep-rate snapshot, written by ``keep_rate_publisher``.

    The payload is byte-stable for replay: ``ratio`` is recomputed from
    ``kept / total`` (or 0.0 when ``total == 0``) so the projection can
    re-derive it without relying on the original write's float
    formatting.
    """

    kind: ClassVar[str] = "metrics_keep_rate_published"
    scope: str
    day: str  # ISO-8601 date (YYYY-MM-DD), the trailing-24h window anchor
    kept: int = Field(ge=0)
    total: int = Field(ge=0)
    ratio: float = Field(ge=0.0, le=1.0)
    published_by: str  # "worm" | UUID-as-str of the admin who triggered
    published_at: datetime

    @field_validator("scope")
    @classmethod
    def _scope_valid(cls, v: str) -> str:
        if v not in _KEEP_RATE_SCOPES:
            raise ValueError(
                f"invalid keep-rate scope {v!r}; expected one of "
                f"{sorted(_KEEP_RATE_SCOPES)}"
            )
        return v

    @field_validator("published_at")
    @classmethod
    def _tz_aware_published_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("published_at must be tz-aware")
        return v


# ---------------------------------------------------------------------------
# === Demo-day P9 — autoresearch learn step (Karpathy loop closure) ===
#
# ``experiment_lesson`` closes the Karpathy autoresearch loop on itself: when
# an experiment is kept (``experiment_resolved`` with outcome="keep"), the
# harness extracts a structured lesson — what features (predicate, condition,
# topic, scope) actually correlated with the keep — and writes it to the
# ledger. The next ``experiment_proposed`` for the same scope reads recent
# lessons (trailing 7 days) and folds them into its rationale + feature
# weighting.
#
# Two scopes carry independent learning streams: per-Person, per-Team-Domain,
# and per-Company. Each scope reads only its own lessons (no cross-scope
# leakage). The ``applied_at`` field is None at extraction time and gets
# filled with the ledger height (seq) of the first ``experiment_proposed``
# that read this lesson — closing the loop empirically. Until ``applied_at``
# is non-None, the lesson is "extracted but never used."
#
# Per CLAUDE.md invariant 7 (auditable governance), the entry carries
# ``proposed_by`` so the projection layer can render attribution. The harness
# itself is the proposer (``"autoresearch_loop"``); admin-confirmed lessons
# are out of scope for this entry kind.
# ---------------------------------------------------------------------------


_LESSON_SCOPES: frozenset[str] = frozenset({"person", "team", "company"})

LessonScope = Literal["person", "team", "company"]


class ExperimentLessonPayload(EntryPayload):
    """Structured lesson extracted from a kept experiment (P9 — learn step).

    Fields per PRD §7 P9:

    - ``prior_keep_id`` — entry id of the ``experiment_resolved`` (kept) row
      this lesson was extracted from. Joins back to the kept experiment for
      provenance / trace navigation.
    - ``scope`` — one of ``"person" | "team" | "company"`` mirroring the
      autoresearch audience scopes (W5.A4). Lessons are read by the same-
      scope proposer only.
    - ``lesson_text`` — human-readable lesson, surfaced on /research and
      folded into the next proposer's rationale string. Must be non-trivial:
      "kept because score=0.8" is too thin; the text should name which
      features correlated with the keep.
    - ``lesson_features`` — structured dict of feature → value strings
      (predicates, conditions, topics that drove the keep). Used by the
      proposer for feature weighting; surface alongside ``lesson_text``.
    - ``applied_to_proposer`` — which proposer module reads this lesson
      (``"autoresearch_loop"`` for now; future per-position or per-domain
      proposers can carry their own marker).
    - ``applied_at`` — ledger height (seq) of the first ``experiment_proposed``
      that consumed this lesson; ``None`` until first applied. Closing the
      loop empirically: a lesson with ``applied_at == None`` was extracted
      but never used by the proposer (a learning-loop hygiene signal).
    - ``proposed_by`` — the harness that extracted the lesson (carry per
      CLAUDE.md invariant 7).
    - ``extracted_at`` — wall-clock at extraction; tz-aware.
    """

    kind: ClassVar[str] = "experiment_lesson"
    prior_keep_id: UUID
    scope: str
    lesson_text: str = Field(min_length=1)
    lesson_features: dict[str, str]
    applied_to_proposer: str = Field(min_length=1)
    applied_at: int | None = None
    proposed_by: str = Field(min_length=1)
    extracted_at: datetime

    @field_validator("scope")
    @classmethod
    def _scope_valid(cls, v: str) -> str:
        if v not in _LESSON_SCOPES:
            raise ValueError(
                f"invalid lesson scope {v!r}; expected one of "
                f"{sorted(_LESSON_SCOPES)}"
            )
        return v

    @field_validator("applied_at")
    @classmethod
    def _applied_at_non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("applied_at must be >= 0 if present")
        return v

    @field_validator("extracted_at")
    @classmethod
    def _tz_aware_extracted_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("extracted_at must be tz-aware")
        return v


# ---------------------------------------------------------------------------
# === Tenant signup — multi-tenancy v2 (Phase 1 Task 1B.B) ===
#
# Two entry kinds drive tenant creation:
#
#   * tenant_signup_initiated — written the moment a Slack OAuth callback
#     fires for an unknown workspace, OR a magic-link request endpoint
#     accepts an email. Carries the tentative slug + display name +
#     signup_email + the pending-token hash so the matching completion
#     step can verify the request is the same one the initiator started.
#
#   * tenant_signup_completed — written after the signup is fully
#     installed: Slack signup writes this immediately after the
#     install_completed cycle inside complete_install; magic-link writes
#     this when the confirm endpoint binds the evaluator to a demo
#     tenant.
#
# Both entries fold into projection_tenants (registered in 1B.A) which
# is the source of truth for the dashboard's tenant list. Status starts
# at 'pending' on signup_initiated and transitions to 'active' on
# signup_completed.
#
# Signup_source is a closed enum {slack_oauth, email_magic_link, demo_seed,
# bootstrapped}. Suspend / delete / export entry kinds are reserved for
# Phase 4 polish and are explicitly NOT registered here — per doctrine,
# kinds are forever and we don't reserve names without an implementation.
# ---------------------------------------------------------------------------


_SIGNUP_SOURCES: frozenset[str] = frozenset(
    {"slack_oauth", "email_magic_link", "demo_seed", "bootstrapped"},
)

SignupSource = Literal[
    "slack_oauth", "email_magic_link", "demo_seed", "bootstrapped",
]


# ---------------------------------------------------------------------------
# === Tenant quota consumption (final wave item #7, 2026-05-13) ===
#
# Emitted by ``LedgerQuotaTracker`` (the opt-in tenant-policy ledger
# emission impl of the ``QuotaTracker`` Protocol) to surface per-tenant
# MCP-request quota consumption into the ledger for SOC-2 audit.
#
# Periodic, not per-request. The tracker accumulates consumption in-memory
# and emits one entry every ``count_threshold`` requests OR every
# ``time_threshold_seconds`` per tenant, whichever fires first. The
# ``triggered_by`` discriminator records which threshold cut the window.
# On quota_exhausted, emission is immediate so the deny moment is
# captured in the audit trail.
#
# For SOC-2 audit: a tenant's full quota-consumption history is
# reconstructable from this entry kind + the rolling-window cadence pin
# (count + time thresholds, both knobs are on the ``LedgerQuotaTracker``
# constructor). Replay determinism: the in-memory window state IS
# recomputable from these entries via the cadence pins, so replay
# produces equivalent (not identical-tick-by-tick) state.
#
# Optional-Effect Injection doctrine §6.4 — this is the 7th case
# (after Wave 4 TenantRouter, Wave 5 SseStreamTransport-with-probe,
# and the multi-tenant routing close-out's tagged follow-up). Default
# OFF: without ``WORMBASE_TENANT_QUOTA_LEDGER=true``, the byte-identical
# Path 4 InMemoryQuotaTracker behavior is preserved.
# ---------------------------------------------------------------------------


_TENANT_QUOTA_TRIGGERS: tuple[str, ...] = (
    "count_threshold",
    "time_threshold",
    "quota_exhausted",
)


class TenantQuotaConsumedPayload(EntryPayload):
    """Periodic ledger entry summarizing per-tenant MCP quota consumption.

    Emitted by ``LedgerQuotaTracker`` at a configurable cadence — every
    ``count_threshold`` requests (default 100) OR every
    ``time_threshold_seconds`` seconds (default 300) per tenant,
    whichever fires first. On ``triggered_by="quota_exhausted"`` the
    emission is immediate so the deny moment is captured in the audit
    trail rather than amortized into the next periodic window.

    For SOC-2 audit: a tenant's full quota-consumption history is
    reconstructable from this entry kind + the cadence pins; the
    in-memory rolling-window state in :class:`InMemoryQuotaTracker`
    becomes recomputable.

    KIND_REGISTRY grew 104 → 105 (additive per schema-evolution doctrine
    Rule 2; under the 120-kind Wave F Addendum 1 ceiling). The 7th case
    of Optional-Effect Injection doctrine §6.4.
    """

    kind: ClassVar[str] = "tenant_quota_consumed"
    tenant_slug: str = Field(min_length=1)
    consumption_count: int = Field(ge=0)
    quota_limit: int = Field(ge=1)
    quota_remaining: int = Field(ge=0)
    window_start_ts: datetime
    window_end_ts: datetime
    triggered_by: Literal["count_threshold", "time_threshold", "quota_exhausted"]

    @field_validator("window_start_ts", "window_end_ts")
    @classmethod
    def _ts_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("window timestamps must be tz-aware")
        return v


class TenantEngineRegisteredPayload(EntryPayload):
    """Records the registration of an engine for a tenant.

    Emitted when an operator provisions (or re-provisions) a database
    engine for a tenant via the admin tooling. The registration is the
    durable boundary between Shape A (shared engine) and Shape B
    (isolated engine-per-tenant) per the engine-per-tenant routing
    design at ``docs/superpowers/specs/2026-05-22-engine-per-tenant-
    routing-design.md`` §3.

    Field semantics:
      * ``tenant_slug`` — the registered tenant slug, lower-case
        canonical form.
      * ``engine_kind`` — ``"shared"`` means routes to the install's
        default engine (Shape A); ``"isolated"`` means routes to a
        dedicated engine via ``engine_dsn_secret_ref``.
      * ``engine_dsn_secret_ref`` — required when ``engine_kind=
        "isolated"``; MUST be ``None`` when ``engine_kind="shared"``.
        Carries a vault-style reference (e.g. ``vault://wormbase/
        tenants/<slug>/engine_dsn``); the actual DSN is resolved by
        the credential broker at construction time so the ledger holds
        only the reference, never the secret.
      * ``provisioned_at`` — wall-clock timestamp the engine became
        available.
      * ``migrated_from_shared_at`` — when an isolated engine succeeds
        a shared one for the same tenant, the timestamp the cutover
        completed. ``None`` for the first registration of a tenant.
      * ``provisioned_by_person_id`` — the admin Person who triggered
        provisioning (operator audit trail).
      * ``region`` — additive (post-rest #7, 2026-05-13). When set
        (e.g. ``"us-west-2"``, ``"eu-central-1"``), pins the tenant's
        preferred region for ops + monitoring. Default ``None`` =
        "no region preference"; preserves byte-identical Phase 1+2
        (#1) replay. Phase 1 of multi-region records + surfaces only;
        connection-pool-per-region, region-locality assertions, and
        cross-region replication policy are deferred.
      * ``hnsw_m`` / ``hnsw_ef_construction`` — additive (next-pass
        #6, 2026-05-13). Per-tenant HNSW index-build overrides
        consumed at migration-apply time by the Phase 3+4 admin
        migration tool. Defaults ``None`` = "use env globals"
        (``WORMBASE_HNSW_M`` / ``WORMBASE_HNSW_EF_CONSTRUCTION`` as
        wired by the v019 migration); preserves byte-identical
        Phase 1+2 (#1) replay for pre-tuning entries. Ranges match
        the v019 env knobs (``m ∈ [4, 64]``, ``ef_construction ∈
        [16, 256]``) so the payload-level invariant matches the
        migration-runner-level invariant. The v019 wire-up is
        deferred to the Phase 3+4 admin migration tool; these
        fields exist as the durable record the admin tool will
        consume.

    Multiple entries per tenant may exist over time as engines are
    re-provisioned or migrated. The most-recent entry by ``ts`` is the
    canonical state; replay folds the sequence into the
    ``TenantEngineRegistry`` lookup.

    Additive only — KIND_REGISTRY 105 → 106 per schema-evolution
    doctrine Rule 2 (Wave F Addendum 1 ceiling: 120). Phase 2 of the
    engine-per-tenant rollout (Phases 1+2 ship together; Phases 3+4
    deferred to operator-driven migration tooling). The ``region``
    field and the ``hnsw_m`` / ``hnsw_ef_construction`` fields are
    additive payload extensions (KIND_REGISTRY size unchanged at
    106) per the schema-evolution doctrine's additive-fields-on-
    existing-kinds allowance.
    """

    kind: ClassVar[str] = "tenant_engine_registered"
    tenant_slug: str = Field(min_length=1)
    engine_kind: Literal["shared", "isolated"]
    engine_dsn_secret_ref: str | None = None
    provisioned_at: datetime
    migrated_from_shared_at: datetime | None = None
    provisioned_by_person_id: str = Field(min_length=1)
    # Multi-region routing (post-rest #7, additive; KIND_REGISTRY size
    # unchanged at 106). Default None = "no region preference",
    # preserving byte-identical Phase 1+2 replay for pre-region
    # entries.
    region: str | None = None
    # Per-tenant HNSW index-build overrides (next-pass #6, additive;
    # KIND_REGISTRY size unchanged at 106). Default None = "use env
    # globals" (WORMBASE_HNSW_M / WORMBASE_HNSW_EF_CONSTRUCTION as
    # wired by the v019 migration). The v019 wire-up is deferred to
    # the Phase 3+4 admin migration tool; these fields are durable
    # record only. Ranges match v019: m ∈ [4, 64], ef_construction
    # ∈ [16, 256].
    hnsw_m: int | None = None
    hnsw_ef_construction: int | None = None

    @field_validator("provisioned_at", "migrated_from_shared_at")
    @classmethod
    def _ts_tz_aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError(
                "tenant_engine_registered timestamps must be tz-aware",
            )
        return v

    @field_validator("engine_dsn_secret_ref")
    @classmethod
    def _dsn_consistency_check(
        cls, v: str | None, info: Any,
    ) -> str | None:
        """Enforce the engine_kind ↔ engine_dsn_secret_ref invariant.

        * ``engine_kind="isolated"`` requires a non-empty
          ``engine_dsn_secret_ref``.
        * ``engine_kind="shared"`` requires ``engine_dsn_secret_ref=None``.

        Without this gate, a "shared" registration with a stray DSN
        reference would silently look like a misconfigured isolated
        engine to the registry resolver — a Shape B failure mode.
        """
        engine_kind = info.data.get("engine_kind")
        if engine_kind == "isolated":
            if v is None or not v.strip():
                raise ValueError(
                    "engine_dsn_secret_ref required when "
                    "engine_kind='isolated'",
                )
        elif engine_kind == "shared":
            if v is not None:
                raise ValueError(
                    "engine_dsn_secret_ref must be None when "
                    "engine_kind='shared'",
                )
        return v

    @field_validator("hnsw_m")
    @classmethod
    def _hnsw_m_in_range(cls, v: int | None) -> int | None:
        """Enforce ``hnsw_m ∈ [4, 64]`` when set — matches the v019
        migration env-knob range so the payload-level invariant lines
        up with the migration-runner-level invariant. The Phase 3+4
        admin migration tool reads this field at migration-apply time
        per tenant engine; out-of-range values would surface there as
        a build-time failure. We fail fast at write time instead."""
        if v is None:
            return v
        if not 4 <= v <= 64:
            raise ValueError(
                f"hnsw_m={v} out of range [4, 64] (matches v019 env "
                f"knob WORMBASE_HNSW_M valid range)",
            )
        return v

    @field_validator("hnsw_ef_construction")
    @classmethod
    def _hnsw_ef_construction_in_range(
        cls, v: int | None,
    ) -> int | None:
        """Enforce ``hnsw_ef_construction ∈ [16, 256]`` when set —
        matches the v019 migration env-knob range. See
        :meth:`_hnsw_m_in_range` for the parallel rationale."""
        if v is None:
            return v
        if not 16 <= v <= 256:
            raise ValueError(
                f"hnsw_ef_construction={v} out of range [16, 256] "
                f"(matches v019 env knob "
                f"WORMBASE_HNSW_EF_CONSTRUCTION valid range)",
            )
        return v


class TenantSignupInitiatedPayload(EntryPayload):
    """Tenant signup started; tenant row not yet active.

    Written for both Slack OAuth (when the workspace is unknown) and
    email magic-link (when an evaluator requests a link). Carries the
    tentative tenant slug + display name + signup_email + the pending
    token hash so the matching completion step can verify match.

    The pending_token_hash is sha256-hex of either the OAuth state token
    (for Slack OAuth signups) or the magic-link bearer token (for email
    magic-link signups). 64 lowercase hex chars; case-insensitive on
    accept.
    """

    kind: ClassVar[str] = "tenant_signup_initiated"
    tenant_id: UUID
    slug: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    signup_source: str
    signup_email: str | None
    pending_token_hash: str

    @field_validator("signup_source")
    @classmethod
    def _signup_source_valid(cls, v: str) -> str:
        if v not in _SIGNUP_SOURCES:
            raise ValueError(
                f"invalid signup_source {v!r}; expected one of "
                f"{sorted(_SIGNUP_SOURCES)}"
            )
        return v

    @field_validator("pending_token_hash")
    @classmethod
    def _hash_is_64_hex(cls, v: str) -> str:
        if len(v) != 64:
            raise ValueError(
                f"pending_token_hash must be 64 hex chars (sha256); got "
                f"{len(v)} chars"
            )
        if any(c not in "0123456789abcdefABCDEF" for c in v):
            raise ValueError(
                "pending_token_hash must be hex (0-9 a-f A-F)"
            )
        return v.lower()


class TenantSignupCompletedPayload(EntryPayload):
    """Tenant signup confirmed; tenant active.

    For Slack OAuth: emitted right after install_completed inside
    complete_install. For magic-link: emitted by the confirm endpoint
    when an evaluator is bound to a demo tenant.

    The assigned_tenant_slug is the slug the requester is bound to; for
    Slack OAuth this is the same as the slug in the matching Initiated
    entry (the workspace's slack_team_ slug); for magic-link it's the
    demo tenant slug picked by the round-robin policy.
    """

    kind: ClassVar[str] = "tenant_signup_completed"
    tenant_id: UUID
    signup_source: str
    assigned_tenant_slug: str = Field(min_length=1)
    signup_email: str | None

    @field_validator("signup_source")
    @classmethod
    def _signup_source_valid(cls, v: str) -> str:
        if v not in _SIGNUP_SOURCES:
            raise ValueError(
                f"invalid signup_source {v!r}; expected one of "
                f"{sorted(_SIGNUP_SOURCES)}"
            )
        return v


# ---------------------------------------------------------------------------
# === Catalog-mirror (Wave 1 of the Semantic Layer) ===
#
# Five entry kinds backing ``packages/wormbase-catalog-mirror/`` —
# the data-plane Protocol that imports upstream-lake structure
# (schemas, lineage, policies, semantic-layer metrics) into the
# ledger. ``CatalogSource`` (the 4th durable Protocol after
# ``SurfaceDriver``, ``ChannelAdapter``, ``MaintainableSource``) emits:
#
#   * external_catalog_imported        — full snapshot import; the
#                                        ``snapshot_hash`` is the drift
#                                        baseline used by the W5a drift
#                                        Reactivity.
#   * external_catalog_drift_detected  — periodic re-discover found
#                                        structure change vs baseline;
#                                        carries old/new hashes plus
#                                        added/removed/changed table-id
#                                        diffs for granular lineage.
#   * external_lineage_imported        — flattened (upstream, downstream)
#                                        edge list mirrored from dbt /
#                                        Snowflake / Cube / etc.
#   * external_policy_imported         — mirror of an upstream masking /
#                                        row-access policy. ``body`` is
#                                        nullable: catalog roles routinely
#                                        lack APPLY privilege on policy
#                                        bodies (Phase 0 S2 finding).
#   * external_metric_imported         — semantic-layer metric
#                                        (dbt MetricFlow / Cube / Malloy /
#                                        LookML normalized).
#
# Per the schema-evolution doctrine (Addendum 2 §A), Wave 1 grows
# KIND_REGISTRY from 83 → 88; well under the 100-kind freeze-pause
# threshold. Adds are auto-registered via ``EntryPayload.__init_subclass__``.
# ---------------------------------------------------------------------------


_EXTERNAL_POLICY_KINDS: tuple[str, ...] = ("masking", "row_access")
_EXTERNAL_CATALOG_IMPORT_MODES: tuple[str, ...] = ("initial", "refresh")


class ExternalCatalogImportedPayload(EntryPayload):
    """Initial mirror or refresh of an upstream catalog.

    ``snapshot_hash`` is the drift baseline that the W5a drift-detection
    Reactivity compares against on each periodic re-discover; equality
    means structure is unchanged, inequality emits
    ``external_catalog_drift_detected``.

    ``import_mode`` distinguishes the first-time mirror of a freshly
    connected source (``"initial"``) from a periodic re-discover pass
    (``"refresh"``). The projection uses this to render "first time"
    onboarding events distinctly from steady-state drift checks.
    """

    kind: ClassVar[str] = "external_catalog_imported"
    source_kind: str  # "dbt" | "snowflake_native" | "cube" | ...
    source_id: str
    domain_id: str
    snapshot_hash: str
    table_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    metric_count: int = Field(ge=0)
    import_mode: Literal["initial", "refresh"]


class CatalogColumnSpec(BaseModel):
    """Per-column metadata as discovered by a connector.

    Carried inside ``CatalogTableImportedPayload.columns``. The connector
    populates ``name`` from the upstream catalog and ``type`` from the
    upstream native type string when available; ``type`` is nullable so
    connectors that lack column-type introspection (e.g. raw CSV
    headers) can still emit a per-table column list.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    type: str | None = None

    @field_validator("name")
    @classmethod
    def _name_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("name must be non-empty")
        return v


class CatalogTableImportedPayload(EntryPayload):
    """Per-table catalog metadata for the catalog-mirror substrate.

    Emitted by connectors during discovery alongside the summary
    ``external_catalog_imported`` entry. One PEVR cycle per table per
    snapshot — the parent summary entry's ``snapshot_hash`` links the
    per-table rows back to the snapshot they were derived from.

    Wave 2 motivation: today's ``ExternalCatalogImportedPayload`` carries
    only ``table_count`` / ``edge_count`` / ``metric_count`` aggregates,
    not the per-table column structure that L2 TableSet and L8
    SchemaShape strategies need to compute real diffs. ``catalog_table_
    imported`` is the substrate that ships those per-table column lists
    into the ledger so the L-axis strategies have first-class structured
    input. (Sub-wave B handles emission from connectors + the reader
    fold; Sub-wave C handles dashboard surfacing.)

    Composite identity is ``(source_id, snapshot_hash, table_id)`` —
    the same logical (source, table) across multiple snapshots produces
    multiple rows because each snapshot is a point-in-time. The
    ``snapshot_hash`` leg lets strategies fetch tables from BOTH the
    current snapshot AND a baseline snapshot for diff computation.

    ``columns`` may be an empty tuple — a table with no discovered
    columns is a valid state (e.g. a permissions-denied connector that
    sees the table exists but cannot list its columns). Emitters that
    can introspect columns populate the tuple; emitters that cannot
    leave it empty without falling back to omitting the entry.

    Additive per the schema-evolution doctrine (Rule 2). Net +1 →
    KIND_REGISTRY=133, under the 150-kind ceiling raised by Wave F
    Addendum 4. L-axis family unchanged (24 of 30) — ``catalog_table_
    imported`` is substrate, not a lake-axis kind.
    """

    kind: ClassVar[str] = "catalog_table_imported"
    source_id: str
    snapshot_hash: str
    table_id: str
    columns: tuple[CatalogColumnSpec, ...] = ()

    @field_validator("source_id")
    @classmethod
    def _source_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("source_id must be non-empty")
        return v

    @field_validator("snapshot_hash")
    @classmethod
    def _snapshot_hash_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("snapshot_hash must be non-empty")
        return v

    @field_validator("table_id")
    @classmethod
    def _table_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("table_id must be non-empty")
        return v


class ExternalCatalogDriftDetectedPayload(EntryPayload):
    """Periodic re-discover detected structure change vs the prior snapshot.

    ``old_hash`` / ``new_hash`` are the snapshot baselines either side
    of the change. ``added_table_ids`` / ``removed_table_ids`` /
    ``changed_table_ids`` carry the granular diff: v1 emitters MAY
    ship hash-only with empty tuples on these fields, but the payload
    shape is forward-compatible for richer-diff emitters in later waves.
    """

    kind: ClassVar[str] = "external_catalog_drift_detected"
    source_id: str
    old_hash: str
    new_hash: str
    added_table_ids: tuple[str, ...] = ()
    removed_table_ids: tuple[str, ...] = ()
    changed_table_ids: tuple[str, ...] = ()


class ExternalLineageImportedPayload(EntryPayload):
    """Flattened (upstream, downstream) edge list mirrored from upstream catalog.

    Edges are tuples of fully-qualified node ids — e.g. dbt's
    ``"source.raw.events" → "model.staging.events"`` or Snowflake's
    ``"ACME.RAW.EVENTS" → "ACME.STAGING.EVENTS"``. The projection
    table indexes both directions for cheap lineage traversal.
    """

    kind: ClassVar[str] = "external_lineage_imported"
    source_id: str
    edges: tuple[tuple[str, str], ...]


class ExternalPolicyImportedPayload(EntryPayload):
    """Mirror of an upstream masking / row-access policy.

    ``body`` is intentionally nullable: per the Phase 0 S2 spike, a
    Snowflake catalog role typically has SHOW privileges on policies
    but not APPLY, so the policy body cannot be fetched. Drift
    detection on policy existence still works even when body is
    inaccessible. Callers that DO have APPLY populate ``body`` with
    the policy SQL; callers that don't leave it ``None``.

    ``applied_to`` lists the column / table references this policy
    is attached to upstream.
    """

    kind: ClassVar[str] = "external_policy_imported"
    source_id: str
    policy_fqn: str
    policy_kind: Literal["masking", "row_access"]
    body: str | None
    applied_to: tuple[str, ...] = ()


class ExternalMetricImportedPayload(EntryPayload):
    """Semantic-layer metric definition mirrored into the ledger.

    Normalized shape across dbt MetricFlow / Cube / Malloy / LookML.
    ``expression`` is the source SQL or DSL expression when the
    upstream catalog exposes it; ``time_grain`` and ``dimensions``
    record the metric's modeling shape so downstream KPI / chat
    surfaces can wire to the canonical name without re-deriving it.

    Promote-from-semantic-gap fields (v1.2, doctrine Rule 2 additive):
    when this payload is written by ``promote_semantic_gap`` rather
    than a catalog-import reactivity, the three optional ``domain_id``
    / ``promoted_from_gap_id`` / ``promoted_by`` fields carry the
    governance + audit context. Catalog-import writers leave them
    ``None``; promote writers set all three.
    """

    kind: ClassVar[str] = "external_metric_imported"
    source_id: str
    name: str
    expression: str | None = None
    time_grain: str | None = None
    dimensions: tuple[str, ...] = ()
    description: str | None = None

    # v1.2 additive (Rule 2): promote_semantic_gap canonicalization.
    domain_id: str | None = None
    promoted_from_gap_id: str | None = None
    promoted_by: str | None = None


# ---------------------------------------------------------------------------
# Semantic Layer Wave 2 — agent-gateway core (4 kinds)
#
# Per doctrine Addendum 3:
#   - ``agent_query`` is a SINGLE kind with FOUR phases (propose/execute/
#     verify/resolve). The phase field selects which leg of the PEVR cycle
#     the entry represents; writes go through ``Ledger.write(propose=,
#     execute_fn=, verify_fn=, resolve_fn=)``, not via per-phase emit
#     helpers.
#   - ``agent_grant`` is a SINGLE kind with a status field for active/
#     revoked rather than a separate ``agent_grant_revoked`` kind. Covers
#     both data grants (``domain.read`` / ``resource.read`` /
#     ``resource.maintainer``) and model grants (``model.access`` with a
#     budget remainder).
#   - ``credential`` is a SINGLE kind with a status field for active/
#     revoked. Covers both data tokens (Snowflake JWT etc.) and model
#     tokens (Anthropic / Kimi / etc.).
# ---------------------------------------------------------------------------


class AgentRegisteredPayload(EntryPayload):
    """An external or internal agent has been registered as a Person sub-type.

    Written by the agent-gateway during ``register_agent``. The
    ``agent_id`` is the UUID minted by the gateway and folded into
    ``projection_agents``; ``registered_by`` is the admin Person who
    authorized the registration.
    """

    kind: ClassVar[str] = "agent_registered"
    agent_id: str
    external_provider: Literal[
        "claude", "openai", "kimi", "internal_worm", "other"
    ]
    display_name: str
    registered_by: str


class AgentGrantPayload(EntryPayload):
    """Grant of a data or model capability to an agent.

    Single kind covers both grant axes; ``status`` handles assign vs
    revoke without a separate ``_revoked`` kind (per Addendum 3).

    ``grant_kind`` ∈ {domain.read, resource.read, resource.maintainer}
    are data grants; ``model.access`` is a model grant and is the only
    kind that carries ``budget_remaining_usd`` (others leave it ``None``).
    ``budget_remaining_usd`` is a string-formatted Decimal so the payload
    stays JSON-safe across the wire.
    """

    kind: ClassVar[str] = "agent_grant"
    agent_id: str
    grant_kind: Literal[
        "domain.read",
        "resource.read",
        "resource.maintainer",
        "model.access",
    ]
    grant_target: str
    status: Literal["active", "revoked"]
    granted_by: str
    budget_remaining_usd: str | None = None


class AgentMetadataUpdatedPayload(EntryPayload):
    """Mutable agent metadata update (display_name, description).

    The agent's identity is the agent_id; this entry records changes to
    human-readable metadata only. To revoke an agent, use ``agent_grant``
    status=revoked (Path 5 pattern). To update operational fields
    (kind, scopes), revoke + re-register — those are immutable per
    Phase 2 doctrine.

    Field semantics:
      * ``display_name`` / ``description`` — ``None`` means "unchanged";
        a string (including the empty string) means "set to this value".
        The agent detail page folds the most-recent non-None value per
        field over the agent's metadata history.
      * ``updated_by_person_id`` — the admin Person who made the change
        (admin role enforced by the dashboard server action; defense in
        depth at the HTTP layer).
      * ``reason`` — optional free-text audit note (e.g. "rebrand from
        Kimi research → Kimi DS-agent"). Pure-audit; not consumed by
        any read path.

    Additive only — KIND_REGISTRY 103 → 104 per schema-evolution doctrine
    Rule 2 (Wave F Addendum 1 ceiling: 120). Status-consolidation
    observed: there is no ``agent_metadata_reverted`` — emit a new
    ``agent_metadata_updated`` to undo a prior update. The agent's
    identity (agent_id, person_id, external_provider) stays immutable;
    only the human-readable surface mutates here.
    """

    kind: ClassVar[str] = "agent_metadata_updated"
    agent_id: str
    display_name: str | None = None
    description: str | None = None
    updated_by_person_id: str
    reason: str | None = None


class AgentQueryPayload(EntryPayload):
    """One entry per phase of an agent_query PEVR cycle.

    Single kind, four phases — written via
    ``Ledger.write(propose=, execute_fn=, verify_fn=, resolve_fn=, ...)``.
    The ``phase`` discriminator selects which leg of the cycle this
    entry represents; consumers fold all four into one row of
    ``projection_agent_queries`` keyed by ``audit_trail_id``.

    ``row_count`` / ``cost_usd`` / ``latency_ms`` are populated on
    verify/resolve and left ``None`` on propose/execute. ``caused_by``
    references the parent ``audit_trail_id`` when an agent query chains
    off a prior agent query (e.g. a follow-up after a metric pull).
    """

    kind: ClassVar[str] = "agent_query"
    agent_id: str
    mcp_tool: str
    args: dict
    route_mode: Literal["broker", "federate"]
    phase: Literal["propose", "execute", "verify", "resolve"]
    row_count: int | None = None
    cost_usd: str | None = None
    latency_ms: int | None = None
    caused_by: str | None = None


class CredentialPayload(EntryPayload):
    """Lifecycle of a CredentialBroker-issued, scoped, time-bounded token.

    Single kind with a status field per Addendum 3. ``credential_kind``
    distinguishes the two surfaces:

    * ``data``   — Snowflake JWT, dbt artifacts URL, etc.; ``target`` is
      the resource_id.
    * ``model``  — Anthropic / Kimi / Gemma scoped key; ``target`` is the
      ``model_kind`` string.

    ``ttl_expires_at`` is ISO-8601; ``issued_by`` is the service identity
    that called the broker (typically ``"agent-gateway"``).
    """

    kind: ClassVar[str] = "credential"
    agent_id: str
    credential_kind: Literal["data", "model"]
    target: str
    status: Literal["active", "revoked"]
    ttl_expires_at: str
    issued_by: str


# ---------------------------------------------------------------------------
# v2.A agent-as-teammate — subscription + delivery entries (2026-05-12).
#
# Three additive kinds materialize the agent-event subscription surface
# (Seam #3 closure). Per schema-evolution doctrine:
#   - ``agent_subscription_created`` carries the serialized filter +
#     transport choice; the ``AgentEventFilter`` dataclass lives in the
#     agent-gateway, but the ledger stores the dict form so replay is
#     boundary-free.
#   - ``agent_subscription_revoked`` consolidates lifecycle endings via
#     a ``reason`` discriminator rather than per-reason kinds.
#   - ``agent_event_delivered`` records every dispatch decision (success,
#     failure, no_target) so wire-replay reproduces the delivery ledger
#     and SOC-2 audits answer "what did agent X learn at time T".
#
# Net +3 → KIND_REGISTRY = 103, well under the 120-kind ceiling per
# Wave F Addendum 1.
# ---------------------------------------------------------------------------


class AgentEventDeliveredPayload(EntryPayload):
    """One delivery decision by the ``SubscriptionDispatcher`` Reactivity.

    Written as the final entry of the dispatcher's PEVR cycle for each
    (subscription, triggering_entry) pair. The
    ``(subscription_id, triggering_entry_seq)`` tuple is the idempotency
    key — replayed runs do not double-deliver.

    ``transport_used`` mirrors the subscription's chosen transport; the
    side-effect (SSE push or webhook POST) runs inside the dispatcher's
    ``execute_fn`` and is no-op'd in wire-replay mode (the entry is
    still written so replayed state matches recorded state).

    ``delivery_status`` ∈ {delivered, failed, no_target}:
      - ``delivered`` — transport accepted the event (2xx for webhook,
        queued for mcp_stream).
      - ``failed`` — transport rejected after retry exhaustion (webhook)
        or queue overflow (mcp_stream).
      - ``no_target`` — subscription is mcp_stream but no consumer is
        currently connected (event is dropped, recorded for audit).
    """

    kind: ClassVar[str] = "agent_event_delivered"
    subscription_id: str
    triggering_entry_seq: int
    triggering_entry_kind: str
    transport_used: Literal["mcp_stream", "webhook"]
    delivery_status: Literal["delivered", "failed", "no_target"]
    duration_ms: int = 0
    error: str | None = None


class AgentSubscriptionCreatedPayload(EntryPayload):
    """Agent declares interest in a ledger-event filter.

    Written by the ``agent.subscriptions.create`` MCP tool (or its
    dashboard analogue). The ``subscription_id`` is a UUID minted by
    the gateway and is the canonical handle for revocation, listing,
    and delivery accounting.

    ``filter`` is the serialized ``AgentEventFilter`` dataclass (a dict
    with ``kinds``, ``domains``, ``agent_id_ref``, ``payload_path_eq``).
    Stored as a plain dict so the ledger stays boundary-free; the
    dispatcher deserializes it via
    ``wormbase_agent_gateway.subscriptions.filter.deserialize_filter``.

    Transport choice is per-subscription:
      - ``mcp_stream`` — agent reads SSE via
        ``agent.subscriptions.stream``; ``webhook_url`` /
        ``webhook_secret_ref`` are None.
      - ``webhook`` — WormBase POSTs to ``webhook_url`` signed with
        HMAC-SHA256 over the body using a secret resolved via
        ``CredentialBroker`` from ``webhook_secret_ref`` (e.g.
        ``vault://wormbase/agents/{agent_id}/webhook_secret``). The
        raw secret never appears on the ledger.
    """

    kind: ClassVar[str] = "agent_subscription_created"
    subscription_id: str
    agent_id: str
    filter: dict
    transport: Literal["mcp_stream", "webhook"]
    webhook_url: str | None = None
    webhook_secret_ref: str | None = None
    description: str | None = None


class AgentSubscriptionRevokedPayload(EntryPayload):
    """Subscription lifecycle ending.

    Per schema-evolution doctrine Rule 3 (status consolidation): a
    single revocation kind with a ``reason`` discriminator rather than
    per-reason kinds. The dispatcher excludes subscriptions whose
    latest lifecycle entry is a revocation when computing active set.

    ``reason`` ∈ {agent_request, admin_revoked, expired, rotated}.
    ``rotated`` is the secret-rotation pattern: revoke + create-new
    in two entries, preserving subscription history.
    """

    kind: ClassVar[str] = "agent_subscription_revoked"
    subscription_id: str
    reason: Literal["agent_request", "admin_revoked", "expired", "rotated"]


# ---------------------------------------------------------------------------
# §4.5 compounding-layer entries — Semantic Layer Wave 2 Task 3
#
# Four entry kinds materialize the compounding query layer per doctrine
# Addendum 3 §B. The lifecycle goes:
#
#   agent_query (PEVR) → query_outcome_recorded → query_template_promoted
#                     ↘ query_correction_suggested
#
# and (no enclosing agent_query):
#
#   semantic_gap_proposed
#
# These are kept as SEPARATE kinds rather than folded into
# ``agent_query.resolve`` or ``external_metric_imported`` because the
# temporality is distinct (outcomes land minutes-to-days after the PEVR
# cycle closes) and the provenance differs (templates are
# agent-derived; external metrics are upstream-imported).
# ---------------------------------------------------------------------------


class QueryCorrectionSuggestedPayload(EntryPayload):
    """Backend's reflective suggestion for a failed ``agent_query``.

    Emitted by the ``lake.query.suggest_correction`` MCP tool when the
    originating ``agent_query`` has ``phase=verify`` with non-empty
    ``failure_detail``. Chains via ``original_query_id`` to the failed
    agent_query's ``audit_trail_id``.

    ``failure_kind`` ∈ {error, empty, schema_mismatch}: the class of
    failure observed during verify. ``refined_query_spec`` is the
    backend's proposed replacement (QuerySpec dump shape).
    """

    kind: ClassVar[str] = "query_correction_suggested"
    original_query_id: str
    failure_kind: Literal["error", "empty", "schema_mismatch"]
    failure_detail: str
    refined_query_spec: dict


class QueryOutcomeRecordedPayload(EntryPayload):
    """Agent's post-query outcome — used / useful / user_correction.

    Lands AFTER user feedback (minutes-to-days after
    ``agent_query.resolve``). Feeds ``projection_query_outcomes``
    (with embedding) for future semantic search + template promotion.

    Distinct from ``agent_query.resolve`` because the temporality
    differs — resolve closes the PEVR cycle synchronously while
    outcome_recorded captures asynchronous downstream feedback.

    ``quality_score`` is a string-formatted Decimal in [0.0, 1.0] so
    the payload stays JSON-safe across the wire.

    v2.B Phase 3b (2026-05-12) adds the optional ``embedding`` field —
    a write-time 768-dim vector computed by
    :class:`wormbase_inference.EmbeddingService` over ``nl_question``.
    Used by axes 1 (template promotion) + 3 (bad-pattern) for cosine
    clustering instead of substring canonicalisation. ``None`` for
    pre-Phase-3b entries OR when the embedding service is disabled
    via env (``WORMBASE_EMBEDDING_ENABLED=false``); downstream axes
    fall back to substring clustering for None-embedding entries.

    Additive per schema-evolution doctrine Rule 2 — defaults to None,
    preserves replay byte-identity for pre-Phase-3b ledgers.
    """

    kind: ClassVar[str] = "query_outcome_recorded"
    agent_query_id: str
    nl_question: str
    final_query_spec: dict
    result_summary: dict
    used: bool
    useful: bool
    user_correction: str | None = None
    quality_score: str
    # v2.B Phase 3b — additive embedding wire (Rule 2). 768-dim nomic-
    # embed-text vector populated by the EmbeddingService at write
    # time. None when the service was disabled / failed / pre-3b.
    embedding: list[float] | None = None


class QueryTemplatePromotedPayload(EntryPayload):
    """Cluster of high-quality outcomes promoted to a durable query
    template.

    Emitted by the ``OutcomeToTemplatePromotion`` W5a Reactivity
    (Wave 2 Task 8) when ≥3 outcomes on the same NL-intent cluster
    pass ``quality_score >= 0.9``. The resulting template lands in
    ``projection_query_templates`` for future low-latency re-use.

    Distinct from ``external_metric_imported``: templates are
    agent-derived from observed-outcome clusters; external metrics
    are upstream-imported via the catalog-mirror data plane (Wave 1).
    """

    kind: ClassVar[str] = "query_template_promoted"
    domain_id: str
    nl_intent: str
    query_spec: dict
    promoted_from_outcome_ids: tuple[str, ...]
    quality_score: str


class SemanticGapProposedPayload(EntryPayload):
    """Agent-reported gap — no matching metric for an NL question.

    Emitted by the ``lake.semantic.gap`` MCP tool when an agent
    cannot find a metric in the catalog that answers a user's
    question. Populates the admin metric-proposal queue at
    ``/lake/metrics-proposed`` (Wave 3 dashboard).

    Observed WITHOUT an enclosing ``agent_query`` — the agent
    short-circuits before issuing the PEVR cycle. ``reason`` ∈
    {no_match, low_confidence, ambiguous} classifies why the agent
    bailed out; ``proposed_metric_name`` is the agent's suggested
    canonical name (may be None when ``reason == "ambiguous"``).
    """

    kind: ClassVar[str] = "semantic_gap_proposed"
    agent_id: str
    nl_question: str
    reason: Literal["no_match", "low_confidence", "ambiguous"]
    proposed_metric_name: str | None = None


# ---------------------------------------------------------------------------
# v2.B Phase 2 — three new compounding axes (2026-05-12).
#
# Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=99.
# Each payload is emitted by a ``Compounding`` Reactivity in
# ``packages/wormbase-agent-gateway/src/wormbase_agent_gateway/reactivities.py``.
# All three live in the compounding-loop family (Addendum 3 §B has
# headroom under the raised 100-kind ceiling per Wave F Addendum 1).
# ---------------------------------------------------------------------------


class BadPatternProposedPayload(EntryPayload):
    """Cluster of repeated failed/unhelpful queries → known-bad-pattern.

    Emitted by the ``QueryFailureToBadPattern`` W5a Reactivity (v2.B
    Phase 2) when two or more ``query_outcome_recorded`` entries fail
    the quality gate (``used=True AND useful=False``, or
    ``quality_score < 0.3``) on the same canonical NL intent within
    a 14-day window.

    The downstream contract: the next agent's
    ``lake.semantic.search`` deprioritizes any candidate whose
    canonical intent matches an existing ``bad_pattern_proposed`` row.
    The pattern is keyed by ``canonical_intent`` (lowercase +
    whitespace-collapsed NL question), the same canonicalisation
    the template-promotion path uses.

    ``failed_outcome_ids`` records the entry_ids that prompted the
    promotion (replay-stable). ``suggested_avoidance`` is the
    Reactivity's prose hint for the next agent — what to try
    *instead*. ``failed_query_specs`` is the list of the actual
    QuerySpec dumps that failed, surfaced on the
    ``/lake/query-improvement`` page so an admin can inspect them.
    """

    kind: ClassVar[str] = "bad_pattern_proposed"
    canonical_intent: str
    failed_outcome_ids: tuple[str, ...]
    failed_query_specs: list[dict]
    failure_count: int
    suggested_avoidance: str
    domain_id: str | None = None


class SemanticGapEscalatedPayload(EntryPayload):
    """Long-unresolved ``semantic_gap_proposed`` → admin escalation.

    Emitted by the ``SemanticGapToEscalation`` W5a Reactivity (v2.B
    Phase 2) when a ``semantic_gap_proposed`` entry has no resolution
    (no matching ``external_metric_imported`` carrying the gap's id
    via ``promoted_from_gap_id``, no admin-confirmed metric covering
    the same question) after the configured age window (default 7
    days).

    Surfaces at the admin metric-proposal queue
    (``/lake/metrics-proposed``) as a higher-priority escalation
    pinned above unresolved-but-recent gaps, prompting proactive
    metric authoring.

    ``original_gap_id`` chains via the parent
    ``semantic_gap_proposed`` entry_id (str) for the full provenance
    walk on the trace view. ``days_unresolved`` is the integer count
    the Reactivity observed at promotion time (frozen, not
    recomputed on read).
    """

    kind: ClassVar[str] = "semantic_gap_escalated"
    original_gap_id: str
    nl_question: str
    reason: Literal["no_match", "low_confidence", "ambiguous"]
    days_unresolved: int
    proposed_metric_name: str | None = None


class DataProductRecommendedPayload(EntryPayload):
    """Multi-consumer cluster → ``data_product_recommended``.

    Emitted by the ``DataProductConsumptionToRecommendation`` W5a
    Reactivity (v2.B Phase 2) when ≥3 distinct agents
    (via ``data_product_consumed`` rows with
    ``surface ∈ {mcp, agent, api}``) have consumed the same data
    product within a 7-day window.

    Surfaces on ``/data-products`` as a "trending" recommendation
    chip to highlight artifacts the agent community is actively
    re-using.

    ``recommendation_score`` is the integer count of distinct
    consumers in-window at promotion time. ``consumer_agent_ids``
    is the set of AgentIDs the cluster observed (str-serialised, in
    encounter order, deduplicated). ``consumed_within_days`` is the
    look-back window the Reactivity used so the surface can show the
    promotion's temporal scope honestly.
    """

    kind: ClassVar[str] = "data_product_recommended"
    data_product_id: UUID
    recommendation_score: int
    consumer_agent_ids: tuple[str, ...]
    consumed_within_days: int


# ---------------------------------------------------------------------------
# L3 Sub-wave A — lake-side lineage-discovery loop (2026-05-29).
#
# Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=109.
# These three kinds back the projection_lineage_edges fold (v021):
#
# * ``lineage_edge_proposed`` — written by the L3 Compounding axis when one
#   or more inference strategies (naming heuristic, sample overlap, dbt
#   manifest) propose a candidate edge between two catalog tables/columns.
# * ``lineage_edge_confirmed`` — written by the admin UI when an operator
#   approves a previously-proposed edge. Forward-only — re-confirmation
#   after rejection emits a NEW entry; no mutation of prior entries.
# * ``lineage_edge_rejected`` — written by the admin UI when an operator
#   rejects a previously-proposed edge with a categorical reason.
#
# Headroom under the 120-kind Rule-5 ceiling per Wave F Addendum 1; 11
# kinds remaining after this batch. Full design spec at
# ``docs/superpowers/specs/2026-05-28-lake-side-compounding-l3-design.md``.
# ---------------------------------------------------------------------------


class LineageEdgeConfirmedPayload(EntryPayload):
    """Operator approves a previously-proposed lineage edge.

    Emitted by the admin UI (``/lake/lineage``) when a maintainer
    accepts a candidate edge. The ``edge_id`` MUST match a prior
    ``lineage_edge_proposed`` entry's ``edge_id`` for the same
    company. Forward-only: re-confirmation after a rejection emits a
    NEW entry; the prior entries are never mutated.

    ``confirmed_by_person_id`` carries the WormBase-internal Person UUID
    of the approving operator, threaded by the admin surface.
    ``notes`` is an optional free-text annotation surfaced on the
    /trace view and the edge-detail row.
    """

    kind: ClassVar[str] = "lineage_edge_confirmed"
    edge_id: str
    confirmed_by_person_id: str
    notes: str | None = None

    @field_validator("edge_id")
    @classmethod
    def _edge_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("edge_id must be non-empty")
        return v


class LineageEdgeProposedPayload(EntryPayload):
    """L3 inference strategies propose a candidate lineage edge.

    Emitted by the lake-side L3 Compounding axis (the
    ``LineageDiscovery`` Reactivity, Sub-wave B). One emission per
    strategy hit; the composite service merges + dedups across
    strategies before writing.

    ``edge_id`` is a deterministic hash of
    ``(src_table_id, src_column, tgt_table_id, tgt_column)`` — the
    same logical edge always gets the same ``edge_id`` so re-proposal
    by the same or a different strategy folds onto the same projection
    row (replay-stable dedup).

    ``confidence`` is a float in [0.0, 1.0]; out-of-range raises at
    validation time. ``strategy`` ∈ {naming_heuristic, sample_overlap,
    dbt_manifest, ...} — open enum to allow future strategy plug-ins
    without ledger churn. ``reasoning`` is a human-readable prose
    explanation; ``evidence`` is a structured dict (e.g.
    ``{"sample_overlap_ratio": 0.87, "sampled_n": 1000}``) preserved
    verbatim through the fold and surfaced on the lineage-edge detail
    panel.

    ``src_column`` / ``tgt_column`` may be ``None`` to express a
    whole-table edge (no column-level pin), which is common in
    dbt-manifest-derived lineage.
    """

    kind: ClassVar[str] = "lineage_edge_proposed"
    edge_id: str
    src_table_id: str
    src_column: str | None
    tgt_table_id: str
    tgt_column: str | None
    confidence: float
    strategy: str
    reasoning: str
    evidence: dict

    @field_validator("edge_id")
    @classmethod
    def _edge_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("edge_id must be non-empty")
        return v

    @field_validator("src_table_id")
    @classmethod
    def _src_table_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("src_table_id must be non-empty")
        return v

    @field_validator("tgt_table_id")
    @classmethod
    def _tgt_table_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("tgt_table_id must be non-empty")
        return v

    @field_validator("strategy")
    @classmethod
    def _strategy_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("strategy must be non-empty")
        return v

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_range(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0]; got {v}"
            )
        return v


class LineageEdgeRejectedPayload(EntryPayload):
    """Operator rejects a previously-proposed lineage edge.

    Emitted by the admin UI when a maintainer rejects a candidate
    edge. The ``edge_id`` MUST match a prior
    ``lineage_edge_proposed`` entry's ``edge_id`` for the same
    company. Forward-only: re-rejection after re-confirmation emits a
    NEW entry; the prior entries are never mutated.

    ``reason`` is a strict enum providing categorical signal that
    downstream strategies can use as negative-signal training (Sub-
    wave B+). ``rejected_by_person_id`` carries the WormBase-internal
    Person UUID of the rejecting operator. ``notes`` is an optional
    free-text annotation.
    """

    kind: ClassVar[str] = "lineage_edge_rejected"
    edge_id: str
    rejected_by_person_id: str
    reason: Literal[
        "false_positive",
        "wrong_direction",
        "low_confidence",
        "out_of_scope",
        "other",
    ]
    notes: str | None = None

    @field_validator("edge_id")
    @classmethod
    def _edge_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("edge_id must be non-empty")
        return v


# ---------------------------------------------------------------------------
# L7 Sub-wave A — lake-side quality-checks discovery loop (2026-05-30).
#
# Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=114.
# These three kinds back the projection_quality_checks fold (v022):
#
# * ``quality_check_proposed`` — written by the L7 Compounding axis when one
#   or more inference strategies (schema_pattern, dbt_tests, historical_stats)
#   propose a candidate quality check on a catalog table/column.
# * ``quality_check_confirmed`` — written by the admin UI when an operator
#   approves a previously-proposed check. Forward-only — re-confirmation
#   after rejection emits a NEW entry; no mutation of prior entries.
# * ``quality_check_rejected`` — written by the admin UI when an operator
#   rejects a previously-proposed check with a categorical reason.
#
# Structurally identical to the L3 lineage-edge triple — same proposed /
# confirmed / rejected shape, same forward-only semantics, same composite
# PK fold (``(company_id, check_id)``). Full design spec at
# ``docs/superpowers/specs/2026-05-30-lake-side-compounding-l7-design.md``.
# ---------------------------------------------------------------------------


class QualityCheckConfirmedPayload(EntryPayload):
    """Operator approves a previously-proposed quality check.

    Emitted by the admin UI (``/lake/quality``) when a maintainer
    accepts a candidate check. The ``check_id`` MUST match a prior
    ``quality_check_proposed`` entry's ``check_id`` for the same
    company. Forward-only: re-confirmation after a rejection emits a
    NEW entry; the prior entries are never mutated.

    ``confirmed_by_person_id`` carries the WormBase-internal Person UUID
    of the approving operator, threaded by the admin surface.
    ``notes`` is an optional free-text annotation surfaced on the
    /trace view and the check-detail row.
    """

    kind: ClassVar[str] = "quality_check_confirmed"
    check_id: str
    confirmed_by_person_id: str
    notes: str | None = None

    @field_validator("check_id")
    @classmethod
    def _check_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("check_id must be non-empty")
        return v


class QualityCheckProposedPayload(EntryPayload):
    """L7 inference strategies propose a candidate quality check.

    Emitted by the lake-side L7 Compounding axis when one or more
    strategies (``schema_pattern``, ``dbt_tests``, ``historical_stats``)
    propose a check candidate. One emission per strategy hit; the
    composite service merges + dedups across strategies before
    writing.

    ``check_id`` is a deterministic hash of
    ``(table_id, column, check_kind, config)`` — the same logical
    check always gets the same ``check_id`` so re-proposal by the
    same or a different strategy folds onto the same projection row
    (replay-stable dedup).

    ``check_kind`` is a strict 7-value enum covering the L7 check
    taxonomy. ``config`` is a structured dict carrying the per-kind
    parameters (e.g. ``{"min_rows": 100}`` for ``row_count_range``).
    ``confidence`` is a float in [0.0, 1.0]; out-of-range raises at
    validation time. ``strategy`` ∈ {schema_pattern, dbt_tests,
    historical_stats} — open enum to allow future strategy plug-ins
    without ledger churn. ``reasoning`` is a human-readable prose
    explanation; ``evidence`` is a structured dict (e.g.
    ``{"non_null_ratio": 0.998, "sampled_n": 10000}``) preserved
    verbatim through the fold and surfaced on the quality-check
    detail panel.

    ``column`` may be ``None`` to express a table-level check (e.g.
    ``row_count_range`` or ``freshness``), which is common in
    dbt-tests-derived checks.
    """

    kind: ClassVar[str] = "quality_check_proposed"
    check_id: str
    table_id: str
    column: str | None
    check_kind: Literal[
        "not_null",
        "unique",
        "freshness",
        "row_count_range",
        "enum_membership",
        "type_stability",
        "value_range",
    ]
    config: dict
    confidence: float
    strategy: str
    reasoning: str
    evidence: dict

    @field_validator("check_id")
    @classmethod
    def _check_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("check_id must be non-empty")
        return v

    @field_validator("table_id")
    @classmethod
    def _table_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("table_id must be non-empty")
        return v

    @field_validator("strategy")
    @classmethod
    def _strategy_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("strategy must be non-empty")
        return v

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_range(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0]; got {v}"
            )
        return v


class QualityCheckRejectedPayload(EntryPayload):
    """Operator rejects a previously-proposed quality check.

    Emitted by the admin UI when a maintainer rejects a candidate
    check. The ``check_id`` MUST match a prior
    ``quality_check_proposed`` entry's ``check_id`` for the same
    company. Forward-only: re-rejection after re-confirmation emits a
    NEW entry; the prior entries are never mutated.

    ``reason`` is a strict enum providing categorical signal that
    downstream strategies can use as negative-signal training (Sub-
    wave B+). ``rejected_by_person_id`` carries the WormBase-internal
    Person UUID of the rejecting operator. ``notes`` is an optional
    free-text annotation.
    """

    kind: ClassVar[str] = "quality_check_rejected"
    check_id: str
    rejected_by_person_id: str
    reason: Literal[
        "false_positive",
        "low_value",
        "wrong_threshold",
        "out_of_scope",
        "other",
    ]
    notes: str | None = None

    @field_validator("check_id")
    @classmethod
    def _check_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("check_id must be non-empty")
        return v


# ---------------------------------------------------------------------------
# L4 Sub-wave A — lake-side schema-evolution-impact discovery loop
# (2026-06-02).
#
# Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=117.
# Three kinds remain before the Wave F Addendum 1 ceiling at 120 — flagged
# in the wave's commit message + design spec.
#
# These three kinds back the projection_schema_impacts fold (v023):
#
# * ``schema_impact_proposed`` — written by the L4 Compounding axis when a
#   schema change in an upstream source propagates an impact to a
#   downstream table/column. Strategy ∈ {lineage_edge, dbt_test,
#   type_coercion}; ``upstream_lineage_edge_id`` threads back to the L3
#   edge that produced the impact (None for type_coercion proposals that
#   derive from sample stats rather than a confirmed L3 edge).
# * ``schema_impact_confirmed`` — written by the admin UI when an operator
#   approves a previously-proposed impact. Forward-only — re-confirmation
#   after rejection emits a NEW entry; no mutation of prior entries.
# * ``schema_impact_rejected`` — written by the admin UI when an operator
#   rejects a previously-proposed impact with a categorical reason.
#
# Structurally identical to the L3 lineage-edge + L7 quality-check triples —
# same proposed / confirmed / rejected shape, same forward-only semantics,
# same composite PK fold (``(company_id, impact_id)``). Full design spec at
# ``docs/superpowers/specs/2026-06-02-lake-side-compounding-l4-design.md``.
# ---------------------------------------------------------------------------


class SchemaImpactConfirmedPayload(EntryPayload):
    """Operator approves a previously-proposed schema-evolution impact.

    Emitted by the admin UI when a maintainer accepts a candidate
    impact. The ``impact_id`` MUST match a prior
    ``schema_impact_proposed`` entry's ``impact_id`` for the same
    company. Forward-only: re-confirmation after a rejection emits a
    NEW entry; the prior entries are never mutated.

    ``confirmed_by_person_id`` carries the WormBase-internal Person UUID
    of the approving operator, threaded by the admin surface.
    ``notes`` is an optional free-text annotation surfaced on the
    /trace view and the impact-detail row.
    """

    kind: ClassVar[str] = "schema_impact_confirmed"
    impact_id: str
    confirmed_by_person_id: str
    notes: str | None = None

    @field_validator("impact_id")
    @classmethod
    def _impact_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("impact_id must be non-empty")
        return v


class SchemaImpactProposedPayload(EntryPayload):
    """L4 axis emits this when a schema change in an upstream source
    propagates an impact to a downstream table/column.

    Emitted by the lake-side L4 Compounding axis (the
    ``SchemaImpactDiscovery`` Reactivity, Sub-wave B). One emission per
    strategy hit; the composite service merges + dedups across
    strategies before writing.

    ``impact_id`` is a deterministic hash of
    ``(source_id, src_table, src_column, change_kind, tgt_table_id,
    tgt_column)`` — the same logical impact always gets the same
    ``impact_id`` so re-proposal by the same or a different strategy
    folds onto the same projection row (replay-stable dedup).

    ``change_kind`` ∈ {column_added, column_dropped, column_type_changed}
    — strict enum pinning the upstream schema-evolution event class.
    ``impact_kind`` ∈ {tgt_column_orphaned, tgt_column_type_mismatch,
    tgt_column_unaware, dbt_test_breakage, type_coercion_required} —
    strict enum pinning the downstream consequence class.
    ``strategy`` ∈ {lineage_edge, dbt_test, type_coercion} — open
    string field with a non-empty guard so future strategy plug-ins
    can ship without ledger churn.

    ``upstream_lineage_edge_id`` threads back to the L3 confirmed-edge
    entry that surfaced this impact. May be ``None`` for
    ``type_coercion``-strategy proposals derived from sample-stats
    (no L3 edge required to detect a coercion-needed downstream type).

    ``confidence`` is a float in [0.0, 1.0]; out-of-range raises at
    validation time. ``reasoning`` is a human-readable prose
    explanation; ``evidence`` is a structured dict (e.g.
    ``{"upstream_change_seq": 1234, "downstream_dbt_test": "not_null"}``)
    preserved verbatim through the fold and surfaced on the
    impact-detail panel.
    """

    kind: ClassVar[str] = "schema_impact_proposed"
    impact_id: str
    source_id: str
    src_table: str
    src_column: str
    change_kind: Literal[
        "column_added",
        "column_dropped",
        "column_type_changed",
    ]
    impact_kind: Literal[
        "tgt_column_orphaned",
        "tgt_column_type_mismatch",
        "tgt_column_unaware",
        "dbt_test_breakage",
        "type_coercion_required",
    ]
    tgt_table_id: str
    tgt_column: str
    upstream_lineage_edge_id: str | None = None
    confidence: float
    strategy: str
    reasoning: str
    evidence: dict

    @field_validator("impact_id")
    @classmethod
    def _impact_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("impact_id must be non-empty")
        return v

    @field_validator("source_id")
    @classmethod
    def _source_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("source_id must be non-empty")
        return v

    @field_validator("src_table")
    @classmethod
    def _src_table_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("src_table must be non-empty")
        return v

    @field_validator("src_column")
    @classmethod
    def _src_column_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("src_column must be non-empty")
        return v

    @field_validator("tgt_table_id")
    @classmethod
    def _tgt_table_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("tgt_table_id must be non-empty")
        return v

    @field_validator("tgt_column")
    @classmethod
    def _tgt_column_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("tgt_column must be non-empty")
        return v

    @field_validator("strategy")
    @classmethod
    def _strategy_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("strategy must be non-empty")
        return v

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_range(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0]; got {v}"
            )
        return v


class SchemaImpactRejectedPayload(EntryPayload):
    """Operator rejects a previously-proposed schema-evolution impact.

    Emitted by the admin UI when a maintainer rejects a candidate
    impact. The ``impact_id`` MUST match a prior
    ``schema_impact_proposed`` entry's ``impact_id`` for the same
    company. Forward-only: re-rejection after re-confirmation emits a
    NEW entry; the prior entries are never mutated.

    ``reason`` is a strict enum providing categorical signal that
    downstream strategies can use as negative-signal training (Sub-
    wave B+). ``rejected_by_person_id`` carries the WormBase-internal
    Person UUID of the rejecting operator. ``notes`` is an optional
    free-text annotation.
    """

    kind: ClassVar[str] = "schema_impact_rejected"
    impact_id: str
    rejected_by_person_id: str
    reason: Literal[
        "false_positive",
        "already_handled",
        "low_value",
        "out_of_scope",
        "other",
    ]
    notes: str | None = None

    @field_validator("impact_id")
    @classmethod
    def _impact_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("impact_id must be non-empty")
        return v


# ---------------------------------------------------------------------------
# L5 Sub-wave A — lake-side sample-data fingerprinting discovery loop
# (2026-06-05).
#
# Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=120.
# At 120, exactly 30 headroom under the Wave F Addendum 4 ceiling at 150.
# L-axis family count = 12 of 30 cap (L3=3 + L7=3 + L4=3 + L5=3) — well
# within the L-axis family cap (Addendum 4 §E).
#
# These three kinds back the projection_semantic_types fold (v024):
#
# * ``semantic_type_proposed`` — written by the L5 Compounding axis when a
#   fingerprinting strategy proposes a semantic type for a column (e.g.
#   "this looks like an email address"). Strategy ∈ {column_name,
#   value_pattern, distribution}; ``semantic_type`` is a strict 19-value
#   Literal enum spanning identity / temporal / identifiers / geo-locale /
#   PII / metric / catch-all bands.
# * ``semantic_type_confirmed`` — written by the admin UI when an operator
#   approves a previously-proposed semantic type. Forward-only — re-
#   confirmation after rejection emits a NEW entry; no mutation of prior
#   entries.
# * ``semantic_type_rejected`` — written by the admin UI when an operator
#   rejects a previously-proposed semantic type with a categorical reason.
#   The 5th reason value is L5-specific: ``wrong_type`` (replaces L4's
#   ``already_handled`` and L7's ``wrong_threshold``).
#
# Structurally identical to the L3 lineage-edge / L7 quality-check / L4
# schema-impact triples — same proposed / confirmed / rejected shape, same
# forward-only semantics, same composite PK fold (``(company_id, type_id)``).
# Full design spec at
# ``docs/superpowers/specs/2026-06-05-lake-side-compounding-l5-design.md``.
# ---------------------------------------------------------------------------


class SemanticTypeConfirmedPayload(EntryPayload):
    """Operator approves a previously-proposed semantic type inference.

    Emitted by the admin UI when a maintainer accepts a candidate
    semantic-type proposal. The ``type_id`` MUST match a prior
    ``semantic_type_proposed`` entry's ``type_id`` for the same
    company. Forward-only: re-confirmation after a rejection emits a
    NEW entry; the prior entries are never mutated.

    ``confirmed_by_person_id`` carries the WormBase-internal Person UUID
    of the approving operator, threaded by the admin surface.
    ``notes`` is an optional free-text annotation surfaced on the
    /trace view and the semantic-type-detail row.
    """

    kind: ClassVar[str] = "semantic_type_confirmed"
    type_id: str
    confirmed_by_person_id: str
    notes: str | None = None

    @field_validator("type_id")
    @classmethod
    def _type_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("type_id must be non-empty")
        return v


class SemanticTypeProposedPayload(EntryPayload):
    """L5 axis emits this when a fingerprinting strategy proposes a
    semantic type for a column (e.g. "this looks like an email address").

    Emitted by the lake-side L5 Compounding axis (the
    ``FingerprintInferenceDiscovery`` Reactivity, Sub-wave B). One
    emission per strategy hit; the composite service merges + dedups
    across strategies before writing.

    ``type_id`` is a deterministic hash of
    ``(table_id, column, semantic_type)`` — the same logical
    column-type proposal always gets the same ``type_id`` so re-
    proposal by the same or a different strategy folds onto the same
    projection row (replay-stable dedup).

    ``semantic_type`` is a strict 19-value Literal enum spanning:
    identity (email, phone_e164, phone_us); temporal (iso_date,
    iso_datetime, unix_timestamp); identifiers (uuid_v4, uuid_v7,
    business_id); geo-locale (country_iso, language_iso,
    currency_iso); PII-sensitive (pii_name, pii_address, pii_ssn,
    pii_credit_card); metric (metric_count, metric_amount,
    metric_rate); plus a catch-all (other). New types require explicit
    doctrine review — strict Literal prevents semantic drift.

    ``strategy`` ∈ {column_name, value_pattern, distribution} — open
    string field with a non-empty guard so future strategy plug-ins
    can ship without ledger churn. Doc spec lists the canonical three.

    ``confidence`` is a float in [0.0, 1.0]; out-of-range raises at
    validation time. ``reasoning`` is a human-readable prose
    explanation; ``evidence`` is a structured dict (e.g.
    ``{"match_count": 18, "sample_n": 20, "regex": "..."}``)
    preserved verbatim through the fold and surfaced on the
    semantic-type-detail panel.
    """

    kind: ClassVar[str] = "semantic_type_proposed"
    type_id: str
    table_id: str
    column: str
    semantic_type: Literal[
        # Identity
        "email",
        "phone_e164",
        "phone_us",
        # Temporal
        "iso_date",
        "iso_datetime",
        "unix_timestamp",
        # Identifiers
        "uuid_v4",
        "uuid_v7",
        "business_id",
        # Geo/locale
        "country_iso",
        "language_iso",
        "currency_iso",
        # PII (sensitive)
        "pii_name",
        "pii_address",
        "pii_ssn",
        "pii_credit_card",
        # Metric
        "metric_count",
        "metric_amount",
        "metric_rate",
        # Catch-all
        "other",
    ]
    confidence: float
    strategy: str
    reasoning: str
    evidence: dict

    @field_validator("type_id")
    @classmethod
    def _type_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("type_id must be non-empty")
        return v

    @field_validator("table_id")
    @classmethod
    def _table_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("table_id must be non-empty")
        return v

    @field_validator("column")
    @classmethod
    def _column_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("column must be non-empty")
        return v

    @field_validator("strategy")
    @classmethod
    def _strategy_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("strategy must be non-empty")
        return v

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_range(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0]; got {v}"
            )
        return v


class SemanticTypeRejectedPayload(EntryPayload):
    """Operator rejects a previously-proposed semantic type inference.

    Emitted by the admin UI when a maintainer rejects a candidate
    semantic-type proposal. The ``type_id`` MUST match a prior
    ``semantic_type_proposed`` entry's ``type_id`` for the same
    company. Forward-only: re-rejection after re-confirmation emits a
    NEW entry; the prior entries are never mutated.

    ``reason`` is a strict 5-value enum providing categorical signal
    that downstream strategies can use as negative-signal training
    (Sub-wave B+). The L5-specific 5th value is ``wrong_type``
    (replaces L4's ``already_handled`` and L7's ``wrong_threshold``).
    ``rejected_by_person_id`` carries the WormBase-internal Person
    UUID of the rejecting operator. ``notes`` is an optional free-
    text annotation.
    """

    kind: ClassVar[str] = "semantic_type_rejected"
    type_id: str
    rejected_by_person_id: str
    reason: Literal[
        "false_positive",
        "low_value",
        "wrong_type",
        "out_of_scope",
        "other",
    ]
    notes: str | None = None

    @field_validator("type_id")
    @classmethod
    def _type_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("type_id must be non-empty")
        return v


# ---------------------------------------------------------------------------
# L6 Sub-wave A — lake-side column-level governance classification loop
# (2026-06-06).
#
# Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=123.
# At 123, exactly 27 headroom under the Wave F Addendum 4 ceiling at 150.
# L-axis family count = 15 of 30 cap (L3=3 + L7=3 + L4=3 + L5=3 + L6=3) —
# well within the L-axis family cap (Addendum 4 §E).
#
# These three kinds back the projection_column_classifications fold
# (v025). L6 is the 5th lake-side compounding axis AND the 2nd
# cross-axis chain (after L4→L3); it reads L5's confirmed semantic
# types via the new ``ConfirmedSemanticTypeReader`` Protocol (Sub-wave
# B) and proposes column-level classifications at one of the 5
# canonical governance levels:
#
# * ``column_classification_proposed`` — written by the L6 Compounding
#   axis when a strategy proposes a classification level for a column
#   (e.g. inferred PII → ``regulated``). Strategy ∈ {semantic_type,
#   naming_pattern, domain_default}. ``classification_level`` is the
#   strict 5-value Literal {public, internal, confidential, pii,
#   regulated} matching the existing governance enum. The
#   ``upstream_semantic_type_id`` field links back to L5's
#   ``projection_semantic_types`` row when strategy="semantic_type" —
#   this is the cross-axis chain that powers the "view L5 semantic
#   type →" link on the /lake/column-classification surface.
# * ``column_classification_confirmed`` — written by the admin UI when
#   an operator approves a previously-proposed classification.
#   Forward-only — re-confirmation after rejection emits a NEW entry;
#   no mutation of prior entries.
# * ``column_classification_rejected`` — written by the admin UI when
#   an operator rejects a previously-proposed classification with a
#   categorical reason. The 5th reason value is L6-specific:
#   ``wrong_level`` (replaces L5's ``wrong_type``, L4's
#   ``already_handled`` and L7's ``wrong_threshold``).
#
# Structurally identical to the L3 lineage-edge / L7 quality-check /
# L4 schema-impact / L5 semantic-type triples — same proposed /
# confirmed / rejected shape, same forward-only semantics, same
# composite PK fold (``(company_id, classification_id)``). Full design
# spec at ``docs/superpowers/specs/2026-06-06-lake-side-compounding-l6-design.md``.
# ---------------------------------------------------------------------------


# Alias for the 5-value governance classification levels. Structurally
# identical to ``Classification`` above (the source-level enum), re-
# exported under a clearer L6 name for the column-level surface. Same
# 5 canonical levels per CLAUDE.md §"Ledger-native governance"; no L6-
# specific additions.
ClassificationLevel = Literal[
    "public",
    "internal",
    "confidential",
    "pii",
    "regulated",
]


class ColumnClassificationConfirmedPayload(EntryPayload):
    """Operator approves a previously-proposed column-level classification.

    Emitted by the admin UI when a maintainer accepts a candidate
    classification proposal. The ``classification_id`` MUST match a
    prior ``column_classification_proposed`` entry's
    ``classification_id`` for the same company. Forward-only: re-
    confirmation after a rejection emits a NEW entry; the prior
    entries are never mutated.

    ``confirmed_by_person_id`` carries the WormBase-internal Person
    UUID of the approving operator, threaded by the admin surface.
    ``notes`` is an optional free-text annotation surfaced on the
    /trace view and the column-classification-detail row.
    """

    kind: ClassVar[str] = "column_classification_confirmed"
    classification_id: str
    confirmed_by_person_id: str
    notes: str | None = None

    @field_validator("classification_id")
    @classmethod
    def _classification_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("classification_id must be non-empty")
        return v


class ColumnClassificationProposedPayload(EntryPayload):
    """L6 axis emits this when a strategy proposes a classification
    level for a specific column (e.g. inferred PII → regulated).

    Emitted by the lake-side L6 Compounding axis (Sub-wave B). One
    emission per strategy hit; the composite service merges + dedups
    across strategies before writing.

    ``classification_id`` is a deterministic hash of
    ``(table_id, column, classification_level, strategy)`` minted
    upstream by the L6 inference service — the same logical column-
    classification proposal always gets the same
    ``classification_id`` so re-proposal by the same strategy folds
    onto the same projection row (replay-stable dedup).

    ``classification_level`` is the strict 5-value
    ``ClassificationLevel`` Literal {public, internal, confidential,
    pii, regulated}. These are the canonical 5 levels per CLAUDE.md
    §"Ledger-native governance"; no L6-specific additions. Drift
    prevention is enforced at the payload validator.

    ``upstream_semantic_type_id`` is the cross-axis link back to
    L5's ``projection_semantic_types.type_id`` when the strategy was
    ``semantic_type`` (i.e. this classification was inferred from a
    confirmed semantic type like ``pii_ssn`` → ``regulated``). NULL
    for ``naming_pattern`` / ``domain_default`` strategies that don't
    consult L5. The /lake/column-classification surface renders a
    "view L5 semantic type →" link when this field is set.

    ``strategy`` ∈ {semantic_type, naming_pattern, domain_default} —
    open string field with a non-empty guard so future strategy
    plug-ins can ship without ledger churn. Doc spec lists the
    canonical three.

    ``confidence`` is a float in [0.0, 1.0]; out-of-range raises at
    validation time. ``reasoning`` is a human-readable prose
    explanation; ``evidence`` is a structured dict (e.g.
    ``{"semantic_type": "pii_ssn", "regex_hit": true}``) preserved
    verbatim through the fold and surfaced on the column-
    classification-detail panel.
    """

    kind: ClassVar[str] = "column_classification_proposed"
    classification_id: str
    table_id: str
    column: str
    classification_level: ClassificationLevel
    upstream_semantic_type_id: str | None = None
    confidence: float
    strategy: str
    reasoning: str
    evidence: dict

    @field_validator("classification_id")
    @classmethod
    def _classification_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("classification_id must be non-empty")
        return v

    @field_validator("table_id")
    @classmethod
    def _table_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("table_id must be non-empty")
        return v

    @field_validator("column")
    @classmethod
    def _column_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("column must be non-empty")
        return v

    @field_validator("strategy")
    @classmethod
    def _strategy_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("strategy must be non-empty")
        return v

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_range(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0]; got {v}"
            )
        return v


class ColumnClassificationRejectedPayload(EntryPayload):
    """Operator rejects a previously-proposed column-level classification.

    Emitted by the admin UI when a maintainer rejects a candidate
    classification proposal. The ``classification_id`` MUST match a
    prior ``column_classification_proposed`` entry's
    ``classification_id`` for the same company. Forward-only: re-
    rejection after re-confirmation emits a NEW entry; the prior
    entries are never mutated.

    ``reason`` is a strict 5-value enum providing categorical signal
    that downstream strategies can use as negative-signal training
    (Sub-wave B+). The L6-specific 5th value is ``wrong_level``
    (distinct from L5's ``wrong_type``, L4's ``already_handled`` and
    L7's ``wrong_threshold``). ``rejected_by_person_id`` carries the
    WormBase-internal Person UUID of the rejecting operator.
    ``notes`` is an optional free-text annotation.
    """

    kind: ClassVar[str] = "column_classification_rejected"
    classification_id: str
    rejected_by_person_id: str
    reason: Literal[
        "false_positive",
        "low_value",
        "wrong_level",
        "out_of_scope",
        "other",
    ]
    notes: str | None = None

    @field_validator("classification_id")
    @classmethod
    def _classification_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("classification_id must be non-empty")
        return v


# ---------------------------------------------------------------------------
# L8 Sub-wave A — lake-side cross-source entity-stitching loop (2026-06-07).
#
# Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=126.
# At 126, exactly 24 headroom under the Wave F Addendum 4 ceiling at 150.
# L-axis family count = 18 of 30 cap (L3=3 + L7=3 + L4=3 + L5=3 + L6=3 +
# L8=3) — well within the L-axis family cap (Addendum 4 §E).
#
# These three kinds back the projection_entity_stitches fold (v026).
# L8 is the 6th lake-side compounding loop AND the 3rd cross-axis chain
# (after L4→L3 and L6→L5); it reads L5's confirmed semantic types via
# the same ``ConfirmedSemanticTypeReader`` Protocol L6 introduced
# (Sub-wave B) and proposes cross-source entity-stitch candidates that
# bridge two source/table/column triples sharing a probable entity
# identity (e.g. ``stripe.customers.email`` ↔ ``salesforce.contacts.email``).
#
# * ``entity_stitch_proposed`` — written by the L8 Compounding axis
#   when a strategy (``name_match`` / ``sample_overlap`` /
#   ``schema_shape``) proposes a cross-source bridge between two
#   columns referring to the same underlying entity. Each stitch
#   carries an ``entity_kind`` tag from the canonical 8-value enum
#   {person, organization, transaction, product, event, location,
#   session, other}. The ``upstream_semantic_type_id`` field links
#   back to L5's ``projection_semantic_types`` when the proposing
#   strategy consulted a confirmed semantic type (the L8→L5
#   cross-axis chain shared with L6).
# * ``entity_stitch_confirmed`` — written by the admin UI when an
#   operator approves a previously-proposed stitch. Forward-only —
#   re-confirmation after rejection emits a NEW entry; no mutation
#   of prior entries.
# * ``entity_stitch_rejected`` — written by the admin UI when an
#   operator rejects a previously-proposed stitch with a categorical
#   reason. The L8-specific 5th reason value is ``wrong_pairing``
#   (replaces L6's ``wrong_level``, L5's ``wrong_type``, L4's
#   ``already_handled`` and L7's ``wrong_threshold``).
#
# Structurally identical to the L3 / L7 / L4 / L5 / L6 triples —
# same proposed / confirmed / rejected shape, same forward-only
# semantics, same composite PK fold (``(company_id, stitch_id)``).
# Full design spec at
# ``docs/superpowers/specs/2026-06-07-lake-side-compounding-l8-design.md``.
# ---------------------------------------------------------------------------


# Alias for the 8-value canonical entity-kind enum L8 stitches tag.
# These are the 8 entity classes the L8 strategy bank can stitch
# across sources; ``other`` is the catch-all for entities outside the
# named seven. Spec §4.2.
EntityKind = Literal[
    "person",
    "organization",
    "transaction",
    "product",
    "event",
    "location",
    "session",
    "other",
]


class EntityStitchConfirmedPayload(EntryPayload):
    """Operator approves a previously-proposed cross-source entity stitch.

    Emitted by the admin UI when a maintainer accepts a candidate
    entity-stitch proposal. The ``stitch_id`` MUST match a prior
    ``entity_stitch_proposed`` entry's ``stitch_id`` for the same
    company. Forward-only: re-confirmation after a rejection emits a
    NEW entry; the prior entries are never mutated.

    ``confirmed_by_person_id`` carries the WormBase-internal Person
    UUID of the approving operator, threaded by the admin surface.
    ``notes`` is an optional free-text annotation surfaced on the
    /trace view and the entity-stitch-detail row.
    """

    kind: ClassVar[str] = "entity_stitch_confirmed"
    stitch_id: str
    confirmed_by_person_id: str
    notes: str | None = None

    @field_validator("stitch_id")
    @classmethod
    def _stitch_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("stitch_id must be non-empty")
        return v


class EntityStitchProposedPayload(EntryPayload):
    """L8 axis emits this when a strategy proposes a cross-source
    entity-stitch candidate bridging two ``(source, table, column)``
    triples that probably reference the same underlying entity.

    Emitted by the lake-side L8 Compounding axis (Sub-wave B). One
    emission per strategy hit; the composite service merges + dedups
    across strategies before writing.

    ``stitch_id`` is a deterministic hash of ``(src_source_id_a,
    src_table_a, src_column_a, src_source_id_b, src_table_b,
    src_column_b)`` minted upstream by the L8 inference service — the
    same logical pair of columns always gets the same ``stitch_id``
    so re-proposal by any strategy folds onto the same projection row
    (replay-stable dedup). The pair ordering is canonicalised
    upstream (lex order on ``source_id`` then ``table`` then
    ``column``) so ``A↔B`` and ``B↔A`` share one ``stitch_id``.

    ``src_*_a`` and ``src_*_b`` carry the two endpoint
    ``(source_id, table, column)`` triples verbatim. Validation rule:
    each of the six identifier fields must be non-empty. There is
    NO ``src_source_id_a != src_source_id_b`` constraint at this
    layer — strategies could in theory propose same-source stitches
    (e.g. two columns within one table that alias the same entity);
    drift prevention is left to strategy logic.

    ``upstream_semantic_type_id`` is the cross-axis link back to
    L5's ``projection_semantic_types.type_id`` when the strategy
    consulted a confirmed semantic type (e.g. both endpoints share
    a ``pii_email`` semantic type → stronger bridge signal). NULL
    for ``name_match`` / ``schema_shape`` strategies that don't
    consult L5. The /lake/entity-stitch surface renders a "view L5
    semantic type →" link when this field is set.

    ``entity_kind`` is the strict 8-value ``EntityKind`` Literal
    {person, organization, transaction, product, event, location,
    session, other}. Drift prevention is enforced at the payload
    validator.

    ``strategy`` ∈ {name_match, sample_overlap, schema_shape} —
    open string field with a non-empty guard so future strategy
    plug-ins can ship without ledger churn. Doc spec lists the
    canonical three.

    ``confidence`` is a float in [0.0, 1.0]; out-of-range raises at
    validation time. ``reasoning`` is a human-readable prose
    explanation; ``evidence`` is a structured dict (e.g.
    ``{"sample_overlap_pct": 0.87, "endpoints_sampled": 200}``)
    preserved verbatim through the fold and surfaced on the
    entity-stitch-detail panel.
    """

    kind: ClassVar[str] = "entity_stitch_proposed"
    stitch_id: str
    src_source_id_a: str
    src_table_a: str
    src_column_a: str
    src_source_id_b: str
    src_table_b: str
    src_column_b: str
    upstream_semantic_type_id: str | None = None
    entity_kind: EntityKind
    confidence: float
    strategy: str
    reasoning: str
    evidence: dict

    @field_validator("stitch_id")
    @classmethod
    def _stitch_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("stitch_id must be non-empty")
        return v

    @field_validator(
        "src_source_id_a",
        "src_table_a",
        "src_column_a",
        "src_source_id_b",
        "src_table_b",
        "src_column_b",
    )
    @classmethod
    def _src_field_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("src_* identifier fields must be non-empty")
        return v

    @field_validator("strategy")
    @classmethod
    def _strategy_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("strategy must be non-empty")
        return v

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_range(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0]; got {v}"
            )
        return v


class EntityStitchRejectedPayload(EntryPayload):
    """Operator rejects a previously-proposed cross-source entity stitch.

    Emitted by the admin UI when a maintainer rejects a candidate
    entity-stitch proposal. The ``stitch_id`` MUST match a prior
    ``entity_stitch_proposed`` entry's ``stitch_id`` for the same
    company. Forward-only: re-rejection after re-confirmation emits a
    NEW entry; the prior entries are never mutated.

    ``reason`` is a strict 5-value enum providing categorical signal
    that downstream strategies can use as negative-signal training
    (Sub-wave B+). The L8-specific 5th value is ``wrong_pairing``
    (distinct from L6's ``wrong_level``, L5's ``wrong_type``, L4's
    ``already_handled`` and L7's ``wrong_threshold``).
    ``rejected_by_person_id`` carries the WormBase-internal Person
    UUID of the rejecting operator. ``notes`` is an optional
    free-text annotation.
    """

    kind: ClassVar[str] = "entity_stitch_rejected"
    stitch_id: str
    rejected_by_person_id: str
    reason: Literal[
        "false_positive",
        "low_value",
        "wrong_pairing",
        "out_of_scope",
        "other",
    ]
    notes: str | None = None

    @field_validator("stitch_id")
    @classmethod
    def _stitch_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("stitch_id must be non-empty")
        return v


# ---------------------------------------------------------------------------
# L1 Sub-wave A — lake-side source-candidate triage loop (2026-06-08).
#
# Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=129.
# At 129, exactly 21 headroom under the Wave F Addendum 4 ceiling at 150.
# L-axis family count = 21 of 30 cap (L3=3 + L7=3 + L4=3 + L5=3 + L6=3 +
# L8=3 + L1=3) — 9 headroom (room for L2 + 2 future axes) within the
# L-axis family cap (Addendum 4 §E).
#
# These three kinds back the projection_source_candidates fold (v027).
# L1 is the 7th lake-side compounding loop AND the 4th day-one
# ``LakeLoopComposite[T]`` consumer (after L5, L6, L8). L1 introduces
# ZERO new cross-axis Protocol chains in the L4→L3 / L6→L5 / L8→L5
# sense — its inference reads existing first-class platform projections
# (``projection_sources``, ``projection_kpi_nodes``,
# ``projection_silver_conversations``) via lightweight Reader Protocols
# rather than peer lake-axis projections. Cross-axis chain count stays
# at 3.
#
# Naming-collision check (spec §1): the existing ``source_proposed`` /
# ``source_confirmed`` / ``source_connected`` / ``source_profiled``
# kinds are the post-promotion lifecycle of an already-decided source.
# L1 is the prequel triage layer; the ``source_candidate_*`` namespace
# is unused elsewhere in ``entries.py``. No rename, no payload schema
# change on the existing source-pipeline kinds.
#
# * ``source_candidate_proposed`` — written by the L1 Compounding axis
#   when a strategy (``kpi_gap`` / ``channel_mention`` /
#   ``complementarity``) surfaces a candidate data source. Carries a
#   ``proposed_kind`` connector-registry string (runtime-validated
#   against ``wormbase_lake_surfaces.registry.default_registry()`` — NOT
#   a ``Literal[...]`` so connector registry growth does NOT churn the
#   ledger schema, per spec §4.2 and Addendum 4 §B "SurfaceDriver registry
#   kinds are NOT KIND_REGISTRY entries; they are configuration."),
#   plus the proposed identifier, optional domain hint, confidence,
#   reasoning, and strategy-specific evidence.
# * ``source_candidate_promoted`` — written by the admin UI when an
#   operator approves a triaged candidate. Promotion synchronously
#   triggers the existing source-builder to emit a downstream
#   ``source_proposed`` entry in Sub-wave C; the optional
#   ``downstream_source_proposed_id`` threads the candidate to its
#   resulting source-pipeline row. Forward-only — re-promotion after
#   rejection emits a NEW entry; no mutation of prior entries.
# * ``source_candidate_rejected`` — written by the admin UI when an
#   operator rejects a candidate with a categorical reason. The
#   L1-specific 5th reason value is ``duplicate`` (replaces L8's
#   ``wrong_pairing``, L6's ``wrong_level``, L5's ``wrong_type``,
#   L4's ``already_handled`` and L7's ``wrong_threshold``) — reflects
#   that the most common reject reason at triage is "we already have
#   this source / something equivalent."
#
# Structurally identical to the L3 / L7 / L4 / L5 / L6 / L8 triples —
# same proposed / promoted-or-confirmed / rejected shape, same
# forward-only semantics, same composite PK fold
# (``(company_id, candidate_id)``). Full design spec at
# ``docs/superpowers/specs/2026-06-08-lake-side-compounding-l1-design.md``.
# ---------------------------------------------------------------------------


def make_candidate_id(
    *,
    proposed_kind: str,
    proposed_identifier: str,
    strategy: str,
) -> str:
    """Mint a deterministic ``candidate_id`` for L1 source-candidate dedup.

    Returns the first 32 hex chars of ``sha256("kind|identifier|strategy")``.
    The composite PK ``(company_id, candidate_id)`` on
    ``projection_source_candidates`` keys off this value, so:

    * Same strategy proposing the same source twice → same hash → folds
      onto the same projection row (natural dedup; re-emission updates
      evidence/confidence/reasoning).
    * Different strategies proposing the same source → distinct hashes
      → distinct rows (each strategy gets to make its own case to the
      admin; the dashboard surface can group them visually later).
    * Different identifiers under the same kind+strategy → distinct
      hashes → distinct rows.

    Mirrors L8's ``make_stitch_id`` shape: deterministic, opaque,
    32-char prefix. Hex-only output keeps it safe to embed in URL
    paths and SQL identifiers without escaping.
    """
    parts = f"{proposed_kind}|{proposed_identifier}|{strategy}"
    return hashlib.sha256(parts.encode()).hexdigest()[:32]


# Alias for the 5-value L1-specific reject-reason enum. ``duplicate``
# is the L1-specific 5th value (distinct from L8's ``wrong_pairing``,
# L6's ``wrong_level``, L5's ``wrong_type``, L4's ``already_handled``
# and L7's ``wrong_threshold``) reflecting the most common reject
# reason at triage. Spec §4.4.
SourceCandidateRejectReason = Literal[
    "duplicate",
    "false_positive",
    "low_value",
    "out_of_scope",
    "other",
]


class SourceCandidateProposedPayload(EntryPayload):
    """L1 axis emits this when a strategy proposes a candidate data
    source for admin triage.

    Emitted by the lake-side L1 Compounding axis (Sub-wave B). One
    emission per strategy hit; the composite service merges + dedups
    across strategies before writing.

    ``candidate_id`` is a deterministic hash minted by
    ``make_candidate_id(proposed_kind, proposed_identifier, strategy)``
    so the same strategy proposing the same source twice folds onto
    the same projection row (replay-stable dedup). Different
    strategies proposing the same source get distinct candidate_ids
    so each strategy's case to the admin surfaces independently.

    ``proposed_kind`` carries a **connector-registry kind string**
    (e.g. ``"csv_local"``, ``"postgres"``, ``"stripe"``,
    ``"mcp:notion"``). This is **NOT** a ``Literal[...]`` —
    connector-registry kinds are configuration (Addendum 4 §B), not
    KIND_REGISTRY entries, so the ledger schema must not couple to
    connector add/remove cadence. Validation happens at runtime
    against ``wormbase_lake_surfaces.registry.default_registry()`` —
    unknown kinds raise a ValidationError. Strategies should consult
    ``default_registry().all_kinds()`` before proposing.

    ``proposed_identifier`` is the free-form identifier carrying
    enough hint for the admin to recognise the source (e.g.
    database name, file path hint, OAuth account hint, vendor URL).

    ``domain_id_hint`` is the inferred WormBase domain for the
    candidate when upstream signal supports it (e.g. KPI-gap strategy
    threads the gap's owning domain through). NULL when the strategy
    has no domain signal.

    ``confidence`` is a float in [0.0, 1.0]; out-of-range raises at
    validation time. ``reasoning`` is human-readable prose;
    ``evidence`` is a structured dict (strategy-specific — KPI gap
    carries ``{"kpi_node_id": ...}``; channel-mention carries
    ``{"message_refs": [...]}``; complementarity carries
    ``{"portfolio_snapshot": [...]}``) preserved verbatim through
    the fold and surfaced on the candidate-detail panel.

    ``strategy`` is one of {``"kpi_gap"``, ``"channel_mention"``,
    ``"complementarity"``} per spec §4.3. Open string field with a
    non-empty guard so future strategy plug-ins can ship without
    ledger churn (the doctrine doc lists the canonical three).
    """

    kind: ClassVar[str] = "source_candidate_proposed"
    candidate_id: str
    proposed_kind: str
    proposed_identifier: str
    domain_id_hint: str | None = None
    strategy: str
    reasoning: str
    confidence: float
    evidence: dict

    @field_validator("candidate_id")
    @classmethod
    def _candidate_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("candidate_id must be non-empty")
        return v

    @field_validator("proposed_kind")
    @classmethod
    def _proposed_kind_against_registry(cls, v: str) -> str:
        """Runtime-validate the connector kind against the default registry.

        Per spec §4.2: a ``Literal[...]`` would couple ledger schema
        evolution to connector add/remove cadence; connectors are
        additive-only and grow independently. Instead, the kind
        string is checked against the live
        ``wormbase_lake_surfaces.registry.default_registry()`` at write
        time. Unknown kinds raise a ValidationError. Import-local so
        the entries module stays connector-import-cheap (the registry
        import resolves quickly once the connectors package has been
        imported at boot).

        Empty string is also rejected — every candidate must declare
        a connector kind for the admin surface to render an action
        button.
        """
        if not v:
            raise ValueError("proposed_kind must be non-empty")
        # Import-local to avoid a hard dependency cycle between
        # ledger and connectors during module-load. The registry is
        # populated by the connectors package at boot; if it has not
        # been imported yet (e.g. unit tests of payload validators
        # that don't transitively import connectors), we accept the
        # value with the non-empty guard above and let the fold
        # surface the ValidationError at higher layers if the kind
        # is genuinely unknown.
        try:
            from wormbase_lake_surfaces.registry import default_registry
        except ImportError:
            return v
        registry = default_registry()
        if len(registry) == 0:
            # Registry not yet populated (tests that import only
            # ledger primitives). Skip the runtime guard; the
            # non-empty check above is still in force.
            return v
        if v not in registry:
            known = ", ".join(registry.all_kinds()[:10])
            raise ValueError(
                f"proposed_kind={v!r} not in connector registry; "
                f"known kinds (first 10): {known}"
            )
        return v

    @field_validator("proposed_identifier")
    @classmethod
    def _proposed_identifier_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("proposed_identifier must be non-empty")
        return v

    @field_validator("strategy")
    @classmethod
    def _strategy_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("strategy must be non-empty")
        return v

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_range(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0]; got {v}"
            )
        return v


class SourceCandidatePromotedPayload(EntryPayload):
    """Operator approves a previously-proposed source candidate for
    promotion into the existing source-pipeline.

    Emitted by the admin UI (Sub-wave C endpoint) when a maintainer
    accepts a triaged candidate. The ``candidate_id`` MUST match a
    prior ``source_candidate_proposed`` entry's ``candidate_id`` for
    the same company. Forward-only: re-promotion after a rejection
    emits a NEW entry; the prior entries are never mutated.

    The Sub-wave C promote endpoint dual-writes — emits this entry
    AND triggers the existing ``source_builder`` to emit a downstream
    ``source_proposed`` entry. ``downstream_source_proposed_id`` is
    threaded with the entry-id of that downstream emission when known
    at write time so the dashboard's /lake/source-candidates surface
    can render a "view connected source →" link to the in-flight
    connection.

    ``promoted_by_person_id`` carries the WormBase-internal Person
    UUID of the approving operator, threaded by the admin surface.
    ``notes`` is an optional free-text annotation surfaced on the
    /trace view and the candidate-detail row.
    """

    kind: ClassVar[str] = "source_candidate_promoted"
    candidate_id: str
    promoted_by_person_id: str
    downstream_source_proposed_id: str | None = None
    notes: str | None = None

    @field_validator("candidate_id")
    @classmethod
    def _candidate_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("candidate_id must be non-empty")
        return v


class SourceCandidateRejectedPayload(EntryPayload):
    """Operator rejects a previously-proposed source candidate with a
    categorical reason.

    Emitted by the admin UI (Sub-wave C endpoint) when a maintainer
    rejects a triaged candidate. The ``candidate_id`` MUST match a
    prior ``source_candidate_proposed`` entry's ``candidate_id`` for
    the same company. Forward-only: re-rejection after re-promotion
    emits a NEW entry; the prior entries are never mutated.

    ``reason`` is a strict 5-value enum providing categorical signal
    that downstream strategies can use as negative-signal training
    (Sub-wave B+). The L1-specific 5th value is ``duplicate``
    (distinct from L8's ``wrong_pairing``, L6's ``wrong_level``,
    L5's ``wrong_type``, L4's ``already_handled`` and L7's
    ``wrong_threshold``) — reflects that the most common reject
    reason at triage is "we already have this source / something
    equivalent."

    ``rejected_by_person_id`` carries the WormBase-internal Person
    UUID of the rejecting operator. ``notes`` is an optional
    free-text annotation.
    """

    kind: ClassVar[str] = "source_candidate_rejected"
    candidate_id: str
    rejected_by_person_id: str
    reason: SourceCandidateRejectReason
    notes: str | None = None

    @field_validator("candidate_id")
    @classmethod
    def _candidate_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("candidate_id must be non-empty")
        return v


# ---------------------------------------------------------------------------
# L2 Sub-wave A — lake-side catalog-drift detection loop (2026-06-09).
#
# Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=132.
# At 132, exactly 18 headroom under the Wave F Addendum 4 ceiling at 150.
# L-axis family count = 24 of 30 cap (L3=3 + L7=3 + L4=3 + L5=3 + L6=3 +
# L8=3 + L1=3 + L2=3) — 6 headroom; **L2 is the FINAL planned axis in this
# generation per spec §11** (any future L9+ requires a doctrine review per
# Addendum 4 §E before design begins).
#
# These three kinds back the projection_catalog_drifts fold (v028).
# L2 is the 8th lake-side compounding loop. L2 introduces ZERO new
# cross-axis Protocol chains today — its inference reads first-class
# catalog-mirror substrate (``external_catalog_imported`` snapshots)
# via a lightweight ``CatalogSnapshotReader`` Protocol added in
# Sub-wave B; cross-axis chain count stays at 3. (Foreshadowed Phase-2
# L4↦L2-acknowledged-drift severity-elevation chain is NOT in Wave 1
# scope.)
#
# Naming-collision check (spec §3, §7): the existing
# ``external_catalog_imported`` / ``external_catalog_drift_detected``
# kinds are the catalog-mirror substrate (raw structural-change
# records); L2 introduces a separate ``catalog_drift_*`` namespace
# (no ``external_`` prefix) carrying inference-bearing fields
# (``strategy``, ``confidence``, ``reasoning``, ``evidence``) —
# analogous to how L1's ``source_candidate_*`` namespace is the triage
# prequel to the lifecycle ``source_proposed/confirmed/connected/
# profiled`` namespace. No rename, no payload schema change on the
# established catalog-mirror kinds. The ``catalog_drift_*`` namespace
# is unused elsewhere in ``entries.py``.
#
# * ``catalog_drift_proposed`` — written by the L2 Compounding axis
#   when a strategy (``table_set`` / ``column_set`` / ``column_type``)
#   detects a structural change in an external catalog snapshot.
#   Carries strict ``Literal[...]`` ``drift_kind`` (5 cases: table_
#   added/table_removed/column_added/column_removed/column_type_
#   changed); ``column`` is nullable (NULL for ``table_*`` drifts,
#   required for ``column_*`` drifts — validator enforces consistency);
#   ``before``/``after`` carry strategy-specific structured snapshots
#   of the changed attribute (NULL for ``*_added`` / ``*_removed``
#   respectively; both required for ``column_type_changed``).
# * ``catalog_drift_acknowledged`` — written by the admin UI when an
#   operator signs off on a drift as known/expected (no downstream
#   pipeline trigger; no cross-axis effect). L2 uses "acknowledged"
#   where L3/L7/L4/L5/L6/L8 use "confirmed" and L1 uses "promoted"
#   per spec §1 because L2's affirmative state is a no-op record —
#   admin acknowledges the drift is known/expected, but nothing else
#   happens automatically. The drift was already observed by the
#   catalog-mirror's W5a Reactivity; L2's job is to record the
#   human-in-the-loop disposition.
# * ``catalog_drift_rejected`` — written by the admin UI when an
#   operator rejects the drift with a categorical reason. The L2-
#   specific 5th reason value is ``expected_change`` (replaces L1's
#   ``duplicate``, L8's ``wrong_pairing``, L6's ``wrong_level``, L5's
#   ``wrong_type``, L4's ``already_handled`` and L7's
#   ``wrong_threshold``) — reflects that the drift was real but a
#   known intentional change (e.g. planned schema migration).
#
# Structurally identical to the L3 / L7 / L4 / L5 / L6 / L8 / L1
# triples — same proposed / affirmative / rejected shape, same
# forward-only semantics, same composite PK fold
# (``(company_id, drift_id)``). Full design spec at
# ``docs/superpowers/specs/2026-06-09-lake-side-compounding-l2-design.md``.
# ---------------------------------------------------------------------------


def make_drift_id(
    *,
    source_id: str,
    table_id: str,
    column: str | None,
    drift_kind: str,
    before: dict | None = None,
    after: dict | None = None,
) -> str:
    """Mint a deterministic ``drift_id`` for L2 catalog-drift dedup.

    Returns the first 32 hex chars of a stable-JSON-encoded sha256
    over the identifying tuple. The composite PK ``(company_id,
    drift_id)`` on ``projection_catalog_drifts`` keys off this value,
    so the same drift detected twice → same drift_id → natural dedup
    at the PK; different drifts (different before/after snapshots
    for the same column-type-change, say) get distinct rows.

    Stable JSON encoding (``sort_keys=True``) keeps the hash stable
    regardless of dict iteration order on ``before``/``after``. Hex-
    only output keeps it safe to embed in URL paths and SQL
    identifiers without escaping. Mirrors L8's ``make_stitch_id`` and
    L1's ``make_candidate_id`` shape: deterministic, opaque, 32-char
    prefix.
    """
    import json

    canonical = json.dumps(
        {
            "source_id": source_id,
            "table_id": table_id,
            "column": column,
            "drift_kind": drift_kind,
            "before": before,
            "after": after,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


# Alias for the 5-value L2-specific drift_kind enum. Strict Literal
# (unlike L1's free-form ``proposed_kind``) — the 5 cases enumerate
# observable catalog-metadata change classes; new cases require a
# doctrine review + Pydantic schema bump.
CatalogDriftKind = Literal[
    "table_added",
    "table_removed",
    "column_added",
    "column_removed",
    "column_type_changed",
]


# Alias for the 5-value L2-specific reject-reason enum.
# ``expected_change`` is the L2-specific 5th value (distinct from
# L1's ``duplicate``, L8's ``wrong_pairing``, L6's ``wrong_level``,
# L5's ``wrong_type``, L4's ``already_handled`` and L7's
# ``wrong_threshold``) — reflects that the drift was real but a
# known intentional change. Spec §3.5 / prompt §1.
CatalogDriftRejectReason = Literal[
    "false_positive",
    "inconsequential",
    "expected_change",
    "out_of_scope",
    "other",
]


class CatalogDriftProposedPayload(EntryPayload):
    """L2 axis emits this when a strategy detects a catalog-drift
    event in an external-catalog snapshot for admin triage.

    Emitted by the lake-side L2 Compounding axis (Sub-wave B). One
    emission per strategy hit; the composite service merges + dedups
    across strategies before writing.

    ``drift_id`` is a deterministic hash minted by
    ``make_drift_id(source_id, table_id, column, drift_kind, before,
    after)`` so the same drift detected twice (same strategy on the
    same snapshot pair) folds onto the same projection row (replay-
    stable dedup).

    ``drift_kind`` is a strict 5-value ``Literal[...]`` enumerating
    the observable catalog-metadata change classes:

    * ``table_added`` — table appears in the current snapshot but not
      the baseline. ``column`` is NULL; ``before`` is NULL; ``after``
      carries the new table descriptor.
    * ``table_removed`` — table disappears between snapshots.
      ``column`` is NULL; ``after`` is NULL; ``before`` carries the
      prior table descriptor.
    * ``column_added`` — column appears in the current snapshot but
      not the baseline. ``column`` REQUIRED; ``before`` is NULL;
      ``after`` carries the new column descriptor.
    * ``column_removed`` — column disappears between snapshots.
      ``column`` REQUIRED; ``after`` is NULL; ``before`` carries the
      prior column descriptor.
    * ``column_type_changed`` — same column name, different type.
      ``column`` REQUIRED; both ``before`` AND ``after`` carry the
      type descriptors (typically ``{"type": "..."}``).

    ``confidence`` is a float in [0.0, 1.0]; out-of-range raises at
    validation time. ``reasoning`` is human-readable prose;
    ``evidence`` is a structured dict (strategy-specific — table_set
    carries ``{"before_tables": [...], "after_tables": [...]}``;
    column_set carries ``{"before_columns": [...], "after_columns":
    [...]}``; column_type carries ``{"before_type": "...",
    "after_type": "..."}``) preserved verbatim through the fold and
    surfaced on the drift-detail panel.

    ``strategy`` is one of {``"table_set"``, ``"column_set"``,
    ``"column_type"``} per spec §4. Open string field with a non-
    empty guard so future strategy plug-ins can ship without ledger
    churn (the doctrine doc lists the canonical three).
    """

    kind: ClassVar[str] = "catalog_drift_proposed"
    drift_id: str
    source_id: str
    table_id: str
    column: str | None = None
    drift_kind: CatalogDriftKind
    before: dict | None = None
    after: dict | None = None
    strategy: str
    reasoning: str
    confidence: float
    evidence: dict

    @field_validator("drift_id")
    @classmethod
    def _drift_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("drift_id must be non-empty")
        return v

    @field_validator("source_id")
    @classmethod
    def _source_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("source_id must be non-empty")
        return v

    @field_validator("table_id")
    @classmethod
    def _table_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("table_id must be non-empty")
        return v

    @field_validator("strategy")
    @classmethod
    def _strategy_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("strategy must be non-empty")
        return v

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_range(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0]; got {v}"
            )
        return v

    @field_validator("column")
    @classmethod
    def _column_non_empty_when_set(cls, v: str | None) -> str | None:
        """``column`` may be None for table-level drifts; if set, it
        must be a non-empty string (no whitespace-only column names)."""
        if v is not None and not v:
            raise ValueError("column, when set, must be non-empty")
        return v

    def model_post_init(self, __context: Any) -> None:
        """Enforce the drift_kind ⇄ column / before / after coherence
        invariants spelled out per drift_kind on the docstring.

        These cross-field invariants live in ``model_post_init`` (not
        a per-field validator) so every field has been parsed before
        the relationship is checked. Per the spec, the projection
        layer also enforces nullability + the drift_kind CHECK at the
        DB schema; the payload-side guard catches the same errors at
        write-time so an invalid emission never lands on the wire.
        """
        # column rules — REQUIRED for column_*, FORBIDDEN for table_*.
        if self.drift_kind in ("column_added", "column_removed", "column_type_changed"):
            if self.column is None:
                raise ValueError(
                    f"column is required when drift_kind={self.drift_kind!r}"
                )
        elif self.drift_kind in ("table_added", "table_removed"):
            if self.column is not None:
                raise ValueError(
                    f"column must be None when drift_kind={self.drift_kind!r}"
                )
        # before rules — FORBIDDEN for *_added (no prior value).
        if self.drift_kind in ("table_added", "column_added"):
            if self.before is not None:
                raise ValueError(
                    f"before must be None when drift_kind={self.drift_kind!r}"
                )
        # after rules — FORBIDDEN for *_removed (no current value).
        if self.drift_kind in ("table_removed", "column_removed"):
            if self.after is not None:
                raise ValueError(
                    f"after must be None when drift_kind={self.drift_kind!r}"
                )
        # column_type_changed — both before AND after REQUIRED.
        if self.drift_kind == "column_type_changed":
            if self.before is None or self.after is None:
                raise ValueError(
                    "before and after are both required when "
                    "drift_kind='column_type_changed'"
                )


class CatalogDriftAcknowledgedPayload(EntryPayload):
    """Operator acknowledges a previously-proposed catalog drift as
    known/expected.

    Emitted by the admin UI (Sub-wave C endpoint) when a maintainer
    signs off on a drift. The ``drift_id`` MUST match a prior
    ``catalog_drift_proposed`` entry's ``drift_id`` for the same
    company. Forward-only: re-acknowledgment after a rejection emits
    a NEW entry; the prior entries are never mutated.

    Unlike L1's promote (which triggers a downstream source-pipeline
    write) and L3-L8's confirm (which feeds peer-axis chains),
    acknowledgment is a no-op record — no downstream pipeline
    trigger, no cross-axis effect. The catalog-mirror's W5a
    Reactivity already observed the drift via
    ``external_catalog_drift_detected``; L2's job is just to record
    the human-in-the-loop disposition.

    ``acknowledged_by_person_id`` carries the WormBase-internal
    Person UUID of the acknowledging operator, threaded by the admin
    surface. ``notes`` is an optional free-text annotation surfaced
    on the /trace view and the drift-detail row.
    """

    kind: ClassVar[str] = "catalog_drift_acknowledged"
    drift_id: str
    acknowledged_by_person_id: str
    notes: str | None = None

    @field_validator("drift_id")
    @classmethod
    def _drift_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("drift_id must be non-empty")
        return v


class CatalogDriftRejectedPayload(EntryPayload):
    """Operator rejects a previously-proposed catalog drift with a
    categorical reason.

    Emitted by the admin UI (Sub-wave C endpoint) when a maintainer
    rejects a drift. The ``drift_id`` MUST match a prior
    ``catalog_drift_proposed`` entry's ``drift_id`` for the same
    company. Forward-only: re-rejection after re-acknowledgment
    emits a NEW entry; the prior entries are never mutated.

    ``reason`` is a strict 5-value enum providing categorical signal
    that downstream strategies can use as negative-signal training
    (Sub-wave B+). The L2-specific 5th value is ``expected_change``
    (distinct from L1's ``duplicate``, L8's ``wrong_pairing``, L6's
    ``wrong_level``, L5's ``wrong_type``, L4's ``already_handled``
    and L7's ``wrong_threshold``) — reflects that the drift was real
    but a known intentional change (e.g. planned schema migration).

    ``rejected_by_person_id`` carries the WormBase-internal Person
    UUID of the rejecting operator. ``notes`` is an optional
    free-text annotation.
    """

    kind: ClassVar[str] = "catalog_drift_rejected"
    drift_id: str
    rejected_by_person_id: str
    reason: CatalogDriftRejectReason
    notes: str | None = None

    @field_validator("drift_id")
    @classmethod
    def _drift_id_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("drift_id must be non-empty")
        return v


__all__ = [
    "ALL_KINDS",
    "KIND_REGISTRY",
    "QUADRANT_VALUES",
    "AddedViaFlow",
    "AgentEventDeliveredPayload",
    "AgentGrantPayload",
    "AgentMetadataUpdatedPayload",
    "AgentQueryPayload",
    "AgentRegisteredPayload",
    "AgentSubscriptionCreatedPayload",
    "AgentSubscriptionRevokedPayload",
    "BadPatternProposedPayload",
    "CatalogColumnSpec",
    "CatalogDriftAcknowledgedPayload",
    "CatalogDriftKind",
    "CatalogDriftProposedPayload",
    "CatalogDriftRejectReason",
    "CatalogDriftRejectedPayload",
    "CatalogTableImportedPayload",
    "ChatReceivedPayload",
    "ChatReplyExecutedPayload",
    "ChatReplyProposedPayload",
    "ChatReplyResolvedPayload",
    "ChatReplyVerifiedPayload",
    "ChatSentPayload",
    "Classification",
    "ClassificationLevel",
    "ClockTickPayload",
    "ColumnClassificationConfirmedPayload",
    "ColumnClassificationProposedPayload",
    "ColumnClassificationRejectedPayload",
    "ConceptConfirmedPayload",
    "ConceptProposedPayload",
    "ConversationSyncPayload",
    "CredentialPayload",
    "DataProductArchivedPayload",
    "DataProductConsumedPayload",
    "DataProductGeneratedPayload",
    "DataProductKind",
    "DataProductProposedPayload",
    "DataProductRecommendedPayload",
    "DataProductSurface",
    "DecisionRecordedPayload",
    "DomainRole",
    "EntityKind",
    "EntityStitchConfirmedPayload",
    "EntityStitchProposedPayload",
    "EntityStitchRejectedPayload",
    "DomainRoleAssignedPayload",
    "EntryPayload",
    "ExecutePayload",
    "ExperimentLessonPayload",
    "ExperimentOutcome",
    "ExperimentProposedPayload",
    "ExperimentResolvedPayload",
    "ExperimentRunPayload",
    "ExternalCatalogDriftDetectedPayload",
    "ExternalCatalogImportedPayload",
    "ExternalLineageImportedPayload",
    "ExternalMetricImportedPayload",
    "ExternalPolicyImportedPayload",
    "GateFiredPayload",
    "HeuristicExperimentPayload",
    "IdentityLinkedPayload",
    "IdentityUnlinkedPayload",
    "InferenceCacheRefreshedPayload",
    "InferenceServedPayload",
    "IngestLandedPayload",
    "IngestProfiledPayload",
    "InstallCompletedPayload",
    "InstallRevokedPayload",
    "KpiAnsweredPayload",
    "KpiProposedPayload",
    "LakeDiscoveryPayload",
    "LedgerEntry",
    "LessonScope",
    "KeepRateScope",
    "LineageEdgeConfirmedPayload",
    "LineageEdgeProposedPayload",
    "LineageEdgeRejectedPayload",
    "MCPCallReceivedPayload",
    "MCPOutcome",
    "MemoryWrittenPayload",
    "MetricObservedPayload",
    "MetricsKeepRatePublishedPayload",
    "NotebookArchivedPayload",
    "NotebookKernel",
    "NotebookProposedPayload",
    "NotebookPublishedPayload",
    "NotebookRunPayload",
    "NotebookRunStatus",
    "PersonArchivedPayload",
    "PersonConfirmedPayload",
    "PersonProposedPayload",
    "PersonRegisteredPayload",
    "PersonRole",
    "PhenomenonGapDetectedPayload",
    "PhenomenonGapKind",
    "PolicyAppliedPayload",
    "PositionAssignedPayload",
    "PositionConfirmedPayload",
    "PositionMetricAddedPayload",
    "PositionProposedPayload",
    "PositionQuestionPatternPayload",
    "PositionRejectedPayload",
    "ProcessMapProposedPayload",
    "ProposePayload",
    "Quadrant",
    "QualityCheckConfirmedPayload",
    "QualityCheckProposedPayload",
    "QualityCheckRejectedPayload",
    "QueryCorrectionSuggestedPayload",
    "QueryOutcomeRecordedPayload",
    "QueryTemplatePromotedPayload",
    "ReactivityConfirmedPayload",
    "ReactivityDisabledPayload",
    "ReactivityFiredPayload",
    "ReactivityProposedPayload",
    "ReactivityScopeLiteral",
    "RecurringQuestionPayload",
    "ResolvePayload",
    "ResourceConversationOutcome",
    "ResourceConversationProposedPayload",
    "ResourceConversationRepliedPayload",
    "ResourceConversationResolvedPayload",
    "ResourceRole",
    "ResourceRoleAssignedPayload",
    "ResourceRoleProposedPayload",
    "ResourceType",
    "RoleAssignedPayload",
    "RoleRevokedPayload",
    "SchemaImpactConfirmedPayload",
    "SchemaImpactProposedPayload",
    "SchemaImpactRejectedPayload",
    "SemanticGapEscalatedPayload",
    "SemanticGapProposedPayload",
    "SemanticTypeConfirmedPayload",
    "SemanticTypeProposedPayload",
    "SemanticTypeRejectedPayload",
    "SetupCompletedPayload",
    "SetupMode",
    "SetupModeChosenPayload",
    "SetupStepAdvancedPayload",
    "SourceBronzedPayload",
    "SourceCandidateProposedPayload",
    "SourceCandidatePromotedPayload",
    "SourceCandidateRejectedPayload",
    "SourceCandidateRejectReason",
    "SourceConfirmedPayload",
    "SourceConnectedPayload",
    "SourceGoldedPayload",
    "SourceProfiledPayload",
    "SourceProposedPayload",
    "SourceSilveredPayload",
    "make_candidate_id",
    "make_drift_id",
    "SignupSource",
    "SpeechAct",
    "SystemMapNodePayload",
    "TenancyRole",
    "TenantEngineRegisteredPayload",
    "TenantQuotaConsumedPayload",
    "TenantSignupCompletedPayload",
    "TenantSignupInitiatedPayload",
    "TopicProposedPayload",
    "VerifyPayload",
]
