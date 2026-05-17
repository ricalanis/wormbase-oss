"""Service composition: build a fully wired worm-core process.

Used by the docker-compose worm-core service and by the integration
tests. The same composition runs in production tenancy and in local
iteration — no demo-only branches.

Also hosts ``chat_received_reactivity_poller`` — the Path 3 replacement
for the lurker SocketMode listener. Instead of opening a second Slack
connection, worm-core now polls Postgres for new ``execute`` ledger
entries whose payload tool is ``emit_chat_received`` (lurker path) or
``channel_adapter.emit_chat_received`` (channel-adapter log-tail path)
and forwards each into the reactivity pipeline. This keeps the
"every inbound goes through the triad" invariant while letting the
channel-adapter own the actual Slack capture.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import text as _sql_text

from wormbase_core.classifier import (
    OllamaCloudClassifier,
    SemanticClassifier,
    StubClassifier,
)
from wormbase_core.conversation import ConversationContract
from wormbase_core.flows import (
    CredentialInDmFlow,
    DashboardFormFlow,
    DropAndProfileFlow,
    KpiGapTriggeredFlow,
    MentionedInConversationFlow,
)
from wormbase_core.lurker import SlackLurker
from wormbase_core.ramp import KnowledgeRamp
from wormbase_core.reactivity import (
    DefaultInfrastructureTrigger,
    DefaultSemanticTrigger,
    ReactivityPipeline,
)
from wormbase_core.relevance import RulesBasedRelevanceGate
from wormbase_core.source_builder import SourceBuilder
from wormbase_governance import (
    CompanyWarmup,
    InterjectionGate,
    KnowledgeGate,
    PIIGate,
    WarmupGate,
)
from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ontology_seed import Loader

logger = logging.getLogger("wormbase_core.service")


# Stable namespace so a string tenant_id maps to the same UUID per run.
# Aligned with apps/channel-adapter/src/wormbase_channel_adapter/tenant.py
# so both services derive the same company_id for the same tenant slug —
# required for the Path 3 architecture where worm-core polls Postgres
# for chat_received entries written by channel-adapter.
TENANT_NAMESPACE = UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f")


def tenant_to_uuid(tenant_id: str) -> UUID:
    # Match channel-adapter's normalization (strip + lower) so the two
    # services derive identical company_ids for the same tenant slug.
    return uuid5(TENANT_NAMESPACE, tenant_id.strip().lower())


@dataclass
class WormCore:
    """Fully wired worm-core ready to receive events."""

    ledger: Ledger | InMemoryLedger
    company_id: UUID
    domain_pack: str
    seed_loader: Loader
    classifier: SemanticClassifier
    pii_gate: PIIGate
    interjection_gate: InterjectionGate
    knowledge_gate: KnowledgeGate
    warmup_gate: WarmupGate
    source_builder: SourceBuilder
    drop_and_profile: DropAndProfileFlow
    credential_in_dm: CredentialInDmFlow
    mentioned_in_conversation: MentionedInConversationFlow
    dashboard_form: DashboardFormFlow
    kpi_gap_triggered: KpiGapTriggeredFlow
    relevance_gate: RulesBasedRelevanceGate
    conversation: ConversationContract
    pipeline: ReactivityPipeline
    ramp: KnowledgeRamp
    lurker: SlackLurker | None = None


async def build_worm_core(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    *,
    domain_pack: str = "saas",
    enable_lurker: bool = False,
    enable_cloud_classifier: bool = True,
    seed_loader: Loader | None = None,
) -> WormCore:
    seed_loader = seed_loader or Loader()
    # 1) warmup the company (idempotent)
    warmup = CompanyWarmup(ledger, seed_loader)
    await warmup.warmup(company_id, domain_pack)

    # 2) classifier
    stub = StubClassifier(seed_loader, domain_pack)
    cloud = (
        OllamaCloudClassifier(seed_loader, domain_pack)
        if enable_cloud_classifier and os.environ.get("OLLAMA_API_KEY")
        else None
    )
    classifier = SemanticClassifier(
        seed_loader, domain_pack, cloud=cloud, stub=stub,
    )

    # 3) gates
    pii_gate = PIIGate(ledger, company_id, seed_loader)
    interjection_gate = InterjectionGate(ledger, company_id)
    knowledge_gate = KnowledgeGate(
        [c.id for c in seed_loader.load_ontology(domain_pack)],  # type: ignore[arg-type]
        [],  # confirmed concepts populate as they're acknowledged
        ledger, company_id,
    )

    # 4) ramp + warmup gate
    ramp = KnowledgeRamp(ledger, seed_loader)

    async def _ramp_reader(cid: UUID):
        return await ramp.compute(cid, write_snapshot=False)

    warmup_gate = WarmupGate(_ramp_reader, ledger, company_id)

    # 5) source builder + 5 flows
    source_builder = SourceBuilder(ledger)
    drop_and_profile = DropAndProfileFlow(source_builder, classifier)
    credential_in_dm = CredentialInDmFlow(source_builder, pii_gate)
    mentioned_in_conversation = MentionedInConversationFlow(
        source_builder, ledger, interjection_gate,
    )
    dashboard_form = DashboardFormFlow(source_builder, pii_gate)
    kpi_gap_triggered = KpiGapTriggeredFlow(
        source_builder, ledger, interjection_gate,
    )

    # 6) reactivity pipeline + conversation contract
    infra_trigger = DefaultInfrastructureTrigger(ledger, company_id)
    semantic_trigger = DefaultSemanticTrigger(classifier, ledger, company_id)
    relevance_gate = RulesBasedRelevanceGate(
        ledger, company_id, mention_handle="@worm",
    )
    pipeline = ReactivityPipeline(
        infra_trigger, semantic_trigger, relevance_gate, ledger, company_id,
    )
    conversation = ConversationContract(
        relevance_gate, interjection_gate, ledger, company_id,
    )

    # 7) lurker (optional)
    lurker = None
    if enable_lurker:
        lurker = SlackLurker(
            ledger, company_id, pipeline,
            flow_dispatcher=make_flow_dispatcher(
                drop_and_profile, credential_in_dm, company_id,
            ),
        )

    return WormCore(
        ledger=ledger,
        company_id=company_id,
        domain_pack=domain_pack,
        seed_loader=seed_loader,
        classifier=classifier,
        pii_gate=pii_gate,
        interjection_gate=interjection_gate,
        knowledge_gate=knowledge_gate,
        warmup_gate=warmup_gate,
        source_builder=source_builder,
        drop_and_profile=drop_and_profile,
        credential_in_dm=credential_in_dm,
        mentioned_in_conversation=mentioned_in_conversation,
        dashboard_form=dashboard_form,
        kpi_gap_triggered=kpi_gap_triggered,
        relevance_gate=relevance_gate,
        conversation=conversation,
        pipeline=pipeline,
        ramp=ramp,
        lurker=lurker,
    )


_FILE_DROP_TYPES = ("file_share", "file_shared", "file_drop")


def _event_to_infra(event: dict, company_id: UUID):
    from datetime import UTC, datetime as _dt

    from wormbase_core.reactivity import InfraEvent
    ts_raw = event.get("event_ts") or event.get("ts") or 0
    if isinstance(ts_raw, _dt):
        ts_dt = ts_raw if ts_raw.tzinfo else ts_raw.replace(tzinfo=UTC)
    else:
        ts_num = float(ts_raw or 0)
        ts_dt = _dt.fromtimestamp(ts_num, tz=UTC) if ts_num else _dt.now(UTC)
    # Flows (DropAndProfileFlow.on_file_drop, etc.) read trigger-specific
    # fields off InfraEvent.payload directly (e.g. payload.get("filename")).
    # The synthesized event from the ledger-poller wraps those fields in
    # an inner `payload` dict — pass the inner dict through so flow code
    # finds them at the top level. Falls back to the whole event for the
    # legacy lurker shape, which inlined the Slack event object.
    inner_payload = event.get("payload")
    flow_payload = (
        inner_payload if isinstance(inner_payload, dict) else event
    )
    etype = event.get("type")
    if etype == "dm":
        source = "dm"
    elif etype in _FILE_DROP_TYPES:
        source = "file_drop"
    else:
        source = "channel_message"

    # Provenance fields propagate to the InfraEvent's is_live derivation
    # downstream. Caller's responsibility to thread platform_ts as a
    # datetime (or None) — we don't parse strings here.
    delivery_mode = event.get("delivery_mode") or "push"
    if delivery_mode not in ("push", "history_sync"):
        delivery_mode = "push"
    platform_ts = event.get("platform_ts")
    history_sync_id = event.get("history_sync_id")

    return InfraEvent(
        source=source,
        payload=flow_payload,
        ts=ts_dt,
        company_id=company_id,
        channel_id=event.get("channel") or event.get("channel_id"),
        person_id=event.get("user") or event.get("user_id"),
        message_id=event.get("client_msg_id") or event.get("message_id") or str(ts_raw),
        text=event.get("text", "") or "",
        delivery_mode=delivery_mode,
        platform_ts=platform_ts,
        history_sync_id=history_sync_id,
    )


def is_mentioned_in_conversation_enabled() -> bool:
    """Return True iff ``WORMBASE_MENTIONED_IN_CONVERSATION_ENABLED`` is truthy.

    Sub-wave A F3 (2026-05-30) gate for the legacy
    ``make_flow_dispatcher`` stub-predicate path. Default OFF so existing
    deploys keep the previous byte-identical behaviour. Truthy values:
    ``"1"``, ``"true"``, ``"yes"`` (case-insensitive). Anything else
    (including empty / unset) → off.

    The production chat-presence dispatcher
    (``packages/wormbase-chat-presence/src/wormbase_chat_presence/dispatcher.py``
    line 142-143) already routes ``suggested_flow ==
    "mentioned_in_conversation"`` to
    ``MentionedInConversationFlow.on_proactive_mention`` via the
    ``wire_chat_for_install`` lifecycle, driven by the relevance gate's
    ``_DATA_SOURCE_KEYWORDS`` matcher. The legacy
    ``make_flow_dispatcher`` below (used today only by ``SlackLurker``,
    Path 2) gained a parallel stub-predicate hook so the dispatcher
    coverage gap audited at ``service.py:283`` is closed in BOTH
    callers. Full semantic interpretation is a Phase 2 carry-forward;
    the stub matches a literal ``data:`` prefix in the event text.
    """
    return os.environ.get(
        "WORMBASE_MENTIONED_IN_CONVERSATION_ENABLED", "0",
    ).strip().lower() in ("1", "true", "yes")


def kpi_gap_default_channel_id() -> str | None:
    """Return the default channel id for kpi_gap_triggered_poller, if set.

    Onboarding Sub-wave C (2026-05-30) — Sub-wave A handoff #4. Lets
    operators thread the worm's owner-channel target through env so
    a freshly-installed worm can route gap escalations into a
    pre-known channel without waiting for the per-domain
    channel-resolution loop to confirm.

    Read from ``WORMBASE_KPI_GAP_DEFAULT_CHANNEL`` (env). Returns
    ``None`` when unset / empty, in which case the poller falls back
    to the previous per-domain mapping path.

    The value is opaque to this function — it is passed through to
    ``KpiGapTriggeredFlow.propose_for_gap`` as ``default_channel_id``
    which then handles platform-specific resolution (Slack channel ID,
    Discord channel ID, etc.). Operators set this to the platform's
    native channel id (e.g. ``"C01ABC"`` for Slack).
    """
    raw = os.environ.get("WORMBASE_KPI_GAP_DEFAULT_CHANNEL", "").strip()
    return raw or None


def _stub_mention_data_prefix(event: dict) -> bool:
    """Stub semantic-interpretation predicate.

    Returns True iff the event's text starts with the literal ``data:``
    prefix (case-insensitive, leading whitespace tolerated). Documented
    contract for tests + ops: enabling
    ``WORMBASE_MENTIONED_IN_CONVERSATION_ENABLED=true`` and sending
    ``"data: stripe sales pipeline"`` in a watched channel will route
    through ``MentionedInConversationFlow.on_proactive_mention``.

    Phase 2 carry-forward: replace this predicate with a real
    ``SemanticClassifier`` invocation reading
    ``DefaultSemanticTrigger`` output. The stub-predicate gate stays so
    operators can A/B the two predicates without code changes.
    """
    text = (event.get("text") or "").lstrip().lower()
    return text.startswith("data:")


def make_flow_dispatcher(
    drop_and_profile: DropAndProfileFlow,
    credential_in_dm: CredentialInDmFlow,
    company_id: UUID,
    *,
    mentioned_in_conversation: Any | None = None,
):
    """Build a flow_dispatcher that routes pipeline decisions to flows.

    Used by both the (legacy) lurker and the Path 3 ledger-poller. The
    decision's ``suggested_flow`` plus the event's ``type`` together
    determine which source-building flow runs. Recognized type values
    span the lurker convention (``file_share`` / ``file_shared``) and
    the poller-synthesized ``file_drop`` so this function works in both
    code paths without the caller having to normalize.

    Sub-wave A F3 (2026-05-30) adds an optional
    ``mentioned_in_conversation`` flow kwarg. When the kwarg is
    supplied AND ``WORMBASE_MENTIONED_IN_CONVERSATION_ENABLED=true``
    AND the event matches ``_stub_mention_data_prefix``, the dispatcher
    routes the event through
    ``MentionedInConversationFlow.on_proactive_mention``. Default off
    so byte-identical behaviour is preserved for callers that do not
    pass the kwarg.

    The newer ``make_flow_dispatcher_with_proactivity`` (below) is the
    canonical chat-driven path; this legacy dispatcher exists only for
    the SlackLurker (Path 2). Both paths now reach the
    mentioned_in_conversation flow when its preconditions are met.
    """
    async def _dispatch(event: dict, decision: Any) -> None:
        sf = getattr(decision, "suggested_flow", None)
        if sf == "drop_and_profile" and event.get("type") in _FILE_DROP_TYPES:
            await drop_and_profile.on_file_drop(
                _event_to_infra(event, company_id)
            )
        elif sf == "credential_offered_in_dm":
            await credential_in_dm.on_dm(
                _event_to_infra(event, company_id)
            )
        # F3 (Sub-wave A): stub-predicate path for mentioned_in_conversation.
        # Production path runs through chat_bundle.dispatcher
        # (packages/wormbase-chat-presence). This branch lights when the
        # legacy SlackLurker path is wired AND the operator opted in.
        elif (
            sf == "mentioned_in_conversation"
            and mentioned_in_conversation is not None
            and is_mentioned_in_conversation_enabled()
            and _stub_mention_data_prefix(event)
        ):
            try:
                await mentioned_in_conversation.on_proactive_mention(
                    _event_to_infra(event, company_id)
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "make_flow_dispatcher: mentioned_in_conversation "
                    "stub-predicate dispatch failed: %s", exc,
                )

    return _dispatch


async def chat_received_reactivity_poller(
    ledger: Ledger,
    pipeline: ReactivityPipeline,
    company_id: UUID,
    *,
    poll_interval_s: float = 1.5,
    initial_seq: int | None = None,
    flow_dispatcher: Any = None,
) -> None:
    """Forward new chat_received / file_received ledger entries to the pipeline.

    Polls Postgres for ``execute`` rows whose payload ``tool`` is one of
    ``emit_chat_received`` (lurker-emitted),
    ``channel_adapter.emit_chat_received`` (channel-adapter log-tail
    path), or ``channel_adapter.emit_file_received`` (file-drop fan-out
    from the same path). Each row is synthesized into a
    reactivity-pipeline raw event and replayed through
    ``pipeline.process``. File-drop entries additionally fan out to a
    flow dispatcher (when supplied) so ``DropAndProfileFlow`` runs and
    ``emit_source_proposed`` lands in the ledger.

    The flow_dispatcher signature is::

        async def flow_dispatcher(
            event: dict, decision: RelevanceDecision | None
        ) -> None: ...

    where ``event`` is the synthesized raw event (same dict that was
    passed to ``pipeline.process``). Mirrors the lurker's dispatcher
    interface so callers can reuse routing logic.

    ``initial_seq`` defaults to the current ``max(seq)`` of the ledger
    so we don't replay history on cold start. Tests can pass a smaller
    value (or 0) to drain pre-existing rows.

    The loop catches every per-row exception so a single bad payload
    never wedges the poller; only ``CancelledError`` propagates.
    """
    if initial_seq is None:
        async with ledger.engine.begin() as conn:
            result = await conn.execute(
                _sql_text(
                    "SELECT COALESCE(MAX(seq), 0) FROM ledger WHERE company_id = :cid"
                ),
                {"cid": company_id},
            )
            initial_seq = int(result.scalar() or 0)

    last_seq = initial_seq
    logger.info(
        "chat_received poller starting: company_id=%s last_seq=%d interval=%.2fs",
        company_id, last_seq, poll_interval_s,
    )

    select_sql = _sql_text(
        """
        SELECT seq, payload
          FROM ledger
         WHERE company_id = :cid
           AND kind = 'execute'
           AND payload->>'tool' IN (
                 'emit_chat_received',
                 'channel_adapter.emit_chat_received',
                 'channel_adapter.emit_file_received'
               )
           AND seq > :last_seq
         ORDER BY seq ASC
        """
    )

    max_seq_sql = _sql_text(
        "SELECT COALESCE(MAX(seq), 0) FROM ledger WHERE company_id = :cid"
    )

    while True:
        try:
            async with ledger.engine.begin() as conn:
                # Tenant-reset detection: if the current MAX(seq) for this
                # company is BELOW our last_seq, the ledger was wiped (e.g.
                # `wormbase demo seed --reset-first`). Rewind so the new
                # post-reset entries are visible.
                cur_max = int(
                    (await conn.execute(max_seq_sql, {"cid": company_id})).scalar()
                    or 0
                )
                if cur_max < last_seq:
                    logger.info(
                        "chat_received poller: tenant reset detected "
                        "(max_seq=%d < last_seq=%d); rewinding to 0",
                        cur_max, last_seq,
                    )
                    last_seq = 0
                result = await conn.execute(
                    select_sql, {"cid": company_id, "last_seq": last_seq}
                )
                rows = result.mappings().all()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("chat_received poller select failed: %s", exc)
            rows = []

        for row in rows:
            try:
                payload = row["payload"] or {}
                tool = payload.get("tool")
                synthesized = _synthesize_event(tool, payload, company_id)
                if synthesized is None:
                    continue
                decision = await pipeline.process(synthesized)
                # Flow dispatch: fan out to the wired dispatcher whenever
                # the relevance gate decided to react. Previously gated on
                # ``synthesized.type == "file_drop"`` only — that swallowed
                # the proactive-mention path entirely (suggested_flow=
                # "mentioned_in_conversation" never reached the dispatcher,
                # so emit_proactive_offer never landed; PRD §9.2 / Block C
                # task C2 root cause).
                #
                # Now: any decision with should_react=True dispatches. The
                # dispatcher itself decides which flow to invoke based on
                # ``decision.suggested_flow`` and ``synthesized.type``.
                if (
                    flow_dispatcher is not None
                    and decision is not None
                    and getattr(decision, "should_react", False)
                ):
                    sf = getattr(decision, "suggested_flow", None)
                    logger.debug(
                        "flow dispatch: type=%s suggested_flow=%s reason=%s",
                        synthesized.get("type"),
                        sf,
                        getattr(decision, "reason", None),
                    )
                    try:
                        await flow_dispatcher(synthesized, decision)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "flow dispatch failed (type=%s flow=%s): %s",
                            synthesized.get("type"), sf, exc,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "chat_received poller row %s failed: %s",
                    row.get("seq"),
                    exc,
                )
            finally:
                # Always advance — a poison row should not freeze the loop.
                last_seq = max(last_seq, int(row["seq"]))

        try:
            await asyncio.sleep(poll_interval_s)
        except asyncio.CancelledError:
            raise


# ---------------------------------------------------------------------------
# F3 (Sub-wave A, 2026-05-30) — kpi_gap_triggered dispatcher hook.
#
# ``KpiGapTriggeredFlow`` was factory-only until this wave: the class
# was constructed in ``build_worm_core`` (line ~153) but no producer
# ever called ``propose_for_gap``. The audit at
# ``docs/superpowers/notes/2026-05-30-onboarding-audit.md`` §5 flow #5
# tagged it "partial — class + factory exist; not currently wired into
# a reactivity that watches the projection layer for gaps".
#
# The poller below closes that gap by watching for
# ``emit_semantic_gap_proposed`` ledger entries (the canonical
# agent-reported "no metric for this question" signal, written by the
# ``lake.semantic.gap`` MCP tool) and dispatching them to
# ``KpiGapTriggeredFlow.propose_for_gap``. The gap's ``nl_question`` is
# used as the ``kpi_id`` (KPI tree doesn't yet have a canonical
# `kpi_id` derived from `nl_question`; future work may promote the
# semantic-gap to a real KPI node before this hook fires).
#
# Same poller shape + tenant-reset detection + per-row exception
# swallow as ``chat_received_reactivity_poller`` so the loop is
# byte-identical operationally.
# ---------------------------------------------------------------------------


async def dispatch_kpi_gap_row(
    flow: Any,  # KpiGapTriggeredFlow
    company_id: UUID,
    payload: dict[str, Any],
    *,
    default_channel_id: str | None = None,
) -> bool:
    """Dispatch a single ``emit_semantic_gap_proposed`` payload to the flow.

    Returns True iff the flow was invoked. Returns False for skipped rows
    (e.g. no kpi_id, payload shape unexpected). Exceptions raised by the
    flow propagate; the caller (poller loop) decides whether to swallow.

    Extracted from ``kpi_gap_triggered_poller`` so unit tests can
    exercise the row-handling path without standing up a Postgres
    fixture. The poller composes this helper with a Postgres SELECT
    loop + tenant-reset detection.
    """
    args = (payload or {}).get("args") or {}
    # Lazy import to avoid circular at module load.
    from wormbase_chat_presence.chat_flows.kpi_gap_triggered import KpiGap
    kpi_id = args.get("proposed_metric_name") or args.get("nl_question") or ""
    if not kpi_id:
        return False
    gap = KpiGap(
        kpi_id=str(kpi_id),
        domain_id=None,
        owner_channel_id=default_channel_id,
    )
    await flow.propose_for_gap(company_id, gap)
    return True


async def kpi_gap_triggered_poller(
    ledger: "Ledger",
    flow: Any,  # KpiGapTriggeredFlow
    company_id: UUID,
    *,
    poll_interval_s: float = 5.0,
    initial_seq: int | None = None,
    default_channel_id: str | None = None,
) -> None:
    """Forward new ``emit_semantic_gap_proposed`` entries to the kpi-gap flow.

    Polls Postgres for ``execute`` rows whose payload ``tool`` is
    ``emit_semantic_gap_proposed`` and constructs a ``KpiGap`` for each
    one. The gap's ``kpi_id`` is the entry's ``nl_question`` (or the
    proposed_metric_name when present); ``owner_channel_id`` is the
    optional ``default_channel_id`` kwarg so the flow's interjection
    gate has a channel to ask permission against.

    Hooked from ``cli.py`` boot path: producers of
    ``emit_semantic_gap_proposed`` are the agent-gateway MCP tools, so
    a worm-core boot WITHOUT the agent-gateway never sees any rows and
    the poller is a no-op (correct).

    The loop catches every per-row exception so a single bad payload
    never wedges the poller; only ``CancelledError`` propagates. Mirrors
    ``chat_received_reactivity_poller``'s tenant-reset detection so a
    ledger wipe (``wormbase demo seed --reset-first``) does not freeze
    the poller against a stale seq.
    """
    if initial_seq is None:
        async with ledger.engine.begin() as conn:
            result = await conn.execute(
                _sql_text(
                    "SELECT COALESCE(MAX(seq), 0) FROM ledger WHERE company_id = :cid"
                ),
                {"cid": company_id},
            )
            initial_seq = int(result.scalar() or 0)

    last_seq = initial_seq
    logger.info(
        "kpi_gap_triggered poller starting: company_id=%s last_seq=%d "
        "interval=%.2fs default_channel=%s",
        company_id, last_seq, poll_interval_s,
        default_channel_id or "<unset>",
    )

    select_sql = _sql_text(
        """
        SELECT seq, payload, ts
          FROM ledger
         WHERE company_id = :cid
           AND kind = 'execute'
           AND payload->>'tool' = 'emit_semantic_gap_proposed'
           AND seq > :last_seq
         ORDER BY seq ASC
        """
    )
    max_seq_sql = _sql_text(
        "SELECT COALESCE(MAX(seq), 0) FROM ledger WHERE company_id = :cid"
    )

    while True:
        try:
            async with ledger.engine.begin() as conn:
                cur_max = int(
                    (await conn.execute(max_seq_sql, {"cid": company_id})).scalar()
                    or 0
                )
                if cur_max < last_seq:
                    logger.info(
                        "kpi_gap_triggered poller: tenant reset detected "
                        "(max_seq=%d < last_seq=%d); rewinding to 0",
                        cur_max, last_seq,
                    )
                    last_seq = 0
                result = await conn.execute(
                    select_sql, {"cid": company_id, "last_seq": last_seq}
                )
                rows = result.mappings().all()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("kpi_gap_triggered poller select failed: %s", exc)
            rows = []

        for row in rows:
            try:
                payload = row["payload"] or {}
                dispatched = await dispatch_kpi_gap_row(
                    flow, company_id, payload,
                    default_channel_id=default_channel_id,
                )
                if not dispatched:
                    logger.debug(
                        "kpi_gap_triggered poller: seq=%s skipped — no "
                        "kpi_id (proposed_metric_name + nl_question empty)",
                        row.get("seq"),
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "kpi_gap_triggered poller row %s failed: %s",
                    row.get("seq"), exc,
                )
            finally:
                last_seq = max(last_seq, int(row["seq"]))

        try:
            await asyncio.sleep(poll_interval_s)
        except asyncio.CancelledError:
            raise


def _synthesize_event(
    tool: str | None, payload: dict[str, Any], company_id: UUID
) -> dict[str, Any] | None:
    """Build a reactivity-pipeline raw event from an execute payload.

    Returns None for unknown tools (caller advances seq and moves on).
    """
    args = (payload or {}).get("args") or {}
    if tool in ("emit_chat_received", "channel_adapter.emit_chat_received"):
        channel_id = args.get("channel_id") or "unknown"
        message_id = args.get("message_id") or "0"
        text = args.get("text") or ""
        try:
            ts = float(message_id)
        except (TypeError, ValueError):
            ts = 0.0
        return {
            "type": "channel_message",
            "ts": ts,
            "channel_id": channel_id,
            "user_id": str(args.get("sender_person") or ""),
            "text": text,
            "message_id": message_id,
            "company_id": str(company_id),
            "payload": args,
        }
    if tool == "channel_adapter.emit_file_received":
        channel_id = args.get("channel_id") or "unknown"
        message_id = args.get("message_id") or "0"
        try:
            ts = float(message_id)
        except (TypeError, ValueError):
            ts = 0.0
        # Build a Slack-shaped file dict for downstream flow code, plus
        # the keys DropAndProfileFlow.on_file_drop reads directly off
        # InfraEvent.payload (filename, mimetype, bytes_url). Keeping
        # both shapes means flow code is unchanged AND the "files" array
        # is reconstructable on demand.
        slack_file = {
            "id": args.get("slack_file_id"),
            "name": args.get("file_name"),
            "mimetype": args.get("mimetype"),
            "size": args.get("file_size"),
            "url_private": args.get("url_private"),
        }
        caption = args.get("caption_text") or ""
        return {
            "type": "file_drop",
            "ts": ts,
            "channel_id": channel_id,
            "user_id": str(args.get("sender_person") or ""),
            "text": caption or (args.get("file_name") or ""),
            "message_id": message_id,
            "company_id": str(company_id),
            "payload": {
                # DropAndProfileFlow reads these:
                "filename": args.get("file_name"),
                "mimetype": args.get("mimetype"),
                "bytes_url": args.get("url_private"),
                # Slack-shaped echo for any consumer that wants it:
                "files": [slack_file],
                "caption_text": caption,
            },
        }
    return None


# ---------------------------------------------------------------------------
# Medallion cascade wiring (Step 2 of the canonical product arc).
#
# See ``docs/superpowers/specs/2026-04-26-wormbase-product-arc.md``. The
# cascade fires automatically after every drop_and_profile / lake_discovery
# proposal; the dispatcher returned here wraps the existing
# ``make_flow_dispatcher`` and runs bronze -> silver -> gold once the
# proposal lands.
# ---------------------------------------------------------------------------


def make_flow_dispatcher_with_cascade(
    drop_and_profile: DropAndProfileFlow,
    credential_in_dm: CredentialInDmFlow,
    company_id: UUID,
    cascade: Any,  # wormbase_core.medallion.MedallionCascade
):
    """Like ``make_flow_dispatcher`` but also runs the medallion cascade.

    For ``file_drop`` events the dispatcher first runs the existing
    ``drop_and_profile.on_file_drop(...)`` and then fires the cascade
    with the dropped file's URI. The cascade reads up to 100 KB from
    the URI (file:// only by default; remote URIs result in an
    empty-bytes deterministic profile). All other events fall through
    to the legacy dispatcher.
    """
    from wormbase_core.flows import cascade_after_propose

    base_dispatcher = make_flow_dispatcher(
        drop_and_profile, credential_in_dm, company_id,
    )

    async def _dispatch(event: dict, decision: Any) -> None:
        sf = getattr(decision, "suggested_flow", None)
        if sf == "drop_and_profile" and event.get("type") in _FILE_DROP_TYPES:
            infra_event = _event_to_infra(event, company_id)
            cid = await drop_and_profile.on_file_drop(infra_event)
            if cid is None:
                return
            payload = infra_event.payload or {}
            uri = (
                payload.get("bytes_url")
                or payload.get("url")
                or f"file://{payload.get('filename', 'unknown')}"
            )
            mime = payload.get("mimetype") or None
            try:
                await cascade_after_propose(
                    drop_and_profile.builder,
                    cascade,
                    correlation_id=str(cid),
                    company_id=company_id,
                    uri=uri,
                    mime=mime,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("medallion cascade failed: %s", exc)
            return
        # Other event types fall through.
        await base_dispatcher(event, decision)

    return _dispatch


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# === Step 2 (proactivity hook) ===
#
# Dispatcher extension: when the relevance gate sets ``suggested_flow ==
# "mentioned_in_conversation"`` AND the gate decided to react (the
# ``_DATA_SOURCE_KEYWORDS`` rule fired with confidence >= 0.6), call
# ``MentionedInConversationFlow.on_proactive_mention(event)``. The result
# carries the ``offer_text`` which the caller posts back into the channel
# via the existing chat path (same as @mention replies — see
# ``ConversationContract``). Append-only over ``make_flow_dispatcher_with_cascade``.
# ---------------------------------------------------------------------------


def make_flow_dispatcher_with_proactivity(
    drop_and_profile: DropAndProfileFlow,
    credential_in_dm: CredentialInDmFlow,
    mentioned_in_conversation: MentionedInConversationFlow,
    company_id: UUID,
    cascade: Any,  # wormbase_core.medallion.MedallionCascade
    chat_sender: Any | None = None,
):
    """Dispatcher that adds proactive-mention handling on top of the cascade.

    On a relevance decision with ``suggested_flow == "mentioned_in_conversation"``:
      1. Call ``mentioned_in_conversation.on_proactive_mention(event)`` —
         writes ``emit_source_proposed`` + ``emit_proactive_offer``.
      2. If a chat_sender is wired, post the ``offer_text`` to the channel
         via the same path the worm uses for @mention replies. The
         ConversationContract has already greenlit the speech act (the
         relevance gate's positive decision is the green light).

    All other event types fall through to ``make_flow_dispatcher_with_cascade``.
    """
    base = make_flow_dispatcher_with_cascade(
        drop_and_profile, credential_in_dm, company_id, cascade,
    )

    async def _dispatch(event: dict, decision: Any) -> None:
        sf = getattr(decision, "suggested_flow", None)
        should_react = bool(getattr(decision, "should_react", False))
        if sf == "mentioned_in_conversation" and should_react:
            infra_event = _event_to_infra(event, company_id)
            try:
                result = await mentioned_in_conversation.on_proactive_mention(
                    infra_event,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("proactive mention dispatch failed: %s", exc)
                return
            if result is None:
                return
            if chat_sender is not None and result.channel_id:
                try:
                    await chat_sender.send(
                        result.channel_id,
                        result.offer_text,
                        speech_act="proposal",
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "proactive offer chat send failed: %s", exc,
                    )
            return
        await base(event, decision)

    return _dispatch


# ---------------------------------------------------------------------------
# === Step 5 — research-loop boot path ===
#
# Removed 2026-05-03 (Wave C₁ — research-worm extraction, Block G2).
#
# The previous ``autoresearch_loop_runner`` re-export delegated to
# ``wormbase_core.autoresearch_loop`` (now lifted into the
# ``wormbase-research-loop`` package). The wall-clock per-Person/Team/
# Company timers were replaced by four W5a Reactivities registered via
# ``wormbase_research_loop.wire_research_for_install`` from cli.py.
# The ``ReactivityRunner`` is now the sole research orchestrator.
# ---------------------------------------------------------------------------


async def publish_kpi_answer_data_product(
    ledger: Any,
    company_id: UUID,
    *,
    question: str,
    answer_html: str,
    requested_by_person_id: UUID,
    citation_source_ids: list[UUID] | None = None,
    citation_source_hashes: list[str] | None = None,
    domain_id: UUID | None = None,
    prompted_by_message_id: str | None = None,
) -> tuple[UUID, dict]:
    """Publish a KPI answer as a first-class data product (F7).

    Called from the worm's @WormBase Q&A path: every answered KPI question
    drops an ``emit_data_product_proposed`` + ``emit_data_product_generated``
    pair so the answer becomes addressable at ``/data-products/{id}`` and
    replayable from pinned source-hashes (PRD §16.7).

    Returns ``(data_product_id, info)`` where info carries the entry ids
    of both PEVR cycles for caller logging.
    """
    from wormbase_core import data_product_actions
    from wormbase_core.storage import get_storage_backend

    storage = get_storage_backend()
    sources = list(citation_source_ids or [])
    source_hashes = list(citation_source_hashes or [])
    contents_bytes = answer_html.encode("utf-8")

    dp_id, propose_result = await data_product_actions.propose_data_product(
        ledger,
        company_id,
        name=question[:120] or "KPI question",
        kind="report",
        requested_by_person_id=requested_by_person_id,
        sources_required=sources,
        domain_id=domain_id,
        parameters={"question": question, "auto_kind": "kpi_answer"},
        prompted_by_message_id=prompted_by_message_id,
        proposed_by="worm",
        quadrant="passive_probabilistic",
    )

    # Run id derived from the dp_id seq for deterministic replay; we use a
    # uuid5 over the question text so re-asking the same question writes a
    # *new* dp (different id) but the contents path is stable per dp.
    from uuid import uuid4

    run_id = uuid4()
    contents_uri, content_hash = await storage.put(
        tenant_id=str(company_id),
        artifact_kind="data-products",
        artifact_id=str(dp_id),
        run_id=str(run_id),
        ext="html",
        data=contents_bytes,
    )
    gen_result = await data_product_actions.generate_data_product(
        ledger,
        company_id,
        data_product_id=dp_id,
        contents_uri=contents_uri,
        content_hash=content_hash,
        kind="report",
        source_hashes=source_hashes,
        duration_ms=0,
        generated_by="worm",
        quadrant="passive_probabilistic",
    )

    info = {
        "propose_entry_ids": [str(e) for e in propose_result.entry_ids],
        "generate_entry_ids": [str(e) for e in gen_result.entry_ids],
        "contents_uri": contents_uri,
        "content_hash": content_hash,
    }
    return dp_id, info


__all__ = [
    "WormCore",
    "build_worm_core",
    "chat_received_reactivity_poller",
    "dispatch_kpi_gap_row",
    "is_mentioned_in_conversation_enabled",
    "kpi_gap_default_channel_id",
    "kpi_gap_triggered_poller",
    "make_flow_dispatcher",
    "make_flow_dispatcher_with_cascade",
    "make_flow_dispatcher_with_proactivity",
    "publish_kpi_answer_data_product",
    "tenant_to_uuid",
]
