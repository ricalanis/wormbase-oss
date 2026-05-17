"""SetupConversationLoop — orchestration of per-tenant onboarding (worm-core).

DM driver primitives lifted to ``wormbase_chat_presence.setup_dm_driver``
in Wave B (Task G3 / D4 spike s C6). This module retains the
orchestration loop + tenant-session bookkeeping + the
``wormbase_core.write_actions`` integration (the split is at the
``write_actions`` import line; everything above lifts, everything below
stays).

The worm DMs the installer in a connected chat platform and walks them
through a YAML-scripted setup conversation (``SetupScript`` lives in
chat-worm). Each answer writes the corresponding ledger entry — same
downstream effect as the wizard path.

Components:

* ``SetupScript`` — YAML-loaded dialogue (re-exported from chat-worm).
* ``SetupConversationLoop`` — long-lived asyncio task. Polls the ledger
  for tenants where ``setup_mode == 'bot'`` AND ``setup_completed_at``
  is null, and drives the conversation in their installer DM.

Algorithm per cycle (``run_once``):

1. Fold projection_installs to find tenants on the bot path that haven't
   completed setup.
2. For each: load the appropriate YAML (per the install's domain_pack
   hint, or saas-default if absent) into a SetupScript.
3. Read projection_setup_progress to find the cursor (current_step).
   - If null: post the first step's bot_says to the installer's DM.
   - Else: scan for new chat_received entries from the installer in
     the DM channel since the last_advance_seq; if any are present and
     match the current step's `expects` schema, fire the on_answer
     handler (writes the corresponding domain ledger entry) + advance
     the cursor.
4. Final step's on_answer is ``emit_setup_completed`` which terminates
   the conversation.

Slack-only for the v1 cut. Discord/Teams DM stay 'preview' (per the
capability-honesty pass) until v1.5; the loop treats non-Slack installs
as no-ops.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from wormbase_chat_presence.setup_dm_driver import (
    DmAdapter,
    ParsedAnswer,
    SetupScript,
    SetupStep,
    load_script,
    load_script_for_pack,
    parse_answer,
    parse_mentions,
)
from wormbase_ledger import InMemoryLedger, Ledger

from wormbase_core import write_actions

logger = logging.getLogger("wormbase_core.setup_conversation")


# ---------------------------------------------------------------------------
# SetupConversationLoop
# ---------------------------------------------------------------------------


@dataclass
class _TenantSession:
    tenant_id: UUID
    installer_person_id: UUID
    installer_platform_user_id: str
    platform: str
    pack: str
    script: SetupScript
    dm_channel_id: str | None = None
    last_advance_seq: int = 0
    completed: bool = False
    awaiting_step: str | None = None
    posted_step_ids: set[str] = field(default_factory=set)


class SetupConversationLoop:
    """Drive bot-path setup conversations across all bot-mode tenants."""

    def __init__(
        self,
        ledger: Ledger | InMemoryLedger,
        *,
        dm_adapter: DmAdapter,
        script_dir: Path | None = None,
        poll_interval_s: float = 5.0,
    ) -> None:
        self._ledger = ledger
        self._dm_adapter = dm_adapter
        self._script_dir = script_dir
        self._poll_interval_s = poll_interval_s
        # tenant_id → in-memory session bookkeeping. Survives across
        # cycles within one process; rebuilt from the ledger on restart.
        self._sessions: dict[UUID, _TenantSession] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run_forever(self) -> None:
        """Periodic loop wrapper. Cancel-safe."""
        logger.info(
            "setup_conversation starting: interval=%.1fs",
            self._poll_interval_s,
        )
        while True:
            try:
                n = await self.run_once()
                if n:
                    logger.info(
                        "setup_conversation advanced %d step%s",
                        n, "" if n == 1 else "s",
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("setup_conversation cycle failed: %s", exc)
            try:
                await asyncio.sleep(self._poll_interval_s)
            except asyncio.CancelledError:
                raise

    async def run_once(self) -> int:
        """Scan every bot-mode tenant; advance + DM as appropriate.

        Returns the count of conversation-step advances this cycle.
        """
        tenants = await self._discover_bot_tenants()
        advances = 0
        for entry in tenants:
            advances += await self._drive_tenant(entry)
        return advances

    # ------------------------------------------------------------------
    # Tenant discovery — fold the ledger to find bot-mode installs.
    # ------------------------------------------------------------------

    async def _discover_bot_tenants(self) -> list[_TenantSession]:
        """Walk every ledger entry once; pick out (tenant, install) pairs
        where setup_mode == 'bot' AND setup_completed_at IS NULL.

        Returns one session per such tenant. Pack defaults to 'saas' when
        the install row doesn't carry a domain_pack field (it doesn't yet
        — pack is a future column; for now the YAML defaults to saas).
        """
        # Fold per-company. The InMemoryLedger / Ledger fetch surfaces
        # are scoped to one company_id, so we need to enumerate. The
        # ``_known_companies`` helper isn't part of the Ledger Protocol;
        # we fall back to walking the in-memory dict for tests, and a
        # SQL DISTINCT for prod.
        companies = await self._enumerate_companies()
        sessions: list[_TenantSession] = []
        for cid in companies:
            session = await self._fold_tenant_session(cid)
            if session is not None and not session.completed:
                # Rehydrate seq cursor from existing in-memory session if any.
                prior = self._sessions.get(cid)
                if prior is not None:
                    session.dm_channel_id = (
                        prior.dm_channel_id or session.dm_channel_id
                    )
                    session.last_advance_seq = max(
                        prior.last_advance_seq, session.last_advance_seq,
                    )
                    session.posted_step_ids = (
                        prior.posted_step_ids | session.posted_step_ids
                    )
                self._sessions[cid] = session
                sessions.append(session)
        return sessions

    async def _enumerate_companies(self) -> list[UUID]:
        """List all company_ids the underlying ledger knows about.

        Two shapes supported:
          * InMemoryLedger.``_entries`` — dict[UUID, list[entry]]
          * production Ledger — would expose a ``list_companies`` method
            (TODO follow-up: add to the Ledger Protocol once the
            production loop wiring lands; for now the loop is Slack-only
            and tests use InMemoryLedger).
        """
        if hasattr(self._ledger, "list_companies"):
            return list(await self._ledger.list_companies())  # type: ignore[no-any-return]
        if hasattr(self._ledger, "_entries"):
            return list(self._ledger._entries.keys())  # type: ignore[no-any-return,attr-defined]
        return []

    async def _fold_tenant_session(
        self, company_id: UUID,
    ) -> _TenantSession | None:
        """Fold a tenant's ledger into a _TenantSession or None.

        Returns None when:
          - no install row exists,
          - setup_mode is not 'bot',
          - setup_completed has already fired,
          - the install platform isn't slack (Discord/Teams = preview).
        """
        rows = await self._ledger.fetch(company_id)
        installer_person_id: UUID | None = None
        installer_platform_user_id: str | None = None
        platform: str | None = None
        setup_mode: str | None = None
        completed = False
        last_advance_seq = 0
        last_step: str | None = None

        for r in rows:
            if r.get("kind") != "execute":
                continue
            payload = r.get("payload") or {}
            tool = payload.get("tool")
            args = payload.get("args") or {}
            if tool == "emit_install_completed":
                if str(args.get("platform")) == "slack":
                    platform = "slack"
                    iid = args.get("installer_person_id")
                    if iid:
                        installer_person_id = UUID(str(iid))
            elif tool == "emit_person_proposed":
                # Bind installer's platform_user_id (the person row written
                # for the installer carries it).
                pid = args.get("person_id")
                if (
                    installer_person_id is not None
                    and pid == str(installer_person_id)
                ):
                    pu = args.get("platform_user_id")
                    if pu and args.get("platform") == "slack":
                        installer_platform_user_id = str(pu)
            elif tool == "emit_setup_mode_chosen":
                setup_mode = str(args.get("mode") or "")
            elif tool == "emit_setup_completed":
                completed = True
            elif tool == "emit_setup_step_advanced":
                seq = int(r.get("seq", 0))
                if seq > last_advance_seq:
                    last_advance_seq = seq
                    last_step = str(args.get("step_id") or "")

        if (
            installer_person_id is None
            or installer_platform_user_id is None
            or platform != "slack"
            or setup_mode != "bot"
            or completed
        ):
            return None

        pack = "saas"  # TODO: read from install row metadata once available.
        script = load_script_for_pack(pack, script_dir=self._script_dir)
        sess = _TenantSession(
            tenant_id=company_id,
            installer_person_id=installer_person_id,
            installer_platform_user_id=installer_platform_user_id,
            platform=platform,
            pack=pack,
            script=script,
            last_advance_seq=last_advance_seq,
            awaiting_step=(
                script.next_after(last_step).id
                if last_step and script.next_after(last_step)
                else (last_step or script.first().id)
            ),
        )
        return sess

    # ------------------------------------------------------------------
    # Drive one tenant's conversation
    # ------------------------------------------------------------------

    async def _drive_tenant(self, sess: _TenantSession) -> int:
        """Advance ``sess`` by one step if possible.

        Returns 1 if an advance fired, 0 if we just posted the next
        question (waiting for the user) or there's nothing to do yet.
        """
        # Open the DM channel lazily.
        if sess.dm_channel_id is None:
            sess.dm_channel_id = await self._dm_adapter.open_dm(
                sess.installer_platform_user_id,
            )

        # If we haven't posted the awaiting_step's question yet, post it.
        step = sess.script.by_id(sess.awaiting_step or sess.script.first().id)
        if step is None:
            return 0
        if step.id not in sess.posted_step_ids:
            await self._dm_adapter.post_message(sess.dm_channel_id, step.bot_says)
            sess.posted_step_ids.add(step.id)
            return 0

        # Look for installer replies since the last advance.
        replies = await self._dm_adapter.fetch_replies(
            sess.dm_channel_id, since_seq=sess.last_advance_seq,
        )
        # Filter to messages from the installer.
        for reply in replies:
            sender = str(reply.get("platform_user_id") or "")
            if sender != sess.installer_platform_user_id:
                continue
            text = str(reply.get("text") or "")
            parsed = parse_answer(step, text)
            if not parsed.ok:
                # Re-prompt with the error so the user can retry.
                await self._dm_adapter.post_message(
                    sess.dm_channel_id,
                    f"Hmm — {parsed.error}. Try again?",
                )
                continue
            await self._handle_setup_answer(sess, step, parsed)
            return 1
        return 0

    async def _handle_setup_answer(
        self,
        sess: _TenantSession,
        step: SetupStep,
        answer: ParsedAnswer,
    ) -> None:
        """Apply ``step.on_answer`` + advance the cursor.

        Five recognised on_answer values map to ledger actions; the
        cursor advances either way (a parse-fail is rejected upstream).
        Final step writes emit_setup_completed and marks the session
        complete.
        """
        # 1. Side-effect: write the appropriate ledger entry.
        try:
            await self._dispatch_on_answer(sess, step, answer)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "setup_conversation on_answer %s failed for tenant %s: %s",
                step.on_answer, sess.tenant_id, exc,
            )
            return

        # 2. Cursor advance.
        await write_actions.advance_setup_step(
            self._ledger,
            sess.tenant_id,
            step_id=step.id,
            advanced_by_person_id=sess.installer_person_id,
        )

        # 3. Move to next step or finish.
        if step.on_answer == "emit_setup_completed":
            sess.completed = True
            return

        nxt = sess.script.next_after(step.id)
        if nxt is None:
            sess.completed = True
            return
        sess.awaiting_step = nxt.id
        # Do NOT pre-post the next question here; the next run_once
        # cycle will detect the unposted step and post it. This keeps
        # the loop's stateful surface exactly the posted-set.

    async def _dispatch_on_answer(
        self,
        sess: _TenantSession,
        step: SetupStep,
        answer: ParsedAnswer,
    ) -> None:
        """Translate a parsed answer into the canonical ledger entry."""
        handler = step.on_answer
        if handler == "emit_domain_registered_for_pack":
            # Treat ``answer.value`` as the pack name; pack registration
            # writes 4-N domain rows. Using the existing memory_written
            # tool as the audit-rail backing for now (worm-core's domain
            # vocabulary doesn't yet have an emit_domain_registered).
            await self._memory_log(
                sess,
                f"setup:domain_pack:{answer.value}",
                tags=["setup", "domain_pack", str(answer.value)],
            )
        elif handler == "emit_classification_default":
            await self._memory_log(
                sess,
                f"setup:classification_default:{answer.value}",
                tags=["setup", "classification_default", str(answer.value)],
            )
        elif handler == "parse_mentions_emit_role_assigned":
            mentions = parse_mentions(str(answer.value or ""))
            for mention in mentions:
                # Each mention becomes a memory_written audit row; the
                # identity_discovery loop later resolves and grants when
                # the mentioned user starts chatting in the workspace.
                await self._memory_log(
                    sess,
                    f"setup:invite_admin:{mention}",
                    tags=["setup", "invite_admin", mention],
                )
        elif handler == "emit_kpi_proposed":
            await self._memory_log(
                sess,
                f"setup:first_kpi:{answer.value}",
                tags=["setup", "first_kpi"],
            )
        elif handler == "emit_setup_completed":
            await write_actions.complete_setup(
                self._ledger, sess.tenant_id,
            )
            return
        else:
            logger.warning(
                "setup_conversation: unknown on_answer %s", handler,
            )

    async def _memory_log(
        self,
        sess: _TenantSession,
        content: str,
        *,
        tags: list[str],
    ) -> None:
        """Audit-write a memory_written row tied to setup answers.

        Bot-path answers land as memory_written entries until the
        production schema for emit_domain_registered / role_assigned via
        bot-conversation gets dedicated tools (worm-core domain vocab is
        currently dashboard-driven). The replay determinism gate (G8 /
        gate s) compares the SET of tools both paths emit; this keeps
        bot-side bookkeeping observable while avoiding a parallel write
        path that would diverge from the wizard's identity-form writes.
        """

        async def _propose() -> dict[str, Any]:
            return {
                "target_kind": "memory_written",
                "ref_id": str(sess.tenant_id),
                "reason": "setup_conversation answer",
                "proposed_by": "setup_conversation",
            }

        async def _execute() -> dict[str, Any]:
            return {
                "tool": "emit_memory_written",
                "args": {
                    "memory_id": str(uuid4()),
                    "content": content,
                    "tags": tags,
                },
                "result_ref": "setup",
            }

        async def _verify(_e: Any) -> dict[str, Any]:
            return {"checks": [{"name": "setup_memory", "ok": True}], "passed": True}

        async def _resolve(_v: Any) -> dict[str, Any]:
            return {"outcome": "keep", "rationale": "setup answer logged"}

        # InMemoryLedger.write expects sync callables; production Ledger
        # accepts both. Wrap in plain lambdas so both backends accept.
        await self._ledger.write(
            company_id=sess.tenant_id,
            propose=(await _propose()),
            execute_fn=lambda: {  # type: ignore[arg-type]
                "tool": "emit_memory_written",
                "args": {
                    "memory_id": str(uuid4()),
                    "content": content,
                    "tags": tags,
                },
                "result_ref": "setup",
            },
            verify_fn=lambda _e: {  # type: ignore[arg-type]
                "checks": [{"name": "setup_memory", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {  # type: ignore[arg-type]
                "outcome": "keep",
                "rationale": "setup answer logged",
            },
            quadrant="active_probabilistic",
        )


__all__ = [
    "DmAdapter",
    "ParsedAnswer",
    "SetupConversationLoop",
    "SetupScript",
    "SetupStep",
    "load_script",
    "load_script_for_pack",
    "parse_answer",
    "parse_mentions",
]
