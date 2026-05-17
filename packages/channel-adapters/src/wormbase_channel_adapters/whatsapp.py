"""WhatsApp channel adapter — preview, via OpenClaw Baileys (WhatsApp Web).

Owns every WhatsApp-specific call the channel-adapter service makes.
Mirrors :mod:`wormbase_channel_adapters.slack` in shape — install +
listen + fetch path — with one structural addition: an internal
**sync state machine** that distinguishes live (push) traffic from
the bulk history-replay Baileys streams on every reconnect.

The state machine is the WhatsApp-specific reconciliation of the
provenance-vs-lineage substrate landed in Phase 1:

* ``IDLE`` — no active connection. New messages arriving here flip
  the machine into ``SYNC_IN_PROGRESS`` (defensive heuristic; in
  practice ``connection_open`` triggers the flip first).
* ``SYNC_IN_PROGRESS`` — Baileys is replaying history after a
  reconnect/initial-connect. Each inbound message is stamped
  ``delivery_mode="history_sync"`` and tagged with the active
  ``history_sync_id``. The machine flips to ``LIVE`` after a 5-second
  quiet window (no new messages) elapses, OR on an explicit
  ``messaging-history.set`` event from OpenClaw if surfaced.
* ``LIVE`` — steady state. Each inbound message is stamped
  ``delivery_mode="push"``, ``history_sync_id=None``. A
  ``connection_drop`` event flips back to ``IDLE`` and the next
  ``connection_open`` opens a new sync session.

On the ``SYNC_IN_PROGRESS → LIVE`` transition, a ``conversation_sync``
ledger entry is written via ``LedgerWriter.emit_conversation_sync``
with the accumulated bounds (channels, message_count, earliest_ts,
latest_ts). On ``connection_drop`` mid-sync, the same write fires
with ``status="interrupted"``.

**Capability honesty.** As of 2026-05-06 (Wave C, this commit), this
adapter ships at ``status="preview"``:

* ``ingest`` — wired via OpenClaw's Baileys plugin and the log-tail
  ``allow channel <jid>`` capture path (Phase 4 generalized the
  regex).
* ``dm`` — wired (jids ending in ``@s.whatsapp.net`` flow as DMs).
* ``send`` — **wired** through OpenClaw's CLI (``openclaw message
  send --channel whatsapp``) via ``asyncio.create_subprocess_exec``
  ``docker exec``-ing into the gateway container. The empirical C1
  finding was that OpenClaw exposes no plain HTTP send route; the
  outbound surface is the WebSocket gateway, and the canonical
  client wire is the bundled CLI. The HTTP route shape OpenClaw
  upstream issue #73016 promises will land flips ``_do_send`` to a
  one-liner POST without changing the public surface here.

  Config envs (all optional, sane defaults):

  * ``WORMBASE_WHATSAPP_OPENCLAW_CONTAINER`` (default
    ``wormbase-openclaw``): container name to ``docker exec`` into.
  * ``WORMBASE_WHATSAPP_OPENCLAW_TOKEN``: gateway token (the master
    ``gateway.auth.token``). When set, passed to the CLI via
    ``--token``. Required for non-pre-paired CLI invocations
    (typical container deploys).
  * ``WORMBASE_WHATSAPP_OPENCLAW_ACCOUNT`` (default ``default``):
    the WhatsApp ``accountId`` slot the CLI invokes against.
  * ``WORMBASE_WHATSAPP_SEND_DISABLE`` (truthy): hard-disables
    outbound; raises ``NotImplementedError`` regardless. For ops
    safety while a tenant rotates phones.

  **Status stays preview, not production**, because the production
  wire still depends on (a) operator-approved write scopes on the
  paired CLI device or master-token granting via Control UI, AND
  (b) the channel-adapter container having either docker-host
  access or being co-deployed alongside the gateway. The wire works
  end-to-end when the operator has approved the upgrade, but the
  approval step is not automated. Capability honesty: ``send`` IS
  in :attr:`capability` because the path exists and round-trips;
  status honesty: this is a preview wire because production
  graduation requires the operator-approval automation that lands
  alongside or after OpenClaw issue #73016.

* ``file_upload`` — out of scope for v1. Per plan §12.

**Baileys ToS.** Baileys is an unofficial WhatsApp Web reverse-
engineered library. Account bans are possible. Use only on dedicated
test numbers — never production CEO numbers. Production transport
will land via Meta Cloud API once OpenClaw issue #73016 closes.

**Log-line grammar gap.** Phase 4 assumed WhatsApp's OpenClaw log
emits ``whatsapp: allow channel <jid> ...`` symmetric to Slack's
``slack: allow channel <C...> ...``. This is **empirically
unverified**: it requires a running OpenClaw instance with the
WhatsApp Baileys plugin enabled and a paired number. The preview
status reflects this gap. If the grammar differs in production, the
``_ALLOW_CHANNEL_RE`` alternation in
``apps/channel-adapter/src/wormbase_channel_adapter/openclaw_log_tail.py``
needs updating; the rest of the adapter stays unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Literal
from uuid import UUID, uuid4

from .base import ChannelAdapter
from .registry import register_channel_adapter
from .types import (
    AuthHandle,
    ChannelCap,
    ChannelRef,
    InfraEvent,
    InstallRecord,
    MessageRef,
    OutMessage,
    Platform,
    PlatformMember,
    SecretBundle,
)
from .whatsapp_rate_limit import (
    PolicyAppliedEmitter,
    with_whatsapp_rate_limit,
)


def resolve_whatsapp_bot_phone(
    *,
    tenant_id: str | None = None,
    company_id: str | UUID | None = None,
) -> str | None:
    """Resolve the WhatsApp bot phone number.

    Single resolver contract used by both ``MentionsWorm`` (chat-presence)
    and ``WhatsAppChannelAdapter`` (channel-adapters), pinned to byte-
    equivalent behavior by ``tests/contract/test_whatsapp_bot_phone_env_resolver.py``.
    Per CLAUDE.md §1.5 rule 3, the two packages may not import from each
    other; this helper is duplicated module-locally in both, with the
    contract test enforcing equivalence.

    Precedence (returns first non-empty match, stripping a leading ``+``):

    1. ``WORMBASE_WHATSAPP_BOT_PHONE_<TENANT_UPPER>`` — when ``tenant_id``
       is given. Tenant slug is upper-cased verbatim (no other transform).
    2. ``WORMBASE_WHATSAPP_BOT_PHONE_<COMPANY_ID_UPPER>`` — when
       ``company_id`` is given. UUID is stringified and upper-cased,
       PRESERVING dashes (matches the existing B1 convention pinned by
       ``test_whatsapp_mention_e2e.py``; do not change without coordinated
       env-var rotation).
    3. ``WORMBASE_WHATSAPP_BOT_PHONE`` — single-tenant fallback (no suffix).

    Returns ``None`` if all three are unset OR if the first non-empty
    match is whitespace-only after stripping ``+``. Callers treat ``None``
    as "we don't know who we are, so no mention can match" / "fall back
    to a sentinel bucket key".

    Single-tenant deployments set just (3). Multi-tenant deployments set
    (1) per-tenant or (2) per-company-id, whichever the operator prefers.
    Setting both (1) and (2) is supported (precedence picks (1) first)
    and intentionally back-compatible with deployments that already set
    both today.

    NB on adapter usage: the adapter typically only knows ``tenant_id``
    at construction time (passed in via ``WhatsAppChannelAdapter.__init__``
    or sourced from ``handle.extra["tenant_id"]``); ``company_id`` is not
    threaded through the adapter surface. So path (1) and path (3) are
    the active paths from the adapter; path (2) activates only via the
    chat-presence predicate which has ``ReactivityContext.company_id``
    in scope.
    """
    if tenant_id:
        tenant_key = str(tenant_id).upper()
        scoped = os.environ.get(
            f"WORMBASE_WHATSAPP_BOT_PHONE_{tenant_key}",
        )
        normalized = _normalize_phone(scoped)
        if normalized is not None:
            return normalized
    if company_id is not None:
        company_key = str(company_id).upper()
        scoped = os.environ.get(
            f"WORMBASE_WHATSAPP_BOT_PHONE_{company_key}",
        )
        normalized = _normalize_phone(scoped)
        if normalized is not None:
            return normalized
    fallback = os.environ.get("WORMBASE_WHATSAPP_BOT_PHONE")
    return _normalize_phone(fallback)


def _truthy(raw: str | None) -> bool:
    """Coerce env-var-style strings to a boolean.

    Returns True for ``"1"``, ``"true"``, ``"yes"``, ``"on"`` (any case)
    after stripping whitespace. Everything else (including ``None``) is
    False. Used by the WhatsApp send kill-switch
    (``WORMBASE_WHATSAPP_SEND_DISABLE``).
    """
    if not raw:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_phone(raw: str | None) -> str | None:
    """Strip surrounding whitespace + leading '+'; treat empties as None.

    Order matters: whitespace must be stripped FIRST so values like
    ``"   +  "`` (whitespace-padded plus sign with no digits) collapse
    to the empty string and are treated as unset, not as a literal "+"
    phone number. Test pin:
    ``tests/contract/test_whatsapp_bot_phone_env_resolver.py::test_whitespace_only_value_treated_as_unset``.
    """
    if not raw:
        return None
    cleaned = raw.strip().lstrip("+").strip()
    if not cleaned:
        return None
    return cleaned

log = logging.getLogger(__name__)


# Quiet-window duration for SYNC_IN_PROGRESS → LIVE heuristic. Baileys
# replays a Slack-window-sized burst on reconnect (defaults around 50
# messages per channel) within seconds; 5s of quiet is the empirical
# crossover where steady-state push deliveries take over.
_SYNC_QUIET_WINDOW_S = 5.0


class _WhatsAppSyncState(str, Enum):
    """Internal sync-machine state.

    Lives behind the adapter's public surface. The state never leaks
    onto InfraEvent — only the derived ``delivery_mode`` /
    ``history_sync_id`` fields do.
    """

    IDLE = "idle"
    SYNC_IN_PROGRESS = "sync_in_progress"
    LIVE = "live"


@dataclass
class _ActiveSync:
    """Bookkeeping for one in-progress sync session.

    Attributes accumulated as messages arrive in ``SYNC_IN_PROGRESS``;
    handed to ``emit_conversation_sync`` on completion or interruption.
    """

    sync_id: UUID
    trigger: Literal["initial_connect", "reconnect", "channel_join"]
    started_at: datetime
    channels: set[str] = field(default_factory=set)
    message_count: int = 0
    earliest_ts: datetime | None = None
    latest_ts: datetime | None = None
    last_message_at: datetime | None = None


# Type aliases for the conversation-sync writer + the sync-completion
# callback. The adapter accepts both as optional constructor injection
# for clean test composition. In production, the channel-adapter
# service.py wires LedgerWriter.emit_conversation_sync as the sync
# emitter so completed sessions land in the ledger via the same PEVR
# cycle as any other write.
ConversationSyncEmitter = Callable[..., Awaitable[Any]]


# Type alias for the install-emission callback (Wave B3, 2026-05-06).
# Invoked on the FIRST ``on_connection_open`` per ``(tenant_id, bot_jid)``
# pair. Signature mirrors the production wiring point in
# ``wormbase_channel_adapter.writer.LedgerWriter.emit_whatsapp_install``:
#   await emitter(
#       tenant_id=<str|None>,    # the AuthHandle tenant; passed through for env scoping
#       account_id=<str>,        # the OpenClaw account_id (== install_id surrogate)
#       bot_jid=<str>,           # the bot's WhatsApp jid (e.g. "5511...@s.whatsapp.net")
#       pairing_method=<str>,    # "qr" today; future Meta Cloud API may add others
#       paired_at=<datetime>,    # UTC tz-aware
#       provider=<str>,          # "openclaw_baileys" today
#       creds_path=<str>,        # descriptive container path (NOT credential material)
#   )
# Implementations MUST be ledger-idempotent (in-process cache + ledger
# fold) so a cache-cleared adapter does not trigger a double-install.
# The adapter is the fast-path; the emitter is the source of truth.
InstallEmitter = Callable[..., Awaitable[Any]]


@register_channel_adapter
class WhatsAppChannelAdapter(ChannelAdapter):
    """WhatsApp platform adapter (preview, via OpenClaw Baileys).

    See module docstring for state-machine semantics and capability
    honesty notes.
    """

    platform: Platform = "whatsapp"
    # Capability set as of Wave C (2026-05-06): ingest + dm + send.
    # send is wired via OpenClaw CLI subprocess (path verified empirically
    # in C1; native HTTP route still pending upstream issue #73016, at
    # which point _do_send swaps to a one-liner POST without surface
    # change). file_upload + voice remain explicit non-goals for v1.
    capability: set[ChannelCap] = {"ingest", "dm", "send"}
    status: str = "preview"
    # Capability-honest summary — ≤200 chars per adapter-card contract
    # (see packages/channel-adapters/tests/test_adapter_status.py). The
    # full caveat surface (Baileys ToS, log-line empirical gap, send
    # CLI-subprocess wiring with operator-approval gating, native HTTP
    # route pending OpenClaw issue #73016) is documented in this
    # module's docstring; the note here is the dashboard-facing summary.
    status_note: str = (
        "Preview. Ingest+DM+send via OpenClaw Baileys (unofficial WA "
        "Web; ToS test-numbers-only). Send via CLI subprocess; needs "
        "operator scopes. HTTP route pending #73016; log grammar "
        "unverified."
    )

    # Bound for the install-detection LRU. One bot_jid per tenant in
    # production; the cap protects against a misbehaving driver that
    # rapidly re-pairs / re-tenants and would otherwise leak entries.
    _SEEN_INSTALLS_MAX = 1024

    def __init__(
        self,
        *,
        sync_emitter: ConversationSyncEmitter | None = None,
        policy_emitter: PolicyAppliedEmitter | None = None,
        install_emitter: InstallEmitter | None = None,
        install_id: str | None = None,
        tenant_id: str | None = None,
        sync_quiet_window_s: float = _SYNC_QUIET_WINDOW_S,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Construct a WhatsApp adapter.

        ``sync_emitter`` (optional): a coroutine matching
        :meth:`wormbase_channel_adapter.writer.LedgerWriter.emit_conversation_sync`
        kwargs. Production wiring passes this in from the
        channel-adapter service so completed syncs land in the ledger.
        Tests pass a fake to capture invocation args.

        ``policy_emitter`` (optional, Wave E2, 2026-05-06): a coroutine
        invoked when the WhatsApp send rate-limit backoff exhausts
        (3 retries, all 429). Emits a ``policy_applied`` ledger entry
        per active throttle session — see
        :mod:`wormbase_channel_adapters.whatsapp_rate_limit` for the
        signature contract. Production wires
        :meth:`LedgerWriter.emit_policy_applied`. Tests pass a fake to
        capture invocation args. Reuses the existing ``policy_applied``
        entry kind (no schema-evolution change).

        ``install_emitter`` (optional, Wave B3, 2026-05-06): a coroutine
        invoked on the FIRST ``on_connection_open`` per
        ``(tenant_id, bot_jid)`` pair. WhatsApp's pairing-complete
        signal is Baileys' ``connection_open`` after a successful QR
        scan; this hook is the install-write site for the WhatsApp
        adapter (Slack uses an OAuth-grant path; WhatsApp uses pairing).
        Production wiring passes :meth:`LedgerWriter.emit_whatsapp_install`
        from channel-adapter service. Tests pass a fake to capture
        invocation args. See :data:`InstallEmitter` for the kwargs
        contract. Idempotency is two-layered: in-process LRU on
        ``(tenant_id, bot_jid)`` here, plus ledger fold inside the
        emitter (production) — same belt-and-braces shape as Wave A2's
        WhatsApp default-policy detection.

        ``install_id`` (optional): the InstallRecord id; threaded into
        each ``conversation_sync`` payload's ``install_id`` field. Also
        passed to the install_emitter as ``account_id`` so the same
        OpenClaw account / install id surfaces consistently in both
        the install entry and downstream conversation_sync entries.

        ``tenant_id`` (optional, Wave E2 + B3): tenant key threaded into
        the rate-limit bucket key + the throttle-audit emission, AND
        used to scope bot-phone env resolution at install time
        (``WORMBASE_WHATSAPP_BOT_PHONE_<TENANT>``). When provided at
        construction it takes precedence over
        ``handle.extra["tenant_id"]`` for rate-limit purposes; the
        latter remains the fallback for runtime drivers that don't
        thread tenant at construction time.

        ``sync_quiet_window_s``: the quiet-window seconds before a
        SYNC_IN_PROGRESS flips to LIVE. Tests override this to drive
        the timer fast.

        ``clock`` (optional): a callable returning ``datetime`` in UTC.
        Tests inject a fake clock for deterministic state-machine
        verification. Defaults to ``datetime.now(tz=UTC)``.
        """
        self._sync_emitter = sync_emitter
        self._policy_emitter = policy_emitter
        self._install_emitter = install_emitter
        self._install_id = install_id
        self._tenant_id = tenant_id
        self._sync_quiet_window_s = sync_quiet_window_s
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # State machine.
        self._state: _WhatsAppSyncState = _WhatsAppSyncState.IDLE
        self._active_sync: _ActiveSync | None = None
        # Quiet-window timer task. Cancelled on each new message;
        # restarted on each arrival; fires _complete_sync on timeout.
        self._quiet_timer_task: asyncio.Task[None] | None = None
        # Last-known message cache used by fetch_latest_and_normalize
        # tests — production injects its own _fetch_message override.
        # Keyed by jid (channel_id).
        self._last_msg: dict[str, dict[str, Any]] = {}
        # Install-detection LRU keyed by ``(tenant_id, bot_jid)``.
        # Insertion-ordered so we can evict oldest at the cap. Cleared on
        # restart; the emitter's ledger fold re-hydrates on first miss
        # after restart so a previously-installed pair does NOT
        # double-install. Multi-tenant safe: ``tenant_id`` is part of
        # the key, and a single adapter instance is per-tenant in
        # production wiring (one ``WhatsAppChannelAdapter`` per
        # ``WHATSAPP_ACCOUNT_ID`` per tenant).
        self._seen_installs: dict[tuple[str | None, str], None] = {}

    # ------------------------------------------------------------------
    # State-machine introspection — public for tests + dashboards.
    # ------------------------------------------------------------------

    @property
    def state(self) -> _WhatsAppSyncState:
        return self._state

    @property
    def active_sync(self) -> _ActiveSync | None:
        """Return a defensive copy of the active sync, or None."""
        if self._active_sync is None:
            return None
        return _ActiveSync(
            sync_id=self._active_sync.sync_id,
            trigger=self._active_sync.trigger,
            started_at=self._active_sync.started_at,
            channels=set(self._active_sync.channels),
            message_count=self._active_sync.message_count,
            earliest_ts=self._active_sync.earliest_ts,
            latest_ts=self._active_sync.latest_ts,
            last_message_at=self._active_sync.last_message_at,
        )

    # ------------------------------------------------------------------
    # ChannelAdapter Protocol implementations.
    # ------------------------------------------------------------------

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        """Validate WhatsApp credentials and return an AuthHandle.

        WhatsApp/Baileys uses runtime QR pairing, not OAuth. The
        ``account_id`` (a tenant-side identifier) is the minimum
        required to identify which paired credentials OpenClaw should
        use. The ``handle_id`` derives from ``account_id`` so the same
        WhatsApp account always resolves to the same handle.

        See ``infra/openclaw/WHATSAPP_PAIRING.md`` for the pairing
        flow operators run before the worm boots.
        """
        account_id = secrets.payload.get("account_id")
        if not account_id or not isinstance(account_id, str):
            raise ValueError(
                "whatsapp adapter requires {account_id: str} "
                "(see infra/openclaw/WHATSAPP_PAIRING.md for pairing)"
            )
        return AuthHandle(
            connector_kind="whatsapp",
            handle_id=account_id,
            extra={
                "account_id": account_id,
                # Tenant id is optional but threaded through for
                # multi-tenant deployments (the OpenClaw config keys
                # WHATSAPP_*_<TENANT> are tenant-scoped).
                "tenant_id": secrets.payload.get("tenant_id"),
            },
        )

    async def install(self, handle: AuthHandle) -> InstallRecord:
        """Mark this handle as installed.

        WhatsApp pairing is out-of-band: by the time we have an
        ``account_id``, the operator has already scanned the QR.
        ``install`` confirms the handle shape and returns an
        InstallRecord. Scopes are conceptual under Baileys (no OAuth
        scope model) — we record the policy-style capabilities the
        OpenClaw config grants us as scope tokens.
        """
        return InstallRecord(
            install_id=handle.handle_id,
            platform="whatsapp",
            scopes=["chat.read", "chat.send", "groups.read"],
            bot_user_id=None,  # WhatsApp accounts don't expose a bot id
            metadata={
                "transport": "baileys",
                "account_id": handle.extra.get("account_id"),
                "tenant_id": handle.extra.get("tenant_id"),
            },
        )

    async def listen(
        self, handle: AuthHandle
    ) -> AsyncIterator[InfraEvent]:
        """Yield InfraEvents.

        Production path: an external loop in
        ``apps/channel-adapter/service.py`` drives
        :class:`OpenClawLogTailer` and dispatches per-platform admit
        callbacks (Phase 4 dispatch table). The WhatsApp admit handler
        invokes :meth:`fetch_latest_and_normalize` directly, bypassing
        ``listen``. ``listen`` itself is provided here only for the
        Protocol contract and idles forever — same shape as Discord/
        Teams stub adapters.
        """
        while True:
            await asyncio.sleep(60)
        # Make this an async generator (unreachable yield satisfies
        # the AsyncIterator contract for the type checker).
        if False:  # pragma: no cover
            yield  # type: ignore[unreachable]

    async def send(
        self,
        handle: AuthHandle,
        channel: ChannelRef,
        msg: OutMessage,
    ) -> MessageRef:
        """Outbound send — rate-limited; OpenClaw CLI subprocess wired.

        **Wave C2 (2026-05-06).** The send wire goes through OpenClaw's
        bundled CLI: ``openclaw message send --channel whatsapp
        --target <jid> --message <text> --json``, executed via
        ``asyncio.create_subprocess_exec`` against ``docker exec`` into
        the gateway container. C1 discovery confirmed OpenClaw does
        not expose a plain HTTP send route; the WebSocket gateway is
        the only outbound transport, and the bundled CLI is the
        canonical Python-callable client. When upstream issue #73016
        lands the HTTP route, ``_do_send`` flips to a one-liner POST
        without changing the public surface here.

        **Rate limiter (Wave E2)** wraps ``_do_send`` automatically —
        the per-(tenant, bot) token bucket acquires before the
        subprocess invocation; on rate-limited responses (Baileys
        delivers via Backoff handlers, surfaced as
        :class:`RateLimitedError` in the future), the surrounding
        decorator backs off with jitter and exhausts after 3 retries
        with a ``policy_applied`` audit entry.

        **Argument fidelity vs Slack:**

        * ``msg.text`` flows through verbatim as the message body.
        * ``msg.blocks`` is Slack-only (Block Kit). WhatsApp has no
          equivalent shape; if non-empty, a warning is logged and the
          send proceeds with text only. (Future Wave D may add
          presentation JSON via ``--presentation``.)
        * ``msg.thread_ref`` carries no analogue on WhatsApp's flat
          conversation model. If set, a warning logs and the send
          proceeds without threading. (Reply-to is theoretically
          available via ``--reply-to``, but mapping a Slack thread_ts
          to a WhatsApp message id requires sender-side resolution
          we don't have at this layer.)
        * ``msg.files`` is Wave D scope. If non-empty, raises
          ``NotImplementedError`` per ship-honest posture.

        Returns a :class:`MessageRef` with the OpenClaw-issued
        ``platform_message_id`` extracted from the CLI's JSON output.
        """
        bot_phone = self._resolve_bot_phone_for_rate_limit(handle)
        tenant_id = self._tenant_id or handle.extra.get("tenant_id")
        # Build the rate-limited wrapper around _do_send. The wrapper
        # acquires a token from the per-(tenant, bot) bucket before
        # invoking _do_send; on RateLimitedError from _do_send (raised
        # by Wave C2's HTTP layer translating 429s), it retries with
        # exponential backoff; on exhaustion it emits a single
        # policy_applied entry per throttle session.
        wrapped = with_whatsapp_rate_limit(
            tenant_id=str(tenant_id) if tenant_id else None,
            bot_phone=bot_phone,
            policy_emitter=self._policy_emitter,
        )(self._do_send)
        return await wrapped(handle, channel, msg)

    async def _do_send(
        self,
        handle: AuthHandle,
        channel: ChannelRef,
        msg: OutMessage,
    ) -> MessageRef:
        """Inner send — OpenClaw CLI subprocess (Wave C2, 2026-05-06).

        Builds and runs::

            docker exec <container> openclaw message send \\
              --channel whatsapp \\
              --account <accountId> \\
              --target <jid> \\
              --message <text> \\
              --json [--token <gateway-token>]

        Parses the resulting JSON, extracts ``messageId`` (or
        ``payload.messageId``, or falls back to empty string for the
        Slack-symmetric Path-A contract), and returns a
        :class:`MessageRef`.

        **Honest behavior on missing infrastructure**:

        * ``WORMBASE_WHATSAPP_SEND_DISABLE`` truthy → raises
          ``NotImplementedError`` immediately (ops kill-switch).
        * ``docker`` binary missing in the channel-adapter container
          → ``FileNotFoundError`` propagates (clear signal that the
          container needs docker-host access OR the future HTTP
          route landing in #73016).
        * Subprocess exits non-zero → raises ``RuntimeError`` with
          stderr captured. The rate-limit decorator's
          :class:`RateLimitedError` mapping happens at this layer
          for "rate limited" / "429" / "Too Many Requests" markers
          in stderr; everything else propagates as a hard error.

        The ``msg.files`` non-empty case is Wave D scope and raises
        :class:`NotImplementedError` to make the gap visible
        (capability-honesty over silent drop).
        """
        # Ops kill-switch.
        if _truthy(os.environ.get("WORMBASE_WHATSAPP_SEND_DISABLE")):
            raise NotImplementedError(
                "WhatsApp outbound send is disabled by ops "
                "(WORMBASE_WHATSAPP_SEND_DISABLE truthy)."
            )
        # Files (media) — Wave D scope.
        if msg.files:
            raise NotImplementedError(
                "WhatsApp file_upload is not wired in v1 (Wave D scope). "
                "Re-enter when capability set includes 'file_upload'."
            )
        # blocks / thread_ref — log-and-proceed warnings; not errors.
        if msg.blocks:
            log.warning(
                "whatsapp send: msg.blocks present (Slack Block Kit); "
                "WhatsApp has no equivalent — sending text-only."
            )
        if msg.thread_ref:
            log.warning(
                "whatsapp send: msg.thread_ref=%r present; WhatsApp "
                "conversation model is flat — ignoring thread_ref.",
                msg.thread_ref,
            )

        container = os.environ.get(
            "WORMBASE_WHATSAPP_OPENCLAW_CONTAINER", "wormbase-openclaw",
        )
        token = os.environ.get("WORMBASE_WHATSAPP_OPENCLAW_TOKEN")
        account_id = (
            os.environ.get("WORMBASE_WHATSAPP_OPENCLAW_ACCOUNT")
            or handle.extra.get("account_id")
            or "default"
        )
        jid = channel.platform_channel_id

        argv: list[str] = [
            "docker", "exec", container,
            "openclaw", "message", "send",
            "--channel", "whatsapp",
            "--account", str(account_id),
            "--target", jid,
            "--message", msg.text or "",
            "--json",
        ]
        if token:
            argv.extend(["--token", token])

        # Run the subprocess.
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            # docker binary missing in this container — clearer error
            # than the bare FileNotFoundError stack the caller would see.
            raise RuntimeError(
                "WhatsApp send requires `docker` in PATH (or the future "
                "OpenClaw HTTP route from upstream issue #73016). The "
                "channel-adapter container is missing docker; deploy "
                "alongside the gateway with docker.sock mounted, or "
                "wait for the HTTP route to land."
            ) from None

        try:
            stdout_b, stderr_b = await proc.communicate()
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise

        stdout = (stdout_b or b"").decode("utf-8", errors="replace")
        stderr = (stderr_b or b"").decode("utf-8", errors="replace")

        if proc.returncode != 0:
            # Detect rate-limit-equivalent stderr patterns to surface as
            # RateLimitedError (the rate-limit decorator's retry hook).
            stderr_l = stderr.lower()
            if (
                "rate limit" in stderr_l
                or "too many requests" in stderr_l
                or "429" in stderr_l
                or "retry-after" in stderr_l
            ):
                from .whatsapp_rate_limit import RateLimitedError
                raise RateLimitedError(
                    f"openclaw message send rate-limited "
                    f"(rc={proc.returncode}): {stderr.strip()[:300]}"
                )
            raise RuntimeError(
                f"openclaw message send failed "
                f"(rc={proc.returncode}, container={container}, "
                f"jid={jid}): stderr={stderr.strip()[:500]} "
                f"stdout={stdout.strip()[:200]}"
            )

        # Parse JSON. CLI emits a single JSON object on success.
        platform_message_id = ""
        try:
            import json as _json
            data = _json.loads(stdout.strip()) if stdout.strip() else {}
        except (ValueError, TypeError):
            data = {}
        if isinstance(data, dict):
            mid = data.get("messageId")
            if not mid:
                payload = data.get("payload")
                if isinstance(payload, dict):
                    mid = payload.get("messageId")
            if isinstance(mid, str):
                platform_message_id = mid

        return MessageRef(
            platform="whatsapp",
            platform_message_id=platform_message_id or "",
            platform_channel_id=jid,
        )

    @staticmethod
    def _resolve_bot_phone_for_rate_limit(handle: AuthHandle) -> str:
        """Resolve the bot's E.164 phone for the rate-limit bucket key.

        Wraps :func:`resolve_whatsapp_bot_phone` (precedence:
        tenant-suffix → company-id-suffix → no-suffix fallback) and
        returns the bare phone — the rate-limit bucket key is
        ``<tenant>:<phone>``, not a jid.

        Falls back to a sentinel (``"_unknown_bot"``) when no env is set
        so the decorator can still be built and the call path still
        acquires a (per-anonymous-bot) token. The limiter must be on
        the path even pre-pairing for the test harness to verify wiring.
        Production setups always set the env.

        Adapter-side limitation: only ``tenant_id`` is in scope from
        ``handle.extra``; ``company_id`` is not threaded through. Path
        (1) and (3) of the resolver are active here; path (2) is unused.
        """
        tenant_id = handle.extra.get("tenant_id")
        phone = resolve_whatsapp_bot_phone(
            tenant_id=str(tenant_id) if tenant_id else None,
        )
        return phone or "_unknown_bot"

    async def list_workspace_members(
        self, handle: AuthHandle
    ) -> list[PlatformMember]:
        """Return [] honestly — WhatsApp has no workspace roster.

        WhatsApp's identity model is per-conversation: DMs surface a
        single peer jid; group metadata enumerates the participants of
        that one group. There's no global "workspace roster" surface
        equivalent to Slack's ``users.list``. Identity discovery for
        WhatsApp happens organically via inbound message attribution
        (each ``InfraEvent.platform_user_id`` triggers
        ``emit_person_proposed`` per the standard auto-discovery loop).
        """
        return []

    # ------------------------------------------------------------------
    # WhatsApp-specific path used by service.py
    # ------------------------------------------------------------------

    async def fetch_latest_and_normalize(
        self, handle: AuthHandle, channel_id: str,
    ) -> InfraEvent | None:
        """Fetch the latest message in a channel and normalize.

        Called by the OpenClaw-log capture path in service.py. The
        underlying fetch (``_fetch_message``) reaches OpenClaw's HTTP
        API; tests inject a synthetic message via ``inject_message``.

        The state machine classifies the message as ``push`` (live)
        or ``history_sync`` based on its ``platform_ts`` and the
        current state, and stamps the InfraEvent accordingly.

        Returns ``None`` when no message is available, the message
        is unrecoverable, or the message is the bot's own outbound
        echoing back through the wire (see :meth:`_is_echo`).
        """
        msg = await self._fetch_message(handle, channel_id)
        if msg is None:
            return None
        # Echo guard: drop our own bot's posts before they round-trip
        # through normalize. Mirrors Slack's bot-id self-echo guard
        # (slack.py:376-384). Defensive landing before Wave C wires
        # send — otherwise the first outbound would re-ingest as a
        # fresh inbound chat_received.
        if self._is_echo(msg, handle):
            return None
        return self._normalize_message(channel_id, msg)

    def inject_message(self, channel_id: str, msg: dict[str, Any]) -> None:
        """Test/sim hook: seed a message so ``_fetch_message`` returns it.

        Production code never calls this — the production fetch path
        hits OpenClaw's HTTP API. The fake path is required because
        the OpenClaw HTTP route shape for WhatsApp is unverified
        upstream; rather than fabricate an endpoint, we keep the real
        path behind ``_fetch_message`` and let tests drive it through
        injection.
        """
        self._last_msg[channel_id] = msg

    # ------------------------------------------------------------------
    # Sync state machine — public hooks for test + service drivers.
    # ------------------------------------------------------------------

    async def on_connection_open(
        self,
        *,
        trigger: Literal[
            "initial_connect", "reconnect", "channel_join"
        ] = "reconnect",
    ) -> None:
        """Flip IDLE → SYNC_IN_PROGRESS, and write Install on first pairing.

        Called by the service driver on OpenClaw ``connection_open``
        events (or whatever signal Baileys surfaces — empirically
        unverified). Idempotent: re-entering ``SYNC_IN_PROGRESS`` is
        a no-op (the existing active sync continues).

        Wave B3 (2026-05-06) extension: WhatsApp's pairing-complete
        signal IS this event (Baileys emits ``connection_open`` after a
        successful QR scan). On the FIRST call per
        ``(tenant_id, bot_jid)``, :meth:`_maybe_emit_install` invokes
        the injected ``install_emitter`` so an Install ledger entry
        lands. Subsequent ``connection_open`` events (creds preserved,
        just reconnecting) are no-ops via the in-process LRU; cache
        wraparound on restart is caught by the emitter's ledger fold.
        Slack's OAuth-grant Install path is unchanged — that flow lives
        in ``apps/worm-core`` and writes the install via
        ``write_actions.complete_install``; this hook only fires for
        WhatsApp.

        The install path runs BEFORE the state-machine transition so
        observers see install-then-sync, matching the production
        semantics ("we paired, then we started replaying history"). A
        failure inside the emitter is logged and swallowed; it does NOT
        block the state-machine transition (preserve Phase 3 invariant
        that ``connection_open`` always leaves the machine in a defined
        state).
        """
        # B3: install-detection runs before the state-machine flip.
        await self._maybe_emit_install()

        if self._state == _WhatsAppSyncState.SYNC_IN_PROGRESS:
            return
        if self._state == _WhatsAppSyncState.LIVE:
            # Live → reconnect path: close out the live state cleanly
            # and open a new sync. Treat as a reconnect transition.
            self._state = _WhatsAppSyncState.IDLE
        # IDLE → SYNC_IN_PROGRESS
        self._active_sync = _ActiveSync(
            sync_id=uuid4(),
            trigger=trigger,
            started_at=self._clock(),
        )
        self._state = _WhatsAppSyncState.SYNC_IN_PROGRESS
        log.info(
            "whatsapp sync started: sync_id=%s trigger=%s",
            self._active_sync.sync_id,
            trigger,
        )

    async def on_history_set(self) -> None:
        """Explicit completion signal from Baileys ``messaging-history.set``.

        If the platform surfaces this signal, we don't need the
        quiet-window heuristic — flip directly to LIVE and write the
        ``conversation_sync`` entry. Idempotent: safe to call from any
        state.
        """
        if self._state != _WhatsAppSyncState.SYNC_IN_PROGRESS:
            return
        await self._complete_sync(status="completed")

    async def on_connection_drop(self) -> None:
        """Flip any state → IDLE.

        If we drop mid-sync, the in-flight ``conversation_sync`` is
        marked ``status="interrupted"`` so downstream consumers can
        tell the difference between a clean completion and a partial
        replay. Idempotent: safe to call when already IDLE.
        """
        if self._state == _WhatsAppSyncState.SYNC_IN_PROGRESS:
            await self._complete_sync(status="interrupted")
        elif self._state == _WhatsAppSyncState.LIVE:
            self._state = _WhatsAppSyncState.IDLE
        # If IDLE, nothing to do.
        # Cancel any pending quiet timer.
        await self._cancel_quiet_timer()

    async def shutdown(self) -> None:
        """Cancel any in-flight quiet-window timer.

        Called on adapter teardown so the timer doesn't outlive the
        owning loop. Tests call this in their ``finally`` blocks.
        """
        await self._cancel_quiet_timer()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _is_echo(self, payload: dict[str, Any], handle: AuthHandle) -> bool:
        """Return True if ``payload`` is the bot's own message echoing back.

        Two detection paths, either fires:

        1. ``key.fromMe == True`` — Baileys' explicit flag for messages
           sent from the connected device. This is the canonical signal
           and works regardless of env configuration.
        2. Sender jid matches the bot's own jid. The bot's jid is
           constructed from a phone resolved via
           :func:`resolve_whatsapp_bot_phone` (precedence: tenant-
           suffix → company-id-suffix → no-suffix fallback). Tenant
           key is ``tenant_id`` from ``handle.extra``, upper-cased.
           If no env is set, this path no-ops and only ``key.fromMe``
           triggers the drop.

           Sender jid is resolved Baileys-canonically:
             * Group: ``key.participant`` (the actual sender within the group)
             * DM:    ``key.remoteJid`` (the peer, which equals the sender
                      for inbound; for self-echoes in DMs, this is the bot's
                      own jid because Baileys writes the to-jid into
                      remoteJid even for self-sent messages)

        Mirrors :mod:`wormbase_channel_adapters.slack`'s bot-id echo
        guard (slack.py:376-384) structurally — early-return None at
        the same call-site stage.
        """
        key = payload.get("key")
        if not isinstance(key, dict):
            # Malformed payload: defer to _normalize_message which also
            # tolerates a missing/empty key. No echo signal available,
            # so don't drop.
            return False

        # Path 1: explicit fromMe flag.
        if key.get("fromMe") is True:
            return True

        # Path 2: jid match. Requires bot phone env to be resolvable.
        bot_jid = self._resolve_bot_jid(handle)
        if bot_jid is None:
            return False

        sender_jid = key.get("participant") or key.get("remoteJid")
        if not isinstance(sender_jid, str):
            return False
        return sender_jid == bot_jid

    def _resolve_bot_jid(self, handle: AuthHandle) -> str | None:
        """Resolve the bot's own WhatsApp jid from env, scoped by tenant.

        Wraps :meth:`_resolve_bot_jid_for_tenant`, which itself wraps
        :func:`resolve_whatsapp_bot_phone` (precedence: tenant-suffix →
        company-id-suffix → no-suffix fallback). Tenant comes from
        ``handle.extra["tenant_id"]``; ``company_id`` is not threaded
        through the adapter surface, so path (2) of the resolver is
        unused at this call site.

        Returns ``None`` if no env value resolves — callers treat that
        as "we don't know our own jid, so no jid match can fire" and
        rely on ``key.fromMe`` alone.

        The phone is E.164 with no leading ``+`` (e.g. ``5511999999999``);
        the resolver strips any leading ``+`` defensively.
        """
        tenant_id = handle.extra.get("tenant_id")
        return self._resolve_bot_jid_for_tenant(tenant_id)

    def _resolve_bot_jid_for_tenant(
        self, tenant_id: str | None,
    ) -> str | None:
        """Resolve bot jid from env using a free-floating tenant_id.

        Wraps :func:`resolve_whatsapp_bot_phone` (precedence:
        tenant-suffix → company-id-suffix → no-suffix fallback) and
        formats the result as a WhatsApp jid. Used both by
        :meth:`_resolve_bot_jid` (which threads ``handle.extra["tenant_id"]``)
        and by :meth:`_maybe_emit_install` (which reaches here from
        ``on_connection_open`` where no ``AuthHandle`` is in scope).

        Adapter-side limitation: only ``tenant_id`` is in scope here;
        ``company_id`` is not threaded through the adapter surface, so
        path (2) of the resolver is unused at this call site. The
        precedence chain still accepts both today (so ops only set ONE
        env var), but the adapter-side resolution naturally lands on
        the tenant-suffix or no-suffix path.
        """
        phone = resolve_whatsapp_bot_phone(
            tenant_id=str(tenant_id) if tenant_id else None,
        )
        if phone is None:
            return None
        return f"{phone}@s.whatsapp.net"

    @property
    def seen_installs(self) -> set[tuple[str | None, str]]:
        """Inspectable install-detection LRU (test hook).

        Returns a defensive copy of the currently-cached
        ``(tenant_id, bot_jid)`` pairs. Public so tests + dashboards
        can verify the install-write path is exercised exactly once
        per pairing without reaching into ``_seen_installs``.
        """
        return set(self._seen_installs)

    def clear_seen_installs(self) -> None:
        """Drop the install-detection cache.

        Used by tests that simulate a fresh process boot (cache empty,
        ledger may already carry an install) to verify the emitter's
        ledger fold is the source of truth, not the in-process LRU.
        Production code never calls this.
        """
        self._seen_installs.clear()

    def _mark_install_seen(
        self, tenant_id: str | None, bot_jid: str,
    ) -> None:
        """Insert into the install-detection LRU; evict oldest at cap."""
        key: tuple[str | None, str] = (tenant_id, bot_jid)
        # Refresh insertion order on re-mark.
        if key in self._seen_installs:
            del self._seen_installs[key]
        elif len(self._seen_installs) >= self._SEEN_INSTALLS_MAX:
            self._seen_installs.pop(next(iter(self._seen_installs)))
        self._seen_installs[key] = None

    async def _maybe_emit_install(self) -> None:
        """Emit the Install ledger entry on first pairing per tenant+bot.

        Called from :meth:`on_connection_open`. WhatsApp's pairing-
        complete signal is precisely this event (Baileys emits
        ``connection_open`` after a successful QR scan); for OAuth
        platforms (Slack), Install is written elsewhere via
        ``write_actions.complete_install``.

        Idempotency contract:

        1. **In-process LRU** keyed by ``(tenant_id, bot_jid)`` — fast
           path. Subsequent ``connection_open`` events on a still-warm
           process are O(1) cache hits.
        2. **Emitter-side ledger fold** — the production emitter
           (``LedgerWriter.emit_whatsapp_install``) walks the ledger
           on every call and skips writing if a prior
           ``install_completed`` exists for the same tenant+platform+
           bot_user_id triple. This catches cold starts (cache empty
           after restart) and cache wraparound. The adapter's LRU is
           the fast path; the emitter is the source of truth.

        Graceful failure modes:

        * **No emitter wired** — log and skip. Tests instantiating the
          adapter without ``install_emitter`` (e.g. the existing
          state-machine tests) keep working byte-identical.
        * **No bot phone env resolvable** — log warning and skip
          without marking seen. We can't write an Install entry whose
          ``bot_user_id`` is empty; the next ``connection_open`` (after
          the operator sets the env) will retry. Mirrors A2's "don't
          mark seen on failure → retry on next admit" posture.
        * **Emitter raises** — log warning and skip without marking
          seen. Same retry posture. The state-machine transition that
          follows is unaffected.
        """
        emitter = self._install_emitter
        if emitter is None:
            return

        bot_jid = self._resolve_bot_jid_for_tenant(self._tenant_id)
        if bot_jid is None:
            log.warning(
                "whatsapp install detection: bot phone env unset "
                "(tenant_id=%r); skipping install write — set "
                "WORMBASE_WHATSAPP_BOT_PHONE_<tenant> or the global "
                "fallback WORMBASE_WHATSAPP_BOT_PHONE",
                self._tenant_id,
            )
            return

        cache_key: tuple[str | None, str] = (self._tenant_id, bot_jid)
        if cache_key in self._seen_installs:
            return

        try:
            await emitter(
                tenant_id=self._tenant_id,
                account_id=self._install_id,
                bot_jid=bot_jid,
                pairing_method="qr",
                paired_at=self._clock(),
                provider="openclaw_baileys",
                # Descriptive only — never credential material. The
                # OpenClaw mount path is canonical for the Baileys
                # transport in v1; future Meta Cloud API will surface
                # a different (or no) path here.
                creds_path=(
                    "/var/openclaw/whatsapp/baileys/"
                    f"{self._install_id or 'default'}/creds.json"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            # Don't mark seen on failure → next connection_open retries.
            log.warning(
                "whatsapp install_emitter failed (tenant_id=%r bot_jid=%s): %s",
                self._tenant_id, bot_jid, exc,
            )
            return

        self._mark_install_seen(self._tenant_id, bot_jid)
        log.info(
            "whatsapp install written: tenant_id=%r bot_jid=%s "
            "account_id=%s",
            self._tenant_id, bot_jid, self._install_id,
        )

    async def _fetch_message(
        self, handle: AuthHandle, channel_id: str,
    ) -> dict[str, Any] | None:
        """Fetch the latest message for ``channel_id``.

        Production target: ``GET http://openclaw:18789/api/whatsapp/
        conversations/<channel>/latest`` — **placeholder pending
        empirical verification** of OpenClaw's HTTP route shape (see
        issue #73016). Until verified, the real path is fed via
        :meth:`inject_message` from the test/sim layer; cached
        messages are returned at most once per channel per call so
        replays don't double-count.
        """
        cached = self._last_msg.pop(channel_id, None)
        if cached is not None:
            return cached
        # Production HTTP path would go here; until route is verified,
        # we return None so callers see a graceful no-op.
        return None

    def _normalize_message(
        self, channel_id: str, msg: dict[str, Any],
    ) -> InfraEvent | None:
        """Build an InfraEvent from a Baileys message dict.

        Baileys message shape (relevant fields):
        * ``key.id`` — message id
        * ``key.remoteJid`` — sender's jid for DMs, group jid otherwise
        * ``key.participant`` — actual sender's jid in groups (None in DMs)
        * ``message.conversation`` — plain-text body
        * ``message.extendedTextMessage.text`` — quoted/forwarded body
        * ``message.extendedTextMessage.contextInfo.mentionedJid`` — list
          of jids explicitly @-mentioned in the message body. Always a
          list (possibly empty) for WhatsApp messages; absent on bare
          ``conversation`` shapes.
        * ``messageTimestamp`` — Unix epoch (seconds, UTC)
        """
        platform_ts_raw = msg.get("messageTimestamp")
        platform_ts: datetime | None
        if platform_ts_raw is not None:
            try:
                platform_ts = datetime.fromtimestamp(
                    int(platform_ts_raw), tz=timezone.utc,
                )
            except (TypeError, ValueError, OverflowError):
                platform_ts = None
        else:
            platform_ts = None

        delivery_mode, history_sync_id = self._classify_message(
            channel_id, platform_ts,
        )

        # DM detection by jid suffix — Baileys/WhatsApp Web canonical
        # split: ``@s.whatsapp.net`` for individual chats, ``@g.us``
        # for group chats. The ``source`` field follows InfraEvent's
        # existing enum (``"dm"`` is the canonical DM tag).
        is_dm = channel_id.endswith("@s.whatsapp.net")
        source: Literal["dm", "channel_message"] = (
            "dm" if is_dm else "channel_message"
        )

        key = msg.get("key") or {}
        if not isinstance(key, dict):
            key = {}

        # Sender: in groups, key.participant is the actual sender jid;
        # in DMs, key.remoteJid is the peer (= sender).
        platform_user_id = key.get("participant") or key.get("remoteJid")
        platform_message_id = key.get("id")

        text = self._extract_text(msg)
        mentioned_jids = self._extract_mentioned_jids(msg)

        return InfraEvent(
            source=source,
            platform="whatsapp",
            platform_channel_id=channel_id,
            platform_user_id=platform_user_id,
            platform_message_id=platform_message_id,
            text=text,
            payload=msg,
            ts=self._clock(),
            company_id=None,
            channel_id=None,
            person_id=None,
            delivery_mode=delivery_mode,
            platform_ts=platform_ts,
            history_sync_id=history_sync_id,
            mentioned_jids=mentioned_jids,
        )

    @staticmethod
    def _extract_mentioned_jids(msg: dict[str, Any]) -> list[str]:
        """Pull the mentionedJid array out of a Baileys message dict.

        Reads the canonical Baileys nesting at
        ``message.extendedTextMessage.contextInfo.mentionedJid``.
        Defensive against every intermediate being missing or the wrong
        type — returns ``[]`` when no mentions are present (this is the
        WhatsApp-side convention vs ``None`` for non-WhatsApp adapters
        that never call this method).

        Filters non-string entries so a malformed payload can't smuggle
        non-jid values into the ledger.
        """
        message = msg.get("message") or {}
        if not isinstance(message, dict):
            return []
        ext = message.get("extendedTextMessage")
        if not isinstance(ext, dict):
            return []
        ctx_info = ext.get("contextInfo")
        if not isinstance(ctx_info, dict):
            return []
        jids = ctx_info.get("mentionedJid")
        if not isinstance(jids, list):
            return []
        return [j for j in jids if isinstance(j, str)]

    @staticmethod
    def _extract_text(msg: dict[str, Any]) -> str:
        """Pull the plain-text body out of a Baileys message dict.

        Baileys nests the body under one of several keys depending on
        the message subtype. We handle the two common cases — bare
        conversation and extended text — and fall back to "".
        """
        message = msg.get("message") or {}
        if not isinstance(message, dict):
            return ""
        conv = message.get("conversation")
        if isinstance(conv, str):
            return conv
        ext = message.get("extendedTextMessage")
        if isinstance(ext, dict):
            text = ext.get("text")
            if isinstance(text, str):
                return text
        return ""

    def _classify_message(
        self, channel_id: str, platform_ts: datetime | None,
    ) -> tuple[Literal["push", "history_sync"], str | None]:
        """Decide delivery_mode + history_sync_id for an inbound message.

        Drives the state machine forward as a side effect:

        * ``IDLE`` + message: defensively flip to SYNC_IN_PROGRESS
          (we missed the connection_open signal). Stamp as history_sync.
        * ``SYNC_IN_PROGRESS`` + message: stamp history_sync_id, accumulate.
        * ``LIVE`` + message: stamp push, history_sync_id=None.

        Side-effect: on every message arrival in SYNC_IN_PROGRESS,
        the quiet-window timer is cancelled and restarted (5s).
        """
        # Defensive: we shouldn't normally see messages while IDLE,
        # but if Baileys delivers history before connection_open fires
        # in our event ordering, treat the first arrival as the
        # implicit start of a sync session.
        if self._state == _WhatsAppSyncState.IDLE:
            self._active_sync = _ActiveSync(
                sync_id=uuid4(),
                trigger="reconnect",
                started_at=self._clock(),
            )
            self._state = _WhatsAppSyncState.SYNC_IN_PROGRESS
            log.info(
                "whatsapp sync auto-started (no connection_open seen): "
                "sync_id=%s",
                self._active_sync.sync_id,
            )

        if self._state == _WhatsAppSyncState.SYNC_IN_PROGRESS:
            assert self._active_sync is not None  # invariant
            now = self._clock()
            self._active_sync.channels.add(channel_id)
            self._active_sync.message_count += 1
            if platform_ts is not None:
                if (
                    self._active_sync.earliest_ts is None
                    or platform_ts < self._active_sync.earliest_ts
                ):
                    self._active_sync.earliest_ts = platform_ts
                if (
                    self._active_sync.latest_ts is None
                    or platform_ts > self._active_sync.latest_ts
                ):
                    self._active_sync.latest_ts = platform_ts
            self._active_sync.last_message_at = now
            # Reset the quiet-window timer on each arrival.
            self._restart_quiet_timer()
            return "history_sync", str(self._active_sync.sync_id)

        # LIVE state: push, no history_sync_id.
        return "push", None

    def _restart_quiet_timer(self) -> None:
        """Cancel any pending quiet-window task and start a fresh one.

        The task fires :meth:`_complete_sync` after
        ``_sync_quiet_window_s`` seconds with no further activity.
        """
        # Cancel previous timer if any.
        prev = self._quiet_timer_task
        if prev is not None and not prev.done():
            prev.cancel()
        # Start a new one.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — skip the timer; tests that drive this
            # without an event loop call _complete_sync directly.
            self._quiet_timer_task = None
            return
        self._quiet_timer_task = loop.create_task(
            self._quiet_timer_run(),
        )

    async def _quiet_timer_run(self) -> None:
        try:
            await asyncio.sleep(self._sync_quiet_window_s)
        except asyncio.CancelledError:
            return
        # Quiet-window elapsed; complete the sync.
        if self._state == _WhatsAppSyncState.SYNC_IN_PROGRESS:
            try:
                await self._complete_sync(status="completed")
            except Exception:  # noqa: BLE001
                log.exception(
                    "whatsapp _complete_sync raised on quiet-window fire"
                )

    async def _cancel_quiet_timer(self) -> None:
        task = self._quiet_timer_task
        self._quiet_timer_task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    async def _complete_sync(
        self,
        *,
        status: Literal["completed", "interrupted"],
    ) -> None:
        """Flip SYNC_IN_PROGRESS → LIVE (or IDLE on interrupt) and write entry.

        Writes the ``conversation_sync`` ledger entry with the
        accumulated bounds and resets state. If no ``sync_emitter`` was
        injected, the write is skipped (a warning logs); production
        always provides one.
        """
        if self._state != _WhatsAppSyncState.SYNC_IN_PROGRESS:
            return
        active = self._active_sync
        # Cancel timer first so it can't double-fire.
        await self._cancel_quiet_timer()
        # Reset state before writing so re-entry into the machine
        # during the await doesn't deadlock.
        self._active_sync = None
        self._state = (
            _WhatsAppSyncState.LIVE
            if status == "completed"
            else _WhatsAppSyncState.IDLE
        )

        if active is None:
            log.warning(
                "whatsapp _complete_sync called with no active sync; "
                "state was %s",
                self._state,
            )
            return

        completed_at = self._clock()
        if self._sync_emitter is None:
            log.info(
                "whatsapp sync %s: no sync_emitter wired, skipping ledger "
                "write (sync_id=%s, message_count=%d, status=%s)",
                "completed" if status == "completed" else "interrupted",
                active.sync_id,
                active.message_count,
                status,
            )
            return

        try:
            await self._sync_emitter(
                sync_id=active.sync_id,
                platform="whatsapp",
                install_id=self._install_id,
                channels=sorted(active.channels),
                trigger=active.trigger,
                started_at=active.started_at,
                completed_at=completed_at,
                message_count=active.message_count,
                earliest_ts=active.earliest_ts,
                latest_ts=active.latest_ts,
                status=status,
            )
            log.info(
                "whatsapp sync %s: sync_id=%s message_count=%d "
                "channels=%d",
                status,
                active.sync_id,
                active.message_count,
                len(active.channels),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "whatsapp _complete_sync ledger write failed: %s",
                exc,
            )


__all__ = ["WhatsAppChannelAdapter", "resolve_whatsapp_bot_phone"]
