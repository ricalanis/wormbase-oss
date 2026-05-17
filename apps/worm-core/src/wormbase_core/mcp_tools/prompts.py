"""MCP prompt templates (J3).

Pre-baked prompt templates that AI clients can invoke. Each prompt
produces a structured message list mixing pulled context (KPIs,
decisions, etc.) with a templated instruction. They are user-curated
workflows in MCP terms — the user picks the prompt, the model executes.

For the demo arc, four prompts ship in this round:

1. ``summarize_company_state`` — KPIs + recent decisions + outstanding
   proposals → narrative summary.
2. ``audit_decision`` — H7 demo gold; walks decision → process → KPIs
   → source bytes for a single decision id.
3. ``whats_new_today`` — overnight digest pull (last 24h activity).
4. ``cfo_snapshot`` — per-position pre-baked query (CFO view).
5. ``cmo_snapshot`` — per-position pre-baked query (CMO view).
6. ``data_engineer_snapshot`` — per-position pre-baked query
   (data-engineer view).

Prompts return the canonical FastMCP shape: ``list[Message]`` where
each message is a ``{role, content}`` dict.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts.base import Message, UserMessage

from wormbase_core.mcp_tools.read_tools import (
    _fold_data_products,
    _fold_decisions,
    _fold_kpis,
    _fold_processes,
    _fold_recurring_questions,
    _fold_sources,
)
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger, Ledger

logger = logging.getLogger("wormbase_core.mcp_tools.prompts")

LedgerLike = Ledger | InMemoryLedger | Any

PROMPT_NAMES = (
    "summarize_company_state",
    "audit_decision",
    "whats_new_today",
    "cfo_snapshot",
    "cmo_snapshot",
    "data_engineer_snapshot",
)


def _bullet_list(items: list[str], limit: int = 10) -> str:
    if not items:
        return "(none)"
    return "\n".join(f"- {it}" for it in items[:limit])


async def _rows(ledger: LedgerLike, company_slug: str) -> list[dict[str, Any]]:
    return await ledger.fetch(tenant_to_uuid(company_slug))


def register_prompts(
    mcp: FastMCP,
    *,
    ledger: LedgerLike,
    api_token: str,  # noqa: ARG001
) -> None:
    """Register the prompt templates on the FastMCP instance."""

    @mcp.prompt(
        description="Summarize the current state of the company across KPIs, "
        "recent decisions, and outstanding proposals.",
    )
    async def summarize_company_state(company_id: str) -> list[Message]:
        rows = await _rows(ledger, company_id)
        kpis = _fold_kpis(rows, domain=None)
        recent_decisions = _fold_decisions(
            rows,
            since=datetime.now(tz=UTC) - timedelta(days=7),
            domain=None,
        )
        proposals = _fold_data_products(rows, kind=None, requested_by=None)
        outstanding = [p for p in proposals if p.get("status") == "proposed"]

        kpi_lines = [
            f"{k.get('name') or k.get('label') or k.get('id')}: "
            f"{k.get('formula') or '(no formula)'}"
            for k in kpis
        ]
        decision_lines = [
            f"{d.get('decision_text')} (ts={d.get('decision_at')})"
            for d in recent_decisions
        ]
        proposal_lines = [
            f"{p.get('name')} ({p.get('kind')})" for p in outstanding
        ]

        body = (
            f"You are summarising tenant `{company_id}`.\n\n"
            f"## KPIs\n{_bullet_list(kpi_lines)}\n\n"
            f"## Decisions (last 7 days)\n{_bullet_list(decision_lines)}\n\n"
            f"## Outstanding proposals\n{_bullet_list(proposal_lines)}\n\n"
            f"Write a concise (≤150 word) summary covering the headline "
            f"KPIs, decisions of note, and which proposals need admin "
            f"attention next."
        )
        return [UserMessage(body)]

    @mcp.prompt(
        description=(
            "Walk a decision back to its provenance: process map, KPIs "
            "affected, source bytes. The H7 demo beat made consumable by "
            "Claude Desktop."
        ),
    )
    async def audit_decision(
        company_id: str, decision_id: str,
    ) -> list[Message]:
        rows = await _rows(ledger, company_id)
        decisions = _fold_decisions(rows, since=None, domain=None)
        match = next(
            (d for d in decisions if d.get("decision_id") == decision_id),
            None,
        )
        if match is None:
            return [
                UserMessage(
                    f"No decision found for id `{decision_id}` in tenant "
                    f"`{company_id}`. Confirm the id and retry."
                )
            ]
        processes = _fold_processes(rows, domain=None)
        related_processes = [
            p for p in processes
            if any(
                step.get("source_message_id") in match.get("evidence_message_ids", [])
                for step in p.get("steps", [])
            )
        ]
        kpis = _fold_kpis(rows, domain=None)
        sources = _fold_sources(rows, kind=None, status=None)

        body = (
            f"Audit the following decision and produce a chain-of-custody "
            f"narrative.\n\n"
            f"## Decision\n"
            f"- id: `{match.get('decision_id')}`\n"
            f"- text: {match.get('decision_text')}\n"
            f"- ts: {match.get('decision_at')}\n"
            f"- evidence msg_ids: "
            f"{', '.join(match.get('evidence_message_ids', [])) or '(none)'}\n"
            f"- channel: {match.get('channel_id')}\n\n"
            f"## Related processes ({len(related_processes)})\n"
            f"{_bullet_list([p.get('process_name', '') for p in related_processes])}\n\n"
            f"## KPIs in scope ({len(kpis)})\n"
            f"{_bullet_list([k.get('name') or k.get('id') or '?' for k in kpis], limit=5)}\n\n"
            f"## Sources ({len(sources)})\n"
            f"{_bullet_list([s.get('uri', '') for s in sources], limit=5)}\n\n"
            f"Produce a 4-step audit narrative: (1) what was decided, "
            f"(2) which process embodies it, (3) which KPIs are affected, "
            f"(4) which source bytes ground it. Reference each fact by id."
        )
        return [UserMessage(body)]

    @mcp.prompt(
        description="Overnight digest: KPIs that moved, decisions taken, proposals waiting.",
    )
    async def whats_new_today(company_id: str) -> list[Message]:
        rows = await _rows(ledger, company_id)
        cutoff = datetime.now(tz=UTC) - timedelta(hours=24)
        recent_decisions = _fold_decisions(
            rows, since=cutoff, domain=None,
        )
        recent_kpis = _fold_kpis(rows, domain=None)
        proposals = _fold_data_products(rows, kind=None, requested_by=None)
        new_proposals = [p for p in proposals if p.get("status") == "proposed"]

        body = (
            f"Daily digest for `{company_id}` (last 24h).\n\n"
            f"## Decisions ({len(recent_decisions)})\n"
            f"{_bullet_list([d.get('decision_text', '') for d in recent_decisions])}\n\n"
            f"## KPI tree size\n- {len(recent_kpis)} nodes\n\n"
            f"## New proposals ({len(new_proposals)})\n"
            f"{_bullet_list([p.get('name', '') for p in new_proposals])}\n\n"
            f"Write a 5-bullet digest highlighting the most material "
            f"developments. Lead with the highest-impact item."
        )
        return [UserMessage(body)]

    # ---- Position snapshots ----------------------------------------

    async def _snapshot(
        company_id: str, position: str, focus_areas: str,
    ) -> list[Message]:
        rows = await _rows(ledger, company_id)
        kpis = _fold_kpis(rows, domain=None)
        decisions = _fold_decisions(rows, since=None, domain=None)
        questions = _fold_recurring_questions(rows)
        kpi_lines = [
            f"{k.get('name') or k.get('id')} = {k.get('formula') or '?'}"
            for k in kpis
        ]
        body = (
            f"Snapshot for the `{position}` position in tenant "
            f"`{company_id}`. Focus areas: {focus_areas}.\n\n"
            f"## KPIs ({len(kpis)})\n"
            f"{_bullet_list(kpi_lines)}\n\n"
            f"## Recent decisions ({len(decisions)})\n"
            f"{_bullet_list([d.get('decision_text', '') for d in decisions], limit=5)}\n\n"
            f"## Recurring questions ({len(questions)})\n"
            f"{_bullet_list([q.get('normalized_question', '') for q in questions], limit=5)}\n\n"
            f"Produce a position-specific 3-bullet snapshot focused on "
            f"{focus_areas}. Reference KPIs and decisions by id."
        )
        return [UserMessage(body)]

    @mcp.prompt(
        description="Pre-baked CFO snapshot: cash, runway, revenue, decisions affecting finance.",
    )
    async def cfo_snapshot(company_id: str) -> list[Message]:
        return await _snapshot(
            company_id,
            "CFO",
            "cash position, runway, revenue trajectory, and any finance-side decisions",
        )

    @mcp.prompt(
        description="Pre-baked CMO snapshot: pipeline, attribution, channel mix, decisions affecting marketing.",
    )
    async def cmo_snapshot(company_id: str) -> list[Message]:
        return await _snapshot(
            company_id,
            "CMO",
            "pipeline, channel attribution, conversion KPIs, and any marketing-side decisions",
        )

    @mcp.prompt(
        description="Pre-baked Data Engineer snapshot: source health, lake freshness, schema drift, recent ingest decisions.",
    )
    async def data_engineer_snapshot(company_id: str) -> list[Message]:
        return await _snapshot(
            company_id,
            "Data Engineer",
            "source health, ingest freshness, schema drift, and recent data-platform decisions",
        )


__all__ = [
    "PROMPT_NAMES",
    "register_prompts",
]
