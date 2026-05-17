"""Translate a ParsedEvent into a 4-step propose/execute/verify/resolve write.

The ledger's ``write`` primitive always produces *four* entries — the
canonical PEVR cycle. For a chat event we therefore emit::

    propose     {target_kind: "chat_received"|"chat_sent", ref_id: <uuid>}
    execute     {tool: "channel_adapter.emit",
                 args:    <full ChatReceivedPayload | ChatSentPayload fields>,
                 result_ref: <message_id>}
    verify      {checks: [{name: "payload_valid", ok: true}], passed: true}
    resolve     {outcome: "keep", rationale: "..."}

The ``execute.args`` body matches the corresponding Pydantic payload model
in :mod:`wormbase_ledger.entries`, so a downstream projector that wants
to reconstruct ``ChatReceivedPayload`` / ``ChatSentPayload`` can simply
``model_validate(execute.args)`` once it has filtered ``kind=="execute"``
rows whose ``args`` contain the expected fields. This is the same shape
worm-core will write later when it generates outbound messages itself.

Quadrant: per CLAUDE.md "two speeds, four quadrants", chat traffic lives
in ``active_probabilistic`` (active = exchange touched the world; proba-
bilistic = no deterministic ground truth for what was said). We hard-code
that here.

Sender mapping: ``ChatReceivedPayload.sender_person`` is a UUID. Slack
gives us a string user id (``U0AV...``); we hash it to a stable UUIDv5
under a fixed namespace so the same Slack user always maps to the same
ledger UUID. A real deployment will swap this for a person-registry
lookup.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4, uuid5

from wormbase_ledger import Ledger
from wormbase_ledger.entries import (
    ChatReceivedPayload,
    ChatSentPayload,
    ConversationSyncPayload,
    InstallCompletedPayload,
)
from wormbase_ledger.write_primitive import WriteResult

from wormbase_channel_adapter.parser import (
    ChatReceivedEvent,
    ChatSentEvent,
    ParsedEvent,
)
from wormbase_channel_adapter.tenant import WORMBASE_TENANT_NAMESPACE

# Stable namespace for slack-user-id -> sender-person UUID mapping.
SLACK_USER_NAMESPACE = uuid5(WORMBASE_TENANT_NAMESPACE, "slack-user-namespace")

# Stable namespace for synthesized WhatsApp installer-person UUIDs (Wave B3.1,
# 2026-05-06). WhatsApp pairing has no installer Person at write time — Baileys
# QR-scan does not expose an OAuth-grant identity. The InstallCompletedPayload
# schema requires an ``installer_person_id`` UUID, so we synthesize one
# deterministically from ``(tenant_id, bot_jid)`` so:
#   * the same tenant + bot pairing always yields the same UUID across restarts
#     (idempotent ledger fold key);
#   * a future ``identity_linked`` from /people manual confirm can replace the
#     synthesized id with a real Person id without rewriting history (the
#     synthesized id stays as a stable ref).
WHATSAPP_INSTALLER_NAMESPACE = uuid5(
    WORMBASE_TENANT_NAMESPACE, "whatsapp-installer-namespace",
)


def slack_user_to_person_uuid(slack_user_id: str) -> UUID:
    """Deterministically map a Slack user id to a ledger ``sender_person`` UUID."""
    if not slack_user_id:
        # OpenClaw occasionally omits sender_id; fall back to a sentinel
        # so the payload still validates. The sentinel collides on
        # purpose — every "unknown sender" is the same UUID.
        return uuid5(SLACK_USER_NAMESPACE, "__unknown__")
    return uuid5(SLACK_USER_NAMESPACE, slack_user_id)


class LedgerWriter:
    """Wraps the ledger and exposes a single ``emit(event)`` async method."""

    def __init__(self, ledger: Ledger | Any, company_id: UUID) -> None:
        # Accepts InMemoryLedger too (same async surface). Typed as Any for
        # the alternate to avoid pulling InMemoryLedger into the public
        # writer signature.
        self._ledger = ledger
        self._company_id = company_id
        # Per-process dedup for assistant replies: OpenClaw double-writes
        # the assistant message to its session JSONL (two `stop` frames
        # ~3-50ms apart with identical text and different ids). The
        # parser dutifully emits a ChatSentEvent for each, so without
        # dedup the ledger ends up with duplicate chat_sent rows. Key by
        # ``(session_id, text)`` with a small LRU window so streaming
        # message chunks (which would have *different* texts as the
        # response builds) still flow through.
        self._recent_chat_sent: dict[tuple[str, str], None] = {}
        self._recent_chat_sent_max = 256
        # Per-process dedup for inbound chat_received: WhatsApp/Baileys
        # replays history on every reconnect, and Slack's stale-fetch
        # path can re-deliver an event after a reconnect. Key by
        # ``(channel_id, message_id)`` with a 1024-entry LRU; second
        # arrival of the same key returns None (no ledger write).
        # This is the substrate-level idempotency guarantee that lets
        # adapters be liberal about replay without poisoning the chain.
        self._recent_chat_received: dict[tuple[str, str], None] = {}
        self._recent_chat_received_max = 1024

    @property
    def company_id(self) -> UUID:
        return self._company_id

    async def emit(self, event: ParsedEvent) -> WriteResult | None:
        if isinstance(event, ChatReceivedEvent):
            return await self._emit_chat_received(event)
        if isinstance(event, ChatSentEvent):
            return await self._emit_chat_sent(event)
        raise TypeError(f"unsupported event type: {type(event).__name__}")

    # ------------------------------------------------------------------
    # Inbound: chat_received
    # ------------------------------------------------------------------

    async def _emit_chat_received(
        self, event: ChatReceivedEvent,
    ) -> WriteResult | None:
        # Dedup against WhatsApp/Slack replay: same (channel_id,
        # message_id) seen twice → second arrival is a no-op. LRU
        # eviction at 1024 distinct keys keeps memory bounded; the
        # window is large enough to absorb a typical reconnect-replay
        # batch (Baileys defaults to up to 50 messages per channel) and
        # still hold weeks of distinct live traffic.
        dedup_key = (event.channel_id, event.message_id)
        if dedup_key in self._recent_chat_received:
            return None
        if len(self._recent_chat_received) >= self._recent_chat_received_max:
            self._recent_chat_received.pop(next(iter(self._recent_chat_received)))
        self._recent_chat_received[dedup_key] = None

        ref_id = uuid4()
        sender_person = slack_user_to_person_uuid(event.sender_id)

        # Build and validate the canonical payload up front; if validation
        # raises, we never touch the ledger.
        payload = ChatReceivedPayload(
            channel_id=event.channel_id,
            message_id=event.message_id,
            sender_person=sender_person,
            text=event.text,
            classification="internal",
            delivery_mode=event.delivery_mode,
            platform_ts=event.platform_ts,
            history_sync_id=event.history_sync_id,
            mentioned_jids=event.mentioned_jids,
            # Raw platform-native sender id (Slack U…, WhatsApp jid). Distinct
            # from sender_person (UUID hash); the raw form is what
            # WhatsAppOrganicDiscoveryReactivity matches against the DM-jid
            # regex to fire person_proposed on previously-unseen senders.
            platform_user_id=event.sender_id or None,
        )
        args = payload.model_dump(mode="json")

        return await self._ledger.write(
            company_id=self._company_id,
            propose={
                "target_kind": "chat_received",
                "ref_id": str(ref_id),
                "reason": f"slack inbound from {event.sender_label or event.sender_id}",
                "proposed_by": "channel-adapter",
            },
            execute_fn=lambda: {
                "tool": "channel_adapter.emit_chat_received",
                "args": args,
                "result_ref": event.message_id,
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "payload_valid", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "slack inbound persisted",
            },
            timestamp=event.ts,
            quadrant="active_probabilistic",
        )

    # ------------------------------------------------------------------
    # Lineage: conversation_sync
    # ------------------------------------------------------------------

    async def emit_conversation_sync(
        self,
        *,
        sync_id: UUID,
        platform: str,
        install_id: str | None,
        channels: list[str],
        trigger: Literal["initial_connect", "reconnect", "channel_join"],
        started_at: datetime,
        completed_at: datetime,
        message_count: int,
        earliest_ts: datetime | None,
        latest_ts: datetime | None,
        status: Literal["completed", "interrupted"] = "completed",
    ) -> WriteResult:
        """Write the full PEVR cycle for one completed sync session.

        Called by adapter sync state machines when a reconnect or initial
        connect's history-replay quiet-window elapses (or the connection
        drops mid-sync, in which case ``status="interrupted"``).

        Quadrant: ``passive_deterministic`` — sync sessions are
        background bookkeeping driven by platform reconnect events, not
        user-initiated probabilistic actions.
        """
        payload = ConversationSyncPayload(
            sync_id=sync_id,
            platform=platform,
            install_id=install_id,
            channels=channels,
            trigger=trigger,
            started_at=started_at,
            completed_at=completed_at,
            message_count=message_count,
            earliest_ts=earliest_ts,
            latest_ts=latest_ts,
            status=status,
        )
        args = payload.model_dump(mode="json")

        return await self._ledger.write(
            company_id=self._company_id,
            propose={
                "target_kind": "conversation_sync",
                "ref_id": str(sync_id),
                "reason": (
                    f"{platform} {trigger}: {message_count} historical messages"
                ),
                "proposed_by": "channel-adapter",
            },
            execute_fn=lambda: {
                "tool": "channel_adapter.emit_conversation_sync",
                "args": args,
                "result_ref": str(sync_id),
            },
            verify_fn=lambda _r: {
                "checks": [
                    {"name": "payload_valid", "ok": True},
                    {"name": "message_count_nonneg", "ok": message_count >= 0},
                ],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": f"{platform} sync session recorded",
            },
            timestamp=completed_at,
            quadrant="passive_deterministic",
        )

    # ------------------------------------------------------------------
    # Lineage: install_completed (WhatsApp pairing-complete)
    # ------------------------------------------------------------------

    @staticmethod
    def synthesize_whatsapp_installer_person_id(
        tenant_id: str | None, bot_jid: str,
    ) -> UUID:
        """Deterministically synthesize an installer Person UUID for WhatsApp.

        WhatsApp's pairing-complete signal (Baileys ``connection_open``)
        carries no OAuth-grant identity — we don't know "who" did the
        scan from the wire. The :class:`InstallCompletedPayload` schema
        requires an ``installer_person_id``, so this helper hashes
        ``(tenant_id, bot_jid)`` under
        :data:`WHATSAPP_INSTALLER_NAMESPACE` to produce a stable
        synthesized id.

        Same ``(tenant_id, bot_jid)`` always yields the same UUID across
        restarts; this is the idempotency key the emitter folds against
        and the stable ref any future ``identity_linked`` (from /people
        manual confirm) can attach to.
        """
        tenant_part = tenant_id if tenant_id else "_no_tenant"
        return uuid5(
            WHATSAPP_INSTALLER_NAMESPACE, f"{tenant_part}:{bot_jid}",
        )

    async def emit_whatsapp_install(
        self,
        *,
        tenant_id: str | None,
        bot_jid: str,
        account_id: str | None,
        pairing_method: str = "qr",
        paired_at: datetime,
        provider: str = "openclaw_baileys",
        creds_path: str,
    ) -> WriteResult | None:
        """Write the full PEVR cycle for a WhatsApp pairing-complete event.

        WhatsApp has no OAuth grant; pairing-complete is Baileys'
        ``connection_open`` after a successful QR scan. The
        :class:`WhatsAppChannelAdapter` invokes this on the FIRST such
        event per ``(tenant_id, bot_jid)`` (in-process LRU); we then
        fold the ledger here as the source-of-truth idempotency layer
        so a cache-cleared adapter (process restart) does not
        double-install.

        Quadrant: ``active_deterministic`` — install is an explicit,
        externally-triggered, deterministic admin action (operator
        scanned a QR), not a probabilistic conversation event.

        Idempotency contract:

        1. **In-process LRU** in the adapter — fast path.
        2. **Ledger fold** here — walk the ledger looking for any prior
           ``install_completed`` whose args match
           ``(tenant_id, platform=whatsapp, bot_user_id=bot_jid)``. If
           one exists, return ``None`` without writing.

        Args:
            tenant_id: tenant slug; threaded into the synthesized
                ``installer_person_id`` and the ``tenant_id`` field
                of :class:`InstallCompletedPayload`. ``None`` for
                single-tenant deployments collapses to the company_id.
            bot_jid: the bot's WhatsApp jid (e.g.
                ``"5511...@s.whatsapp.net"``); written as
                ``bot_user_id`` per the InstallCompletedPayload schema.
            account_id: the OpenClaw account id (== install_id
                surrogate). When ``None``, ``install_id`` is generated
                fresh via ``uuid4()``.
            pairing_method: ``"qr"`` today; future Meta Cloud API may
                add others.
            paired_at: UTC tz-aware datetime of pairing completion.
            provider: ``"openclaw_baileys"`` today.
            creds_path: descriptive container path (e.g.
                ``"/var/openclaw/whatsapp/baileys/<account>/creds.json"``).
                NEVER credential material — the
                ``oauth_grant_ref`` enforces the ``vault://`` prefix
                via the InstallCompletedPayload validator.

        Returns:
            ``WriteResult`` from the PEVR write, or ``None`` when the
            ledger fold absorbs the call as already-installed.
        """
        installer_person_id = self.synthesize_whatsapp_installer_person_id(
            tenant_id, bot_jid,
        )

        # Ledger fold — source-of-truth idempotency. If a prior
        # install_completed exists for the same (tenant, platform=whatsapp,
        # bot_user_id), this is a re-pairing event after process restart;
        # the adapter's LRU was empty, but the ledger remembers.
        if await self._has_existing_whatsapp_install(
            tenant_id=tenant_id, bot_jid=bot_jid,
        ):
            return None

        # Resolve install_id: prefer the OpenClaw account_id (so it
        # surfaces consistently in install + downstream conversation_sync
        # entries via the install_id field), but generate fresh if absent.
        if account_id:
            try:
                install_id = UUID(account_id)
            except (TypeError, ValueError):
                # account_id is a free-form OpenClaw key (e.g. "wa-1"),
                # not necessarily a UUID. Synthesize a stable id from
                # the same key so re-pairings under the same account
                # always resolve identically.
                install_id = uuid5(
                    WHATSAPP_INSTALLER_NAMESPACE,
                    f"install:{tenant_id or '_no_tenant'}:{account_id}",
                )
        else:
            install_id = uuid4()

        # Tenant id: InstallCompletedPayload requires UUID. When tenant_id
        # is a slug (production case, e.g. "baseworm"), hash it under the
        # installer namespace for a stable UUID. When None, fall back to
        # company_id so the row stays scoped within the writer's tenancy.
        if tenant_id:
            try:
                tenant_uuid = UUID(tenant_id)
            except (TypeError, ValueError):
                tenant_uuid = uuid5(
                    WHATSAPP_INSTALLER_NAMESPACE,
                    f"tenant:{tenant_id}",
                )
        else:
            tenant_uuid = self._company_id

        # Descriptive sentinel — vault:// prefix required by validator.
        # Never carries credential material; the path is a reference for
        # the operator to find the creds.json on the OpenClaw mount.
        oauth_grant_ref = (
            f"vault://wormbase/whatsapp-baileys/{account_id or 'default'}"
        )

        payload = InstallCompletedPayload(
            install_id=install_id,
            tenant_id=tenant_uuid,
            platform="whatsapp",
            installer_person_id=installer_person_id,
            oauth_grant_ref=oauth_grant_ref,
            scopes=[],
            bot_user_id=bot_jid,
        )
        args = payload.model_dump(mode="json")
        # Include WhatsApp-specific paired_at + provider + creds_path on
        # the execute args for downstream consumers — the schema model
        # doesn't carry them, but the projection layer reads them off
        # the execute payload (mirroring how complete_install threads
        # extra metadata via execute args today).
        args["paired_at"] = paired_at.isoformat()
        args["provider"] = provider
        args["pairing_method"] = pairing_method
        args["creds_path"] = creds_path

        return await self._ledger.write(
            company_id=self._company_id,
            propose={
                "target_kind": "install_completed",
                "ref_id": str(install_id),
                "reason": (
                    f"whatsapp pairing complete for {bot_jid} "
                    f"(tenant={tenant_id or '_'}, account={account_id or '_'})"
                ),
                "proposed_by": "channel-adapter.whatsapp",
            },
            execute_fn=lambda: {
                "tool": f"emit_{InstallCompletedPayload.kind}",
                "args": args,
                "result_ref": str(install_id),
            },
            verify_fn=lambda _r: {
                "checks": [
                    {"name": "payload_valid", "ok": True},
                    {"name": "bot_jid_present", "ok": bool(bot_jid)},
                ],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "whatsapp install recorded via pairing-complete",
            },
            timestamp=paired_at,
            quadrant="active_deterministic",
        )

    async def _has_existing_whatsapp_install(
        self, *, tenant_id: str | None, bot_jid: str,
    ) -> bool:
        """Fold the ledger for a prior whatsapp install for this (tenant, jid).

        Matches the read shape used by /people install projections:
        ``tool=emit_install_completed`` with
        ``args.platform == "whatsapp"`` and
        ``args.bot_user_id == bot_jid``. Tenant scoping is implicit via
        ``self._company_id`` (the writer is per-company); the ``tenant_id``
        kwarg is included for forward-compat where a single company hosts
        multiple WhatsApp accounts under different tenant slugs.

        Conservative on read failure: returns ``True`` (don't write) so
        a transient ledger error does not double-install. The next
        ``connection_open`` retries.
        """
        try:
            rows = await self._ledger.fetch(self._company_id)
        except Exception:  # noqa: BLE001
            return True
        for r in rows:
            if r.get("kind") != "execute":
                continue
            payload = r.get("payload") or {}
            if payload.get("tool") != f"emit_{InstallCompletedPayload.kind}":
                continue
            args = payload.get("args") or {}
            if args.get("platform") != "whatsapp":
                continue
            if args.get("bot_user_id") != bot_jid:
                continue
            return True
        return False

    # ------------------------------------------------------------------
    # Outbound: chat_sent
    # ------------------------------------------------------------------

    async def _emit_chat_sent(self, event: ChatSentEvent) -> WriteResult | None:
        # Dedup against OpenClaw's double-frame quirk (see __init__ note).
        dedup_key = (event.session_id, event.text)
        if dedup_key in self._recent_chat_sent:
            return None
        # LRU eviction: drop oldest insertion when over capacity. Python
        # dicts preserve insertion order, so popping the first item is O(1).
        if len(self._recent_chat_sent) >= self._recent_chat_sent_max:
            self._recent_chat_sent.pop(next(iter(self._recent_chat_sent)))
        self._recent_chat_sent[dedup_key] = None

        ref_id = uuid4()
        # OpenClaw doesn't expose the slack ts of the *outbound* message
        # in the JSONL (it's posted asynchronously by the Slack channel
        # plugin). Use the OpenClaw event id as a stable surrogate.
        message_id = event.event_id

        payload = ChatSentPayload(
            channel_id="",  # session-scoped; channel resolution is v1.1
            message_id=message_id,
            text=event.text,
            in_reply_to=event.in_reply_to,
            attribution={
                "source": "openclaw",
                "session_id": event.session_id,
            },
            speech_act="answer",
        )
        args = payload.model_dump(mode="json")

        return await self._ledger.write(
            company_id=self._company_id,
            propose={
                "target_kind": "chat_sent",
                "ref_id": str(ref_id),
                "reason": "assistant final reply",
                "proposed_by": "channel-adapter",
            },
            execute_fn=lambda: {
                "tool": "channel_adapter.emit_chat_sent",
                "args": args,
                "result_ref": message_id,
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "payload_valid", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "assistant reply persisted",
            },
            timestamp=event.ts,
            quadrant="active_probabilistic",
        )
