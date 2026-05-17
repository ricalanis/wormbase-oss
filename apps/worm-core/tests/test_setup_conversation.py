"""SetupConversationLoop tests (Block G5 / PRD §17.5).

Covers the orchestration loop end-to-end with a mock DmAdapter and
InMemoryLedger. DM-driver primitive tests (YAML loader, parse_answer,
parse_mentions) live in
``packages/wormbase-chat-presence/tests/test_setup_dm_driver.py``
after the Wave-B / Task-G3 split (D4 spike s C6).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_core.setup_conversation import SetupConversationLoop
from wormbase_ledger import InMemoryLedger


# ---------------------------------------------------------------------------
# Loop end-to-end with a mock adapter + InMemoryLedger.
# ---------------------------------------------------------------------------


class MockDmAdapter:
    """Minimal in-memory DmAdapter for tests.

    Tracks every message the loop posts; lets the test inject installer
    replies via ``feed_reply``.
    """

    def __init__(self) -> None:
        self.posts: list[tuple[str, str]] = []  # (channel_id, text)
        self._opened: dict[str, str] = {}
        self._inbox: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._fetch_cursor: dict[str, int] = defaultdict(int)

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
        # Return queued replies for this channel; one shot, then drain.
        items = self._inbox[channel_id]
        out = list(items)
        self._inbox[channel_id] = []
        return out

    def feed_reply(
        self, channel_id: str, *, platform_user_id: str, text: str,
    ) -> None:
        self._inbox[channel_id].append(
            {
                "platform_user_id": platform_user_id,
                "text": text,
            },
        )


async def _seed_install_and_bot_mode(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    installer_person_id: UUID,
    installer_platform_user_id: str = "UINSTALL",
) -> None:
    """Drop the 3 ledger entries the loop expects to see for a tenant on
    the bot path: install_completed + person_proposed (installer) +
    setup_mode_chosen=bot.
    """

    def _verify_pass(_e: Any) -> dict[str, Any]:
        return {"checks": [], "passed": True}

    def _resolve_keep(_v: Any) -> dict[str, Any]:
        return {"outcome": "keep", "rationale": "ok"}

    # Install
    install_id = uuid4()
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "install_completed",
            "ref_id": str(install_id),
            "reason": "test seed",
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

    # Person proposed (installer with platform_user_id we'll DM)
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

    # Setup mode = bot
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "setup_mode_chosen",
            "ref_id": str(company_id),
            "reason": "T2",
            "proposed_by": str(installer_person_id),
        },
        execute_fn=lambda: {
            "tool": "emit_setup_mode_chosen",
            "args": {
                "tenant_id": str(company_id),
                "mode": "bot",
                "chosen_by_person_id": str(installer_person_id),
            },
            "result_ref": "ok",
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


@pytest.mark.asyncio
async def test_loop_posts_first_question_on_initial_run() -> None:
    ledger = InMemoryLedger()
    company_id = uuid4()
    installer_id = uuid4()
    await _seed_install_and_bot_mode(
        ledger,
        company_id=company_id,
        installer_person_id=installer_id,
    )

    adapter = MockDmAdapter()
    loop = SetupConversationLoop(ledger, dm_adapter=adapter)

    advances = await loop.run_once()
    assert advances == 0  # no answer yet — just posted the first question

    assert len(adapter.posts) == 1
    channel, text = adapter.posts[0]
    assert channel == "D-UINSTALL"
    assert "saas, marketplace, fintech, custom" in text


@pytest.mark.asyncio
async def test_loop_advances_on_valid_one_of_answer() -> None:
    ledger = InMemoryLedger()
    company_id = uuid4()
    installer_id = uuid4()
    await _seed_install_and_bot_mode(
        ledger,
        company_id=company_id,
        installer_person_id=installer_id,
    )

    adapter = MockDmAdapter()
    loop = SetupConversationLoop(ledger, dm_adapter=adapter)

    # Cycle 1: post first question.
    await loop.run_once()
    # Installer replies "saas".
    adapter.feed_reply("D-UINSTALL", platform_user_id="UINSTALL", text="saas")

    # Cycle 2: parse answer + advance.
    advances = await loop.run_once()
    assert advances == 1

    # Cycle 3: posts the next question.
    await loop.run_once()
    assert len(adapter.posts) == 2
    assert "internal or confidential" in adapter.posts[1][1]


@pytest.mark.asyncio
async def test_loop_re_prompts_on_invalid_answer() -> None:
    ledger = InMemoryLedger()
    company_id = uuid4()
    installer_id = uuid4()
    await _seed_install_and_bot_mode(
        ledger,
        company_id=company_id,
        installer_person_id=installer_id,
    )

    adapter = MockDmAdapter()
    loop = SetupConversationLoop(ledger, dm_adapter=adapter)

    await loop.run_once()  # post Q1
    adapter.feed_reply(
        "D-UINSTALL",
        platform_user_id="UINSTALL",
        text="not-a-pack-name",
    )
    advances = await loop.run_once()
    assert advances == 0  # invalid answer → no advance

    # Re-prompt was posted.
    assert len(adapter.posts) == 2
    assert "Try again" in adapter.posts[1][1]


@pytest.mark.asyncio
async def test_loop_completes_full_5_step_conversation() -> None:
    ledger = InMemoryLedger()
    company_id = uuid4()
    installer_id = uuid4()
    await _seed_install_and_bot_mode(
        ledger,
        company_id=company_id,
        installer_person_id=installer_id,
    )

    adapter = MockDmAdapter()
    loop = SetupConversationLoop(ledger, dm_adapter=adapter)

    answers = [
        "saas",  # domain_pack
        "internal",  # classification_default
        "@bob @carol",  # invite_admins
        "Q3 net revenue",  # first_kpi
        "thanks",  # done — any answer terminates
    ]

    for ans in answers:
        # Run a posting cycle (post next question).
        await loop.run_once()
        # Feed the answer.
        adapter.feed_reply(
            "D-UINSTALL",
            platform_user_id="UINSTALL",
            text=ans,
        )
        # Run an advancing cycle.
        await loop.run_once()

    # Verify setup_completed was written.
    rows = await ledger.fetch(company_id)
    tools = [
        r["payload"]["tool"]
        for r in rows
        if r.get("kind") == "execute"
    ]
    assert "emit_setup_completed" in tools
    # 5 step_advanced markers were also written.
    assert tools.count("emit_setup_step_advanced") == 5


@pytest.mark.asyncio
async def test_loop_skips_non_slack_installs() -> None:
    """Discord/Teams installs are 'preview'; the bot loop is Slack-only in v1."""
    ledger = InMemoryLedger()
    company_id = uuid4()
    installer_id = uuid4()

    # Seed a Discord install + bot mode.
    def _vp(_e: Any) -> dict[str, Any]:
        return {"checks": [], "passed": True}

    def _rk(_v: Any) -> dict[str, Any]:
        return {"outcome": "keep", "rationale": "ok"}

    install_id = uuid4()
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "install_completed",
            "ref_id": str(install_id),
            "reason": "discord install",
            "proposed_by": str(installer_id),
        },
        execute_fn=lambda: {
            "tool": "emit_install_completed",
            "args": {
                "install_id": str(install_id),
                "tenant_id": str(company_id),
                "platform": "discord",
                "installer_person_id": str(installer_id),
                "oauth_grant_ref": "vault://test/abc",
                "scopes": [],
                "bot_user_id": "UBOT",
            },
            "result_ref": "ok",
        },
        verify_fn=_vp,
        resolve_fn=_rk,
    )

    adapter = MockDmAdapter()
    loop = SetupConversationLoop(ledger, dm_adapter=adapter)

    advances = await loop.run_once()
    assert advances == 0
    assert len(adapter.posts) == 0


@pytest.mark.asyncio
async def test_loop_ignores_already_completed_tenant() -> None:
    ledger = InMemoryLedger()
    company_id = uuid4()
    installer_id = uuid4()
    await _seed_install_and_bot_mode(
        ledger,
        company_id=company_id,
        installer_person_id=installer_id,
    )

    # Write emit_setup_completed.
    def _vp(_e: Any) -> dict[str, Any]:
        return {"checks": [], "passed": True}

    def _rk(_v: Any) -> dict[str, Any]:
        return {"outcome": "keep", "rationale": "done"}

    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "setup_completed",
            "ref_id": str(company_id),
            "reason": "manual",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_setup_completed",
            "args": {
                "tenant_id": str(company_id),
                "completed_at": "2026-04-26T14:30:00+00:00",
            },
            "result_ref": "ok",
        },
        verify_fn=_vp,
        resolve_fn=_rk,
    )

    adapter = MockDmAdapter()
    loop = SetupConversationLoop(ledger, dm_adapter=adapter)

    advances = await loop.run_once()
    assert advances == 0
    assert len(adapter.posts) == 0
