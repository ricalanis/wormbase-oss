"""ScenarioEngine — beat-by-beat driver.

For each beat in order:
  1. ``await clock.advance_to(beat.at)`` — wait (wall) or jump (virtual).
  2. If ``improv``, ask the LLM to riff on ``say``; else use it verbatim.
  3. If ``drop``, upload the file (with caption) AND post the text body
     so the persona attribution is visible in the thread. If only ``say``,
     post that.
  4. If ``dm``, post the message in the persona-bot ↔ worm DM channel.
     The worm's bot user id is resolved via ``WORMBASE_AGENT_USER_ID``.
  5. If ``wait_for``, poll the ledger every 250ms until the named tool
     lands ``count`` times, or raise on timeout.

The harness writes nothing to the WormBase ledger — Path 3 (OpenClaw +
channel-adapter) handles capture deterministically. The engine only
talks to Slack and (for ``wait_for``) reads from the ledger.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from wormbase_sim_harness.clock import Clock
from wormbase_sim_harness.improv import ImprovEngine
from wormbase_sim_harness.personas import Persona, PersonaRegistry
from wormbase_sim_harness.scenario import Beat, Scenario, WaitFor
from wormbase_sim_harness.slack_poster import SlackPoster

log = logging.getLogger(__name__)


class _LedgerLike(Protocol):
    """The minimal Ledger surface ``wait_for`` needs."""

    async def fetch(  # pragma: no cover — Protocol
        self, company_id: UUID, until_ts: Any | None = None,
    ) -> list[dict[str, Any]]: ...


@dataclass
class BeatResult:
    """Telemetry for one executed beat."""

    index: int
    persona: str | None
    channel: str
    text: str | None
    file: str | None
    response: dict[str, Any] = field(default_factory=dict)
    kind: str = "post"  # post | upload | dm | wait_for


@dataclass
class RunReport:
    """Aggregated per-beat results returned by ``ScenarioEngine.run``."""

    scenario: str
    started_at_iso: str
    beats: list[BeatResult] = field(default_factory=list)


class ScenarioEngine:
    """Walks a scenario, dispatching to a SlackPoster on the chosen clock."""

    def __init__(
        self,
        registry: PersonaRegistry,
        *,
        improv: ImprovEngine | None = None,
        fixtures_root: str | Path | None = None,
        ledger: _LedgerLike | None = None,
        company_id: UUID | None = None,
        agent_user_id: str | None = None,
        wait_poll_interval_s: float = 0.25,
    ) -> None:
        self._registry = registry
        self._improv = improv
        self._fixtures_root = Path(fixtures_root) if fixtures_root else None
        self._ledger = ledger
        self._company_id = company_id
        # The worm's Slack user id is required to open a DM channel
        # between the persona-bot and the worm. Caller may pass it
        # explicitly; otherwise we read WORMBASE_AGENT_USER_ID.
        self._agent_user_id = (
            agent_user_id
            if agent_user_id is not None
            else os.environ.get("WORMBASE_AGENT_USER_ID", "").strip() or None
        )
        self._wait_poll_interval_s = wait_poll_interval_s

    def _resolve_file(self, declared: str) -> Path:
        p = Path(declared)
        if p.is_absolute():
            return p
        if self._fixtures_root is not None:
            return (self._fixtures_root / p).resolve()
        return p.resolve()

    async def _line_for(self, beat: Beat) -> str:
        seed = beat.say or ""
        if beat.improv and self._improv is not None and self._improv.enabled:
            try:
                persona = self._registry.get(beat.persona) if beat.persona else None
                if persona is None:
                    return seed
                return await self._improv.generate(persona, seed)
            except Exception as exc:  # noqa: BLE001
                log.info("improv generate failed; using seed: %s", exc)
                return seed
        return seed

    async def _resolve_dm_channel(self, poster: SlackPoster) -> str:
        """Open (or fetch) the persona-bot ↔ worm DM channel id.

        Slack's ``conversations.open`` is idempotent: calling it with the
        same user pair returns the same channel id. We therefore call it
        once per engine run (per worm user id). The bot user posting the
        DM is the persona bot — same auth as everything else.
        """
        if not self._agent_user_id:
            raise RuntimeError(
                "dm beat requires the worm's Slack user id; set "
                "WORMBASE_AGENT_USER_ID in the env or pass agent_user_id "
                "to ScenarioEngine"
            )
        client = poster.client
        resp = await client.conversations_open(users=self._agent_user_id)
        data = getattr(resp, "data", resp)
        if not isinstance(data, dict) or not data.get("ok"):
            raise RuntimeError(f"conversations.open failed: {data!r}")
        channel = (data.get("channel") or {}).get("id")
        if not channel:
            raise RuntimeError(f"conversations.open returned no channel id: {data!r}")
        return channel

    async def _wait_for_tool(self, spec: WaitFor) -> dict[str, Any]:
        """Poll the ledger until ``spec.tool`` has fired ``spec.count`` times.

        Returns telemetry: ``{tool, observed, deadline_remaining_s}``.
        Raises ``TimeoutError`` on miss.
        """
        if self._ledger is None or self._company_id is None:
            raise RuntimeError(
                "wait_for beats require a ledger + company_id wired into "
                "ScenarioEngine; got ledger=%r company_id=%r"
                % (self._ledger, self._company_id)
            )
        # Snapshot the row count at entry so we count NEW arrivals only —
        # otherwise pre-existing rows for the tool (e.g. from a prior
        # rehearsal in the same tenant) would satisfy the wait instantly.
        baseline = await self._count_tool(spec.tool)
        deadline = asyncio.get_event_loop().time() + spec.timeout_s
        while True:
            now_count = await self._count_tool(spec.tool)
            new_arrivals = now_count - baseline
            if new_arrivals >= spec.count:
                return {
                    "tool": spec.tool,
                    "observed": new_arrivals,
                    "required": spec.count,
                }
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise TimeoutError(
                    f"wait_for timed out after {spec.timeout_s}s waiting "
                    f"for tool={spec.tool!r} count={spec.count} "
                    f"(observed {new_arrivals} new arrivals; "
                    f"baseline={baseline}, current={now_count})"
                )
            await asyncio.sleep(min(self._wait_poll_interval_s, remaining))

    async def _count_tool(self, tool: str) -> int:
        """Count execute rows for ``tool`` in the current tenant."""
        assert self._ledger is not None
        assert self._company_id is not None
        rows = await self._ledger.fetch(self._company_id)
        n = 0
        for row in rows:
            if row.get("kind") != "execute":
                continue
            payload = row.get("payload") or {}
            if payload.get("tool") == tool:
                n += 1
        return n

    async def run(
        self,
        scenario: Scenario,
        clock: Clock,
        poster: SlackPoster,
        *,
        channel_resolver: Callable[[str], str] | None = None,
    ) -> RunReport:
        """Execute every beat in order; return per-beat telemetry."""
        scenario.validate_against(self._registry)

        await clock.start()
        report = RunReport(
            scenario=scenario.name,
            started_at_iso=clock.started_at().isoformat(),
        )
        channel_raw = scenario.default_channel
        channel = channel_resolver(channel_raw) if channel_resolver else channel_raw

        for i, beat in enumerate(scenario.beats):
            await clock.advance_to(beat.at)

            # --- wait_for (engine-driven; no persona) -----------------
            if beat.wait_for is not None:
                # mypy: scenario validator coerces str -> WaitFor.
                spec = beat.wait_for
                assert isinstance(spec, WaitFor)
                wait_result = await self._wait_for_tool(spec)
                report.beats.append(
                    BeatResult(
                        index=i,
                        persona=None,
                        channel=channel,
                        text=None,
                        file=None,
                        response=wait_result,
                        kind="wait_for",
                    )
                )
                continue

            assert beat.persona is not None  # validator guarantees this
            persona: Persona = self._registry.get(beat.persona)
            text = await self._line_for(beat)

            # --- dm (persona DMs the worm) ----------------------------
            if beat.dm is not None:
                dm_channel = await self._resolve_dm_channel(poster)
                resp = await poster.post_as(persona, dm_channel, beat.dm.text)
                report.beats.append(
                    BeatResult(
                        index=i,
                        persona=beat.persona,
                        channel=dm_channel,
                        text=beat.dm.text,
                        file=None,
                        response=resp,
                        kind="dm",
                    )
                )
                continue

            # --- drop (file upload, optionally with say follow-up) ----
            if beat.drop is not None:
                file_path = self._resolve_file(beat.drop.file)
                upload_resp = await poster.upload_as(
                    persona,
                    channel,
                    file_path,
                    caption=beat.drop.caption,
                )
                follow_resp: dict[str, Any] = {}
                if beat.say:
                    follow_resp = await poster.post_as(persona, channel, text)
                report.beats.append(
                    BeatResult(
                        index=i,
                        persona=beat.persona,
                        channel=channel,
                        text=beat.say,
                        file=str(file_path),
                        response={"upload": upload_resp, "post": follow_resp},
                        kind="upload",
                    )
                )
                continue

            # --- plain say --------------------------------------------
            resp = await poster.post_as(persona, channel, text)
            report.beats.append(
                BeatResult(
                    index=i,
                    persona=beat.persona,
                    channel=channel,
                    text=text,
                    file=None,
                    response=resp,
                    kind="post",
                )
            )

        return report


__all__ = ["ScenarioEngine", "BeatResult", "RunReport"]
