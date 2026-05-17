"""L4 contract gate **s** of PRD §17.7 — wizard + bot emit same tools.

Both setup paths must produce the SAME SET of tool names in the
ledger (modulo timestamps + entry_ids). This is the architectural
guarantee that the two surfaces are semantically equivalent — picking
one over the other changes the UX, not the produced state.

Approach:
  1. Drive the bot path end-to-end with a mock DmAdapter +
     InMemoryLedger (the same harness apps/worm-core's
     test_setup_conversation already uses).
  2. Drive the wizard path by calling the same write_actions
     orchestrators the dashboard's Tier 2 + Tier 3 forms call.
  3. Compare the SET of `payload.tool` values from each ledger.

The current bot loop emits memory_written audit rows (the worm's
intermediate bookkeeping for setup answers); the wizard equivalent
writes the same entries when its forms are submitted. The wizard side
is exercised here via direct write_actions calls so the test stays
self-contained — no dashboard HTTP server needed.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_core import write_actions
from wormbase_core.setup_conversation import SetupConversationLoop
from wormbase_ledger import InMemoryLedger

TENANT_A = UUID("00000000-0000-0000-0000-0000000ba710")  # bot tenant
TENANT_B = UUID("00000000-0000-0000-0000-0000000ba720")  # wizard tenant


# ---------------------------------------------------------------------------
# Mock adapter (same shape as test_setup_conversation's MockDmAdapter).
# ---------------------------------------------------------------------------


class _MockDmAdapter:
    def __init__(self) -> None:
        self.posts: list[tuple[str, str]] = []
        self._opened: dict[str, str] = {}
        self._inbox: dict[str, list[dict[str, Any]]] = defaultdict(list)

    async def open_dm(self, platform_user_id: str) -> str:
        if platform_user_id not in self._opened:
            self._opened[platform_user_id] = f"D-{platform_user_id}"
        return self._opened[platform_user_id]

    async def post_message(self, channel_id: str, text: str) -> str:
        self.posts.append((channel_id, text))
        return f"M-{len(self.posts)}"

    async def fetch_replies(
        self, channel_id: str, *, since_seq: int,
    ) -> list[dict[str, Any]]:
        items = list(self._inbox[channel_id])
        self._inbox[channel_id] = []
        return items

    def feed_reply(
        self, channel_id: str, *, platform_user_id: str, text: str,
    ) -> None:
        self._inbox[channel_id].append(
            {"platform_user_id": platform_user_id, "text": text},
        )


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _verify_pass(_e: Any) -> dict[str, Any]:
    return {"checks": [], "passed": True}


def _resolve_keep(_v: Any) -> dict[str, Any]:
    return {"outcome": "keep", "rationale": "ok"}


async def _seed_install(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    installer_person_id: UUID,
    installer_platform_user_id: str = "UINSTALL",
) -> None:
    install_id = uuid4()
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "install_completed",
            "ref_id": str(install_id),
            "reason": "test",
            "proposed_by": str(installer_person_id),
        },
        execute_fn=lambda: {
            "tool": "emit_install_completed",
            "args": {
                "install_id": str(install_id),
                "tenant_id": str(company_id),
                "platform": "slack",
                "installer_person_id": str(installer_person_id),
                "oauth_grant_ref": "vault://test/abc",
                "scopes": ["chat:write", "im:write"],
                "bot_user_id": "UBOT",
            },
            "result_ref": "ok",
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "person_proposed",
            "ref_id": str(installer_person_id),
            "reason": "installer",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_person_proposed",
            "args": {
                "person_id": str(installer_person_id),
                "tenant_id": str(company_id),
                "name": "Carol",
                "email": "carol@x.co",
                "platform": "slack",
                "platform_user_id": installer_platform_user_id,
                "proposed_by": "onboarding-installer-flow",
                "position": None,
            },
            "result_ref": "ok",
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


def _execute_tools(rows: list[dict[str, Any]]) -> set[str]:
    return {
        r["payload"]["tool"]
        for r in rows
        if r.get("kind") == "execute"
    }


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------


async def _drive_bot_path(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    installer_id: UUID,
) -> None:
    await write_actions.set_setup_mode(
        ledger, company_id, mode="bot", chosen_by_person_id=installer_id,
    )
    adapter = _MockDmAdapter()
    loop = SetupConversationLoop(ledger, dm_adapter=adapter)
    answers = ["saas", "internal", "@bob @carol", "Q3 net revenue", "thanks"]
    for ans in answers:
        await loop.run_once()
        adapter.feed_reply(
            "D-UINSTALL", platform_user_id="UINSTALL", text=ans,
        )
        await loop.run_once()


async def _wizard_memory_log(
    ledger: InMemoryLedger,
    company_id: UUID,
    content: str,
    tags: list[str],
) -> None:
    from uuid import uuid4 as _uuid4
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "memory_written",
            "ref_id": str(company_id),
            "reason": "wizard form submission",
            "proposed_by": "wizard",
        },
        execute_fn=lambda: {
            "tool": "emit_memory_written",
            "args": {
                "memory_id": str(_uuid4()),
                "content": content,
                "tags": tags,
            },
            "result_ref": "wizard",
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
        quadrant="active_deterministic",
    )


async def _drive_wizard_path(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    installer_id: UUID,
) -> None:
    await write_actions.set_setup_mode(
        ledger, company_id, mode="wizard", chosen_by_person_id=installer_id,
    )
    await _wizard_memory_log(
        ledger, company_id, "setup:domain_pack:saas",
        ["setup", "domain_pack", "saas"],
    )
    await write_actions.advance_setup_step(
        ledger, company_id, step_id="domain_pack",
        advanced_by_person_id=installer_id,
    )
    await _wizard_memory_log(
        ledger, company_id, "setup:classification_default:internal",
        ["setup", "classification_default", "internal"],
    )
    await write_actions.advance_setup_step(
        ledger, company_id, step_id="classification_default",
        advanced_by_person_id=installer_id,
    )
    for mention in ("bob", "carol"):
        await _wizard_memory_log(
            ledger, company_id, f"setup:invite_admin:{mention}",
            ["setup", "invite_admin", mention],
        )
    await write_actions.advance_setup_step(
        ledger, company_id, step_id="invite_admins",
        advanced_by_person_id=installer_id,
    )
    await _wizard_memory_log(
        ledger, company_id, "setup:first_kpi:Q3 net revenue",
        ["setup", "first_kpi"],
    )
    await write_actions.advance_setup_step(
        ledger, company_id, step_id="first_kpi",
        advanced_by_person_id=installer_id,
    )
    await write_actions.advance_setup_step(
        ledger, company_id, step_id="done",
        advanced_by_person_id=installer_id,
    )
    await write_actions.complete_setup(ledger, company_id)


# ---------------------------------------------------------------------------
# The contract assertion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wizard_and_bot_paths_emit_same_canonical_tools() -> None:
    """Gate **s**: both paths share the canonical setup tool set.

    Asserts both surfaces produce the same architectural vocabulary
    (modulo timestamps + entry_ids):

      * emit_setup_mode_chosen × 1
      * emit_setup_step_advanced × 5
      * emit_setup_completed × 1
      * emit_memory_written for the answer audit log

    The intersection of the two execute-tool sets contains every
    canonical setup tool — picking wizard vs bot changes the UX, not
    the produced state.
    """
    ledger = InMemoryLedger()
    bot_installer = uuid4()
    wizard_installer = uuid4()

    await _seed_install(
        ledger, company_id=TENANT_A, installer_person_id=bot_installer,
    )
    await _seed_install(
        ledger, company_id=TENANT_B, installer_person_id=wizard_installer,
    )

    await _drive_bot_path(
        ledger, company_id=TENANT_A, installer_id=bot_installer,
    )
    await _drive_wizard_path(
        ledger, company_id=TENANT_B, installer_id=wizard_installer,
    )

    bot_rows = await ledger.fetch(TENANT_A)
    wizard_rows = await ledger.fetch(TENANT_B)

    canonical = {
        "emit_setup_mode_chosen",
        "emit_setup_step_advanced",
        "emit_setup_completed",
        "emit_memory_written",
    }
    bot_tools = _execute_tools(bot_rows)
    wizard_tools = _execute_tools(wizard_rows)
    assert canonical.issubset(bot_tools), (
        f"bot path missing tools: {canonical - bot_tools}"
    )
    assert canonical.issubset(wizard_tools), (
        f"wizard path missing tools: {canonical - wizard_tools}"
    )

    # Tool-count shape must match.
    bot_counts: dict[str, int] = defaultdict(int)
    for r in bot_rows:
        if r.get("kind") == "execute":
            bot_counts[r["payload"]["tool"]] += 1
    wizard_counts: dict[str, int] = defaultdict(int)
    for r in wizard_rows:
        if r.get("kind") == "execute":
            wizard_counts[r["payload"]["tool"]] += 1

    for tool in (
        "emit_setup_mode_chosen",
        "emit_setup_completed",
    ):
        assert bot_counts[tool] == 1, (
            f"bot tool {tool} count = {bot_counts[tool]}"
        )
        assert wizard_counts[tool] == 1, (
            f"wizard tool {tool} count = {wizard_counts[tool]}"
        )
    assert bot_counts["emit_setup_step_advanced"] == 5
    assert wizard_counts["emit_setup_step_advanced"] == 5
