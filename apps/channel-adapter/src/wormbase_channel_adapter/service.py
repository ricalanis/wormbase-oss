"""Service composition root: wire ledger + tailers + writer together.

Two parallel capture paths feed the writer:

1. **Session JSONL tailer** (the original path) — picks up agent-engaged
   conversations from OpenClaw's per-session ``*.jsonl`` files. Carries
   the rich Slack metadata block (sender_id, conversation_label, etc.).
2. **OpenClaw global log tailer** (Path 3) — observes every inbound
   platform event regardless of agent engagement. Multi-platform aware:
   the tailer hands ``(platform, channel_id)`` tuples to the dispatch
   table built in :func:`run_service`; each platform binds to its own
   capture handler (Slack uses :class:`GlobalLogCapture`; WhatsApp gets
   its own once Phase 3 lands). Until a handler is registered for a
   platform, lines for that platform are logged-and-dropped — not
   raised — so an unrecognized platform never wedges the loop.

Both paths funnel through :class:`LedgerWriter` and produce the same
``execute`` payload shape (``tool=channel_adapter.emit_chat_received``)
so worm-core's chat_received poller picks up either source identically.

Dedup: the global-log path can race the JSONL path on agent-engaged
events. We dedup on Slack ``ts`` per channel inside the global-log
handler (the JSONL path uses byte-offset state for its own dedup). If
both paths emit the same ts, two ledger entries land — the downstream
consumer is idempotent at the ``message_id`` level via the lurker
poller's seq tracking, so the dedup happens at consumption time even
if both producers race.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

from wormbase_ledger import Ledger
from wormbase_ledger.entries import ChatReceivedPayload
from wormbase_ledger.schema import metadata as ledger_metadata

from wormbase_channel_adapter.hermes_event_consumer import HermesEventConsumer
from wormbase_channel_adapter.parser import ChatReceivedEvent, ParsedEvent
from wormbase_channel_adapter.slack_client import SlackClient
from wormbase_channel_adapter.state import OffsetState
from wormbase_channel_adapter.tailer import Tailer, pump
from wormbase_channel_adapter.tenant import tenant_to_company_uuid
from wormbase_channel_adapter.whatsapp_envelope_watcher import (
    WhatsAppInboundEnvelopeWatcher,
)
from wormbase_channel_adapter.writer import LedgerWriter, slack_user_to_person_uuid

log = logging.getLogger(__name__)


async def _ensure_schema(ledger: Ledger) -> None:
    """Create ledger tables if they don't exist.

    A full deployment runs alembic explicitly; the bootstrap path
    materializes the schema on first boot so a fresh Postgres volume
    works without a separate migration step. Idempotent — running this
    against an already-migrated database is a no-op.
    """
    async with ledger.engine.begin() as conn:
        await conn.run_sync(ledger_metadata.create_all)


class GlobalLogCapture:
    """Resolve channel-id signals into chat_received ledger entries.

    Held as an object (rather than a closure) so the dedup state is
    inspectable in tests and the bot-id lookup is centralized.

    File drops produce an ADDITIONAL ``channel_adapter.emit_file_received``
    execute entry per ``files[]`` element, alongside the chat_received
    entry that carries the message caption. The file entry's ``args``
    dict has the following shape (generic — no Pydantic model needed,
    since this is not a registered ledger ``kind``)::

        {
            "channel_id":     str,            # Slack channel id
            "message_id":     str,            # Slack ts
            "sender_person":  str,            # UUID (slack-user-derived)
            "slack_file_id":  str,            # Slack file id (file["id"])
            "file_name":      str | None,
            "mimetype":       str | None,
            "file_size":      int | None,
            "url_private":    str | None,
            "classification": "internal",
            "caption_text":   str | None,     # message.text, often empty
        }

    Worm-core's poller dequeues these and synthesizes a
    ``type="file_drop"`` event for the reactivity pipeline.
    """

    def __init__(
        self,
        *,
        ledger: Ledger | Any,
        company_id: UUID,
        slack: SlackClient,
    ) -> None:
        self._ledger = ledger
        self._company_id = company_id
        self._slack = slack
        # channel_id -> last emitted Slack ts (string). String compare is
        # fine: Slack ts values are zero-padded epoch seconds with a dot
        # and 6-digit microsecond suffix, so lexicographic == numeric.
        self._last_ts: dict[str, str] = {}
        # (channel_id, ts, slack_file_id) tuples already emitted. Memory-
        # only dedup; cleared on restart. Re-emitting after a restart is
        # idempotent at the worm-core poller (it tracks last_seq).
        self._emitted_files: set[tuple[str, str, str]] = set()

    @property
    def last_ts(self) -> dict[str, str]:
        return dict(self._last_ts)

    @property
    def emitted_files(self) -> set[tuple[str, str, str]]:
        return set(self._emitted_files)

    async def on_channel_admit(self, channel_id: str) -> None:
        """Called by the log tailer for each ``allow channel`` line."""
        try:
            msg = await self._slack.fetch_latest_message(channel_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("slack fetch failed for %s: %s", channel_id, exc)
            return
        if msg is None:
            log.debug(
                "openclaw-log: fetch_latest_message returned None for %s",
                channel_id,
            )
            return
        ts = msg.get("ts")
        if not isinstance(ts, str) or not ts:
            log.debug(
                "openclaw-log: latest msg in %s has no ts; skipping",
                channel_id,
            )
            return
        # Echo-loop guard: drop our own bot's outbound *chat* messages.
        # The guard applies to chat-only — NOT to file_received fan-out.
        #
        # Why: in our setup the worm never uploads files (its only outbound
        # action is chat.postMessage). Files arriving in a channel are
        # therefore always real wire events — either a real user upload
        # OR a sim-harness `files_upload_v2` (which Slack records as a
        # bot-owned upload because the bot token is the only path through
        # which sim can attribute uploads). Echoing such file_share events
        # as self-echo would suppress every file drop the sim performs,
        # breaking the demo's drop_and_profile flow end-to-end (PRD §9.1).
        #
        # Modern Slack apps post with as_user=true and Slack sets NO
        # `subtype` on the resulting message, so we cannot gate on
        # `subtype == "bot_message"`. The reliable identity signal is
        # the message's `bot_id` (and as a backup the user id).
        bot_id = self._slack.bot_id
        bot_user_id = self._slack.bot_user_id
        msg_bot_id = msg.get("bot_id")
        msg_user = msg.get("user")
        is_self_echo_chat = bool(
            (bot_id is not None and msg_bot_id == bot_id)
            or (bot_user_id is not None and msg_user == bot_user_id)
        )
        last = self._last_ts.get(channel_id)
        already_seen_ts = last is not None and ts <= last
        files = msg.get("files")
        has_files = isinstance(files, list) and len(files) > 0

        log.debug(
            "openclaw-log admit: channel=%s ts=%s msg_user=%r msg_bot=%r "
            "self_echo_chat=%s has_files=%s",
            channel_id, ts, msg_user, msg_bot_id, is_self_echo_chat, has_files,
        )

        if not already_seen_ts and not is_self_echo_chat:
            await self._emit_chat_received(channel_id, ts, msg)
        elif is_self_echo_chat:
            # Mark as seen so a later same-ts call from a non-bot path
            # is also short-circuited.
            self._last_ts[channel_id] = ts

        # File-drop fan-out: emit one file_received per file in the
        # message's `files[]`. NOT gated on is_self_echo_chat — see comment
        # above. Per-file dedup is handled in _emit_file_received via the
        # (channel, ts, file_id) tuple in self._emitted_files.
        if has_files:
            assert isinstance(files, list)  # for type narrowing
            user_id = msg.get("user") or msg.get("bot_id") or ""
            sender_person = slack_user_to_person_uuid(str(user_id))
            caption_text = msg.get("text") or ""
            for f in files:
                if not isinstance(f, dict):
                    continue
                await self._emit_file_received(
                    channel_id=channel_id,
                    ts=ts,
                    sender_person=sender_person,
                    caption_text=caption_text,
                    file=f,
                )

        # Always advance last_ts once we've handled this message (chat
        # and/or files), so the next poll won't re-process the same ts.
        if last is None or ts > last:
            self._last_ts[channel_id] = ts

    async def _emit_chat_received(
        self, channel_id: str, ts: str, msg: dict[str, Any]
    ) -> None:
        text = msg.get("text") or ""
        user_id = msg.get("user") or msg.get("bot_id") or ""
        sender_person = slack_user_to_person_uuid(str(user_id))

        try:
            payload = ChatReceivedPayload(
                channel_id=channel_id,
                message_id=ts,
                sender_person=sender_person,
                text=text,
                classification="internal",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("chat_received payload validation failed: %s", exc)
            return

        ref = uuid4()
        try:
            await self._ledger.write(
                company_id=self._company_id,
                propose={
                    "target_kind": "chat_received",
                    "ref_id": str(ref),
                    "reason": (
                        f"openclaw log: allow channel {channel_id} "
                        f"(slack user {user_id or '?'})"
                    ),
                    "proposed_by": "channel-adapter.openclaw-log",
                },
                execute_fn=lambda: {
                    "tool": "channel_adapter.emit_chat_received",
                    "args": payload.model_dump(mode="json"),
                    "result_ref": ts,
                },
                verify_fn=lambda _r: {
                    "checks": [{"name": "payload_valid", "ok": True}],
                    "passed": True,
                },
                resolve_fn=lambda _v: {
                    "outcome": "keep",
                    "rationale": "openclaw-log path captured inbound",
                },
                quadrant="active_probabilistic",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("ledger write failed for %s/%s: %s", channel_id, ts, exc)
            return

        log.info(
            "openclaw-log capture: channel=%s ts=%s text_len=%d",
            channel_id,
            ts,
            len(text),
        )

    async def _emit_file_received(
        self,
        *,
        channel_id: str,
        ts: str,
        sender_person: UUID,
        caption_text: str,
        file: dict[str, Any],
    ) -> None:
        slack_file_id = file.get("id")
        if not isinstance(slack_file_id, str) or not slack_file_id:
            log.warning(
                "skipping file with no id on channel=%s ts=%s", channel_id, ts
            )
            return
        dedup_key = (channel_id, ts, slack_file_id)
        if dedup_key in self._emitted_files:
            return

        file_name = file.get("name") if isinstance(file.get("name"), str) else None
        mimetype = (
            file.get("mimetype") if isinstance(file.get("mimetype"), str) else None
        )
        raw_size = file.get("size")
        file_size: int | None
        if isinstance(raw_size, int):
            file_size = raw_size
        elif isinstance(raw_size, float):
            file_size = int(raw_size)
        else:
            file_size = None
        url_private = (
            file.get("url_private")
            if isinstance(file.get("url_private"), str)
            else None
        )

        args: dict[str, Any] = {
            "channel_id": channel_id,
            "message_id": ts,
            "sender_person": str(sender_person),
            "slack_file_id": slack_file_id,
            "file_name": file_name,
            "mimetype": mimetype,
            "file_size": file_size,
            "url_private": url_private,
            "classification": "internal",
            "caption_text": caption_text or None,
        }

        ref = uuid4()
        try:
            await self._ledger.write(
                company_id=self._company_id,
                propose={
                    "target_kind": "file_received",
                    "ref_id": str(ref),
                    "reason": (
                        f"openclaw log: file_share channel={channel_id} "
                        f"file={slack_file_id}"
                    ),
                    "proposed_by": "channel-adapter.openclaw-log",
                },
                execute_fn=lambda: {
                    "tool": "channel_adapter.emit_file_received",
                    "args": args,
                    "result_ref": slack_file_id,
                },
                verify_fn=lambda _r: {
                    "checks": [{"name": "file_meta_present", "ok": True}],
                    "passed": True,
                },
                resolve_fn=lambda _v: {
                    "outcome": "keep",
                    "rationale": "openclaw-log path captured file drop",
                },
                quadrant="active_probabilistic",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "ledger write failed for file %s/%s/%s: %s",
                channel_id,
                ts,
                slack_file_id,
                exc,
            )
            return

        self._emitted_files.add(dedup_key)
        log.info(
            "openclaw-log file capture: channel=%s ts=%s file_id=%s "
            "file_name=%r mimetype=%s file_size=%s",
            channel_id,
            ts,
            slack_file_id,
            file_name,
            mimetype,
            file_size,
        )


class WhatsAppLogCapture:
    """Resolve whatsapp ``allow channel <jid>`` log lines into ledger entries.

    Mirrors :class:`GlobalLogCapture` (Slack) in shape. Holds a
    :class:`WhatsAppChannelAdapter` + its AuthHandle. On each admit:

    1. Ensure a default ``policy_applied`` entry exists for the channel
       (talkativeness="lurker", daily_interjection_budget=0) — see
       :meth:`_ensure_default_policy`. Writes happen on the FIRST admit
       per ``channel_id``; subsequent admits are no-ops.
    2. Defer to the adapter's ``fetch_latest_and_normalize`` to surface
       a normalized :class:`InfraEvent` with provenance fields stamped
       by the sync state machine (``delivery_mode``,
       ``history_sync_id``, ``platform_ts``).
    3. Translate the InfraEvent into a ``ChatReceivedEvent`` shape and
       hand it to :class:`LedgerWriter._emit_chat_received`. The writer's
       built-in dedup on ``(channel_id, message_id)`` absorbs duplicate
       arrivals from history-replay batches.

    The WhatsApp adapter's sync state machine writes a
    ``conversation_sync`` ledger entry on its own (via the injected
    ``sync_emitter`` — :meth:`LedgerWriter.emit_conversation_sync`); the
    capture handler is per-message only.

    **Why default-lurker on first-touch (Wave A2, 2026-05-06):** the
    chat-presence default policy is ``responsive`` with budget 3, which
    is correct for Slack channels but unsafe for WhatsApp — Wave C wires
    outbound ``send`` and an accidental flip to responsive could silently
    start posting in real WhatsApp groups. By writing an explicit
    ``policy_applied`` ledger entry on first ingest, we record a defensive
    posture (lurker, budget 0) that survives Wave C and any future
    posture-changing UX. Slack channels are unaffected — this code path
    only runs for the WhatsApp dispatch handler.

    Honesty notes (preserved verbatim from the adapter docstring):

    * Outbound send is NOT wired in v1 — only ingest flows here.
    * The OpenClaw log-line grammar for whatsapp is **assumed
      symmetric** to Slack's; if the running OpenClaw emits a different
      shape, the regex in
      :mod:`wormbase_channel_adapter.openclaw_log_tail` needs an update.
    """

    # Bound the channel-seen LRU. A real deployment will see at most a
    # handful of WhatsApp channels per tenant in v1 (one bot phone), but
    # the cap keeps memory bounded if a misbehaving log-line generator
    # spams admits for thousands of distinct jids.
    _SEEN_CHANNELS_MAX = 4096

    def __init__(
        self,
        *,
        adapter: Any,
        handle: Any,
        writer: LedgerWriter,
        company_id: UUID,
    ) -> None:
        self._adapter = adapter
        self._handle = handle
        self._writer = writer
        self._company_id = company_id
        # Per-process cache of channel_ids known to already have a
        # policy_applied entry in the ledger. Insertion-ordered so we
        # can evict oldest at the cap. Cleared on restart; the ledger
        # query on first miss after restart re-hydrates the cache.
        # Multi-tenant safety: this object is per-`company_id` (one
        # WhatsAppLogCapture per service.run_service call), so no
        # cross-tenant contamination is possible.
        self._seen_channels: dict[str, None] = {}

    @property
    def seen_channels(self) -> set[str]:
        """Inspectable channel-id LRU (test hook)."""
        return set(self._seen_channels)

    async def _ensure_default_policy(self, channel_id: str) -> None:
        """Write a defensive lurker policy on first admit for this channel.

        Idempotent in two layers:

        1. **In-process cache** — once we've confirmed (or written) a
           policy for ``channel_id``, the next call is an O(1) miss-skip.
        2. **Ledger fold** — on cache miss we walk the ledger looking for
           any prior ``policy_applied`` entry tied to this channel. If
           one exists (any source), we record-and-skip without writing.

        The fold is a safety net: a freshly-restarted service whose cache
        is empty must not double-write an existing policy. Same shape
        ``ChatStore.read_policy`` reads, so the fold is byte-correct.
        """
        if channel_id in self._seen_channels:
            return

        # Cache miss → fold the ledger for any existing policy_applied
        # tied to this channel under the channel_talkativeness template.
        existing = await self._has_existing_policy(channel_id)
        if existing:
            self._mark_seen(channel_id)
            return

        # First-touch: write the defensive lurker entry as a full PEVR cycle.
        ref_id = uuid4()
        policy_id = uuid4()
        args: dict[str, Any] = {
            "policy_id": str(policy_id),
            "policy_name": "policy:channel_talkativeness",
            "applies_to": {"scope": "channel", "channel_id": channel_id},
            "rule": "whatsapp first-touch lurker default",
            "gate_impl": "channel_talkativeness_default",
            "talkativeness": "lurker",
            "daily_interjection_budget": 0,
        }
        try:
            await self._writer._ledger.write(
                company_id=self._company_id,
                propose={
                    "target_kind": "policy_applied",
                    "ref_id": str(ref_id),
                    "reason": (
                        f"whatsapp first-touch: defensive lurker default "
                        f"for {channel_id}"
                    ),
                    "proposed_by": "channel-adapter.whatsapp",
                },
                execute_fn=lambda: {
                    "tool": "emit_policy_applied",
                    "args": args,
                    "result_ref": channel_id,
                },
                verify_fn=lambda _r: {
                    "checks": [{"name": "payload_valid", "ok": True}],
                    "passed": True,
                },
                resolve_fn=lambda _v: {
                    "outcome": "applied",
                    "rationale": (
                        "defensive lurker on first-touch; raise via "
                        "/channels POST when ready"
                    ),
                },
                quadrant="active_deterministic",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "whatsapp policy_applied write failed for %s: %s",
                channel_id, exc,
            )
            # Don't mark seen on failure — a future admit will retry.
            return

        self._mark_seen(channel_id)
        log.info(
            "whatsapp first-touch: wrote default lurker policy_applied "
            "channel=%s budget=0",
            channel_id,
        )

    def _mark_seen(self, channel_id: str) -> None:
        """Insert into the LRU; evict oldest if at cap."""
        if len(self._seen_channels) >= self._SEEN_CHANNELS_MAX:
            self._seen_channels.pop(next(iter(self._seen_channels)))
        self._seen_channels[channel_id] = None

    async def _has_existing_policy(self, channel_id: str) -> bool:
        """Fold the ledger for a prior policy_applied for this channel.

        Matches the read shape ``_LedgerBackedChatStore.read_policy``
        uses (tool=``emit_policy_applied``, policy_name=
        ``policy:channel_talkativeness``, applies_to.channel_id match).
        Company-scoped via ``self._company_id`` — multi-tenant safe.
        """
        try:
            rows = await self._writer._ledger.fetch(self._company_id)
        except Exception as exc:  # noqa: BLE001
            # Conservative on read failure: do not write (avoid
            # double-writes during transient ledger errors). The next
            # admit will retry the fold.
            log.warning(
                "whatsapp policy fold failed for %s: %s",
                channel_id, exc,
            )
            return True
        for r in rows:
            if r.get("kind") != "execute":
                continue
            payload = r.get("payload") or {}
            if payload.get("tool") != "emit_policy_applied":
                continue
            args = payload.get("args") or {}
            if args.get("policy_name") != "policy:channel_talkativeness":
                continue
            applies_to = args.get("applies_to") or {}
            if applies_to.get("channel_id") == channel_id:
                return True
        return False

    async def on_channel_admit(self, channel_id: str) -> None:
        """Called by the log tailer for each whatsapp ``allow channel`` line."""
        # Wave A2: defensive lurker policy on first-touch. Runs BEFORE
        # the fetch_latest_and_normalize path so a same-admit-burst can
        # write the policy even if the message fetch fails.
        await self._ensure_default_policy(channel_id)

        try:
            event = await self._adapter.fetch_latest_and_normalize(
                self._handle, channel_id,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "whatsapp fetch_latest_and_normalize failed for %s: %s",
                channel_id, exc,
            )
            return
        if event is None:
            log.debug(
                "whatsapp openclaw-log: no event for %s (likely first-poll "
                "before adapter has cached a message)",
                channel_id,
            )
            return
        if not event.platform_message_id:
            log.debug(
                "whatsapp openclaw-log: dropping event with no message id "
                "channel=%s",
                channel_id,
            )
            return

        # Translate InfraEvent → ChatReceivedEvent shape so the existing
        # writer dedup + provenance plumbing applies. Sender label is
        # left blank — WhatsApp identity discovery happens via the
        # standard auto-discovery loop on the platform_user_id (jid).
        # ``mentioned_jids`` is forwarded straight through (Wave B1.1):
        # the adapter's _normalize_message extracts the array from
        # Baileys' contextInfo, and the writer threads it into
        # ChatReceivedPayload so the MentionsWorm WhatsApp branch
        # evaluates correctly on real ledger entries.
        chat_event = ChatReceivedEvent(
            kind="chat_received",
            session_id=channel_id,  # session-scoped at the channel
            event_id=event.platform_message_id,
            ts=event.ts,
            channel_id=channel_id,
            message_id=event.platform_message_id,
            sender_id=event.platform_user_id or "",
            sender_label=None,
            text=event.text,
            conversation_label=None,
            delivery_mode=event.delivery_mode,
            platform_ts=event.platform_ts,
            history_sync_id=event.history_sync_id,
            mentioned_jids=event.mentioned_jids,
        )
        try:
            await self._writer.emit(chat_event)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "whatsapp ledger write failed for %s/%s: %s",
                channel_id, event.platform_message_id, exc,
            )
            return
        log.info(
            "whatsapp openclaw-log capture: channel=%s msg=%s "
            "delivery_mode=%s text_len=%d",
            channel_id,
            event.platform_message_id,
            event.delivery_mode,
            len(event.text),
        )


async def run_service(
    *,
    ledger_dsn: str,
    sessions_path: str,
    state_path: str,
    tenant_slug: str = "baseworm",
    poll_interval_s: float = 0.5,
    openclaw_log_dir: str | None = None,
    slack_bot_token: str | None = None,
    whatsapp_account_id: str | None = None,
    gateway_kind: str = "hermes",
    hermes_consumer_host: str = "0.0.0.0",
    hermes_consumer_port: int = 18790,
) -> None:
    """Run the channel adapter until SIGINT/SIGTERM.

    The ``gateway_kind`` parameter selects the inbound transport per
    `docs/superpowers/specs/2026-04-27-openclaw-to-hermes-migration.md`
    §6 Phase 2:

      - ``"openclaw"`` (default): legacy OpenClaw log-tail path. Tails
        ``openclaw_log_dir`` for ``slack: allow channel <CID>`` lines.
      - ``"hermes"``: Phase 1 Hermes Agent path. Starts an HTTP
        consumer on ``hermes_consumer_port`` that receives wire-tap
        hook POSTs and emits :class:`ChatReceivedEvent` directly via
        the writer.

    Both paths funnel through the same :class:`LedgerWriter`; per-
    process ``(channel_id, message_id)`` dedup means running both
    simultaneously during a cutover window is safe (the second
    arrival of the same key is a no-op).
    """
    company_id = tenant_to_company_uuid(tenant_slug)
    log.info("tenant %r → company_id %s", tenant_slug, company_id)

    ledger = Ledger(ledger_dsn)
    await _ensure_schema(ledger)
    writer = LedgerWriter(ledger, company_id)

    state = OffsetState(state_path)
    state.load()
    log.info(
        "loaded offset state from %s (%d session(s) tracked)",
        state_path,
        len(state.items()),
    )

    # Construct the WhatsApp envelope watcher when the OpenClaw daily
    # log directory is mounted. This is independent of slack_bot_token
    # because the watcher's only job is to cache recent inbound
    # envelopes for the session-JSONL parser to correlate against —
    # OpenClaw 2026.5.6 does NOT emit Slack-style admit lines for
    # WhatsApp, so without this watcher inbound WhatsApp DMs land in
    # session JSONL with no envelope and the parser drops them.
    envelope_watcher: WhatsAppInboundEnvelopeWatcher | None = None
    envelope_watcher_task: asyncio.Task[None] | None = None
    envelope_lookup = None
    if openclaw_log_dir:
        # Direct-emission callback for the openclaw 2026.5.6+ web-inbound
        # format. The watcher builds a ChatReceivedEvent from the log
        # line's structured payload (which now includes body) and pushes
        # it straight to the writer — bypassing the legacy
        # session-JSONL-correlation path that no longer fires under
        # silent-mode gate 6 (the gate-6 plugin claims `before_agent_reply`
        # which prevents the user message from landing in session JSONL).
        envelope_watcher = WhatsAppInboundEnvelopeWatcher(
            openclaw_log_dir,
            on_inbound=writer.emit,
        )
        envelope_lookup = envelope_watcher.find_recent_envelope
        log.info(
            "whatsapp envelope watcher enabled: log_dir=%s (direct emission on)",
            openclaw_log_dir,
        )

    tailer = Tailer(
        sessions_path,
        state,
        poll_interval_s=poll_interval_s,
        whatsapp_envelope_lookup=envelope_lookup,
    )

    # When the openclaw-log capture path is active, it is the single
    # source of truth for inbound Slack chat (chat_received). The JSONL
    # session tailer would emit a duplicate from the agent's own session
    # record, so we suppress Slack-shaped chat_received from the JSONL
    # path and keep only chat_sent (bot replies — those only appear in
    # the agent JSONL).
    #
    # WhatsApp is the inverse: OpenClaw 2026.5.6 doesn't emit
    # ``whatsapp: allow channel <jid>`` admit lines, so the daily-log
    # capture path NEVER fires for WhatsApp. The session-JSONL parser
    # (now correlating envelopes via ``whatsapp_envelope_lookup``) is the
    # ONLY source of WhatsApp chat_received entries. We let those
    # through unconditionally.
    # Phase 4: openclaw log-tail retired (commit landed on
    # `feat/hermes-migration`). Disable the dedup branch so the
    # session-JSONL parser becomes the canonical Slack chat_received
    # emitter again, alongside Hermes wire-tap.
    log_tail_active = False

    async def handler(event: ParsedEvent) -> None:
        if log_tail_active and isinstance(event, ChatReceivedEvent):
            # Distinguish Slack vs WhatsApp by the channel_id grammar.
            # WhatsApp DMs surface ``<digits>@s.whatsapp.net`` (set by
            # the parser's WhatsApp fallback path); Slack channels are
            # ``channel:C...`` or similar. Only Slack-shaped events get
            # deduped against the daily-log capture path.
            is_whatsapp_shaped = event.channel_id.endswith(
                "@s.whatsapp.net",
            ) or event.channel_id.endswith("@g.us")
            if not is_whatsapp_shaped:
                # Deduped against the openclaw-log capture path.
                return
        log.info(
            "emit %s session=%s event=%s",
            event.kind,
            event.session_id,
            event.event_id,
        )
        await writer.emit(event)

    stop_event = asyncio.Event()

    def _on_signal(*_: Any) -> None:
        log.info("shutdown signal received")
        stop_event.set()
        tailer.stop()
        if envelope_watcher is not None:
            envelope_watcher.stop()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            # Windows / restricted environments: rely on KeyboardInterrupt.
            pass

    # Start the envelope watcher BEFORE we begin pumping the session
    # tailer. The watcher's open-at-end behavior means freshly-arriving
    # log lines are picked up immediately; any race where the session
    # JSONL frame lands a few ms before the watcher caches its envelope
    # is absorbed by the parser's 30s correlation window.
    if envelope_watcher is not None:
        envelope_watcher_task = asyncio.create_task(envelope_watcher.run())

    # Phase 1 Hermes path. When ``gateway_kind == "hermes"`` we start
    # an HTTP server on ``hermes_consumer_port`` that receives wire-tap
    # hook POSTs. The legacy OpenClaw log-tail path below still runs
    # (when openclaw_log_dir is set) so a single channel-adapter can
    # consume from BOTH gateways simultaneously during a Phase 2
    # cutover window. Dedup at the writer absorbs duplicate
    # (channel_id, message_id) arrivals.
    hermes_consumer: HermesEventConsumer | None = None
    hermes_consumer_task: asyncio.Task[None] | None = None
    if gateway_kind.lower() == "hermes":
        hermes_consumer = HermesEventConsumer(
            writer=writer,
            host=hermes_consumer_host,
            port=hermes_consumer_port,
        )
        hermes_consumer_task = asyncio.create_task(hermes_consumer.run())
        log.info(
            "hermes event consumer enabled: listening on http://%s:%d",
            hermes_consumer_host, hermes_consumer_port,
        )

    log.info(
        "channel-adapter up: sessions=%s ledger=%s poll=%.1fs "
        "envelope_watcher=%s gateway_kind=%s",
        sessions_path,
        _redact_dsn(ledger_dsn),
        poll_interval_s,
        "on" if envelope_watcher is not None else "off",
        gateway_kind,
    )

    # Optional: OpenClaw global log tailer + Slack client.
    #
    # B6: the Slack-API surface lives in
    # ``wormbase_channel_adapters.SlackChannelAdapter``. We load it
    # from the registry (Protocol-driven) and authenticate to get an
    # AuthHandle whose ``extra`` carries the live AsyncWebClient. The
    # SlackClient facade in this package wraps that same client so
    # GlobalLogCapture's existing API (``slack.bot_id`` etc.) keeps
    # working unchanged.
    # Phase 4 (openclaw retirement): the OpenClawLogTailer code path is
    # gone. Variables retained as None so the cleanup logic below stays
    # uniform and a partial rollback (re-introducing the tailer in a
    # follow-up commit) doesn't require structural edits.
    log_tailer: Any = None
    log_tailer_task: asyncio.Task[None] | None = None
    # The Slack admit-channel dispatch table is preserved (and the
    # SlackClient initialization below) so the existing tests that
    # construct a service WITH slack_bot_token can still authenticate;
    # without the OpenClawLogTailer the admit channel events simply
    # never fire and the dispatch table sits idle.
    if False and openclaw_log_dir and slack_bot_token:  # noqa: SIM223 — see comment
        # Load the Slack adapter from the registry (Protocol-driven).
        from wormbase_channel_adapters import (
            SecretBundle as _SecretBundle,
            default_registry as _default_registry,
        )
        adapter_cls = _default_registry().get("slack")
        if adapter_cls is not None:
            adapter = adapter_cls()
            await adapter.authenticate(_SecretBundle(
                payload={"bot_token": slack_bot_token},
            ))
            log.info(
                "SlackChannelAdapter loaded from registry "
                "(B6 refactor — every Slack-API call now flows through it)",
            )
        slack = SlackClient(slack_bot_token)
        # auth.test once at startup; non-fatal if it fails.
        await slack.resolve_bot_id()
        capture = GlobalLogCapture(
            ledger=ledger, company_id=company_id, slack=slack,
        )

        def _on_signal_extra(*_: Any) -> None:
            if log_tailer is not None:
                log_tailer.stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _on_signal_extra)
            except NotImplementedError:
                pass

        # Platform dispatch table. The OpenClawLogTailer surfaces every
        # ``<platform>: allow channel <id>`` line as ``(platform, channel_id)``;
        # we route by platform here. Phase 3 (2026-05-05) added the WhatsApp
        # handler — gated on ``whatsapp_account_id`` being configured so
        # Slack-only deployments stay byte-identical with prior behavior.
        # Unknown platforms hit the "no adapter registered" branch and are
        # dropped gracefully.
        platform_admit_handlers: dict[
            str, Callable[[str], Awaitable[None]]
        ] = {
            "slack": capture.on_channel_admit,
        }

        # Optional WhatsApp wire-up. Activates when ``whatsapp_account_id``
        # is provided (sourced from ``WHATSAPP_ACCOUNT_ID`` env in __main__).
        # Loads the WhatsAppChannelAdapter from the registry, authenticates
        # against the configured account, and threads the writer's
        # emit_conversation_sync as the sync_emitter so completed
        # history-sync sessions land in the ledger as conversation_sync
        # entries.
        if whatsapp_account_id:
            wa_cls = _default_registry().get("whatsapp")
            if wa_cls is None:
                log.warning(
                    "whatsapp adapter requested but not registered "
                    "(WHATSAPP_ACCOUNT_ID=%r ignored)",
                    whatsapp_account_id,
                )
            else:
                # Wave B3.1 (2026-05-06): wire install_emitter so the
                # adapter's pairing-complete signal lands an
                # ``install_completed`` ledger entry on the FIRST
                # connection_open per (tenant, bot_jid). The writer's
                # method enforces idempotency via ledger fold; the
                # adapter's in-process LRU is the fast path.
                wa_adapter = wa_cls(
                    sync_emitter=writer.emit_conversation_sync,
                    install_emitter=writer.emit_whatsapp_install,
                    install_id=whatsapp_account_id,
                    tenant_id=tenant_slug,
                )
                wa_handle = await wa_adapter.authenticate(_SecretBundle(
                    payload={
                        "account_id": whatsapp_account_id,
                        "tenant_id": tenant_slug,
                    },
                ))
                wa_capture = WhatsAppLogCapture(
                    adapter=wa_adapter,
                    handle=wa_handle,
                    writer=writer,
                    company_id=company_id,
                )
                platform_admit_handlers["whatsapp"] = (
                    wa_capture.on_channel_admit
                )
                log.info(
                    "WhatsAppChannelAdapter wired: account_id=%s "
                    "(preview status — see status_note for caveats)",
                    whatsapp_account_id,
                )

        async def _on_admit(platform: str, channel_id: str) -> None:
            handler = platform_admit_handlers.get(platform)
            if handler is None:
                log.warning(
                    "openclaw-log: no adapter registered for platform=%r, "
                    "dropping admit channel_id=%r",
                    platform,
                    channel_id,
                )
                return
            await handler(channel_id)

        # Phase 4: OpenClawLogTailer deleted. The block above is
        # `if False` so the body never runs; preserved as a placeholder
        # for the spec-described "two-phase" rollback (re-add the
        # tailer + drop `if False` if you need to roll back to a
        # hybrid OpenClaw+Hermes state).
        pass
    else:
        log.info(
            "openclaw-log capture path retired (Phase 4 of "
            "openclaw→hermes migration). Inbound now flows via "
            "HermesEventConsumer; envelope_watcher still owns "
            "WhatsApp ingest correlation."
        )

    try:
        await pump(tailer, state, handler)
    finally:
        if log_tailer is not None:
            log_tailer.stop()
        if log_tailer_task is not None:
            try:
                await asyncio.wait_for(log_tailer_task, timeout=2.0)
            except (TimeoutError, Exception):  # noqa: BLE001
                log_tailer_task.cancel()
        if envelope_watcher is not None:
            envelope_watcher.stop()
        if envelope_watcher_task is not None:
            try:
                await asyncio.wait_for(envelope_watcher_task, timeout=2.0)
            except (TimeoutError, Exception):  # noqa: BLE001
                envelope_watcher_task.cancel()
        if hermes_consumer is not None:
            hermes_consumer.stop()
        if hermes_consumer_task is not None:
            try:
                await asyncio.wait_for(hermes_consumer_task, timeout=2.0)
            except (TimeoutError, Exception):  # noqa: BLE001
                hermes_consumer_task.cancel()
        await ledger.dispose()
        log.info("channel-adapter shutdown complete")


def _redact_dsn(dsn: str) -> str:
    """Obscure the password in a SQLAlchemy DSN for log output."""
    if "@" not in dsn or "://" not in dsn:
        return dsn
    scheme, rest = dsn.split("://", 1)
    creds, host = rest.split("@", 1)
    if ":" in creds:
        user = creds.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}"
    return dsn
