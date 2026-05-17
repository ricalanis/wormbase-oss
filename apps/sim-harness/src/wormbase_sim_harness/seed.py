"""Real tenant seeding for ``wormbase demo seed``.

Provides ``seed_tenant`` — an idempotent async function that:

1. Resolves a stable ``company_id`` from a tenant slug (matches
   ``wormbase_core.service.tenant_to_uuid`` so worm-core, channel-adapter,
   and the sim harness all derive the same UUID).
2. Optionally clears prior ledger rows for that tenant via raw SQLAlchemy
   ``DELETE FROM ledger WHERE company_id = :cid``. The InMemoryLedger
   shim discards its in-process list directly when ``ledger.engine`` is
   missing.
3. Runs ``CompanyWarmup`` to seed domains, classifications, ontology and
   the initial knowledge-ramp gauges (one canonical PEVR cycle per
   domain plus a ``company_warmup_completed`` marker).

Historical chat seeding is intentionally NOT part of the default
``wormbase demo seed`` flow. Fresh tenants have no prior chat history;
that's the production-equivalent baseline. To replay a recorded set of
wire events through the production code path, use
``wormbase demo seed --replay-history <path/to/wire-record.jsonl>`` —
the JSONL is fed through the channel-adapter's wire-replay tool
(`apps/channel-adapter/src/wormbase_channel_adapter/wire_replay.py`)
which writes ``channel_adapter.emit_chat_received`` entries via the
exact same PEVR primitive the live wire uses. No bypass; deterministic
input through the real surface.

The legacy ``write_history=True`` direct-write path is preserved as
``write_history`` keyword for back-compat with existing tests, but it
defaults to ``False`` and is no longer reachable from the CLI without
an explicit override. Callers who need replayable chat history should
move to ``--replay-history``.

This module reuses ``CompanyWarmup`` and ``tenant_to_uuid`` rather than
reimplementing them — the wormbase-worm-core / wormbase-governance
packages are listed as workspace deps of the sim harness for exactly
this reason.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import text as _sql_text

from wormbase_core.lurker import SLACK_USER_NAMESPACE, slack_user_to_person
from wormbase_core.service import tenant_to_uuid
from wormbase_governance import CompanyWarmup
from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ledger.entries import ChatReceivedPayload
from wormbase_ontology_seed import Loader

logger = logging.getLogger("wormbase.sim.seed")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class SeedReport(BaseModel):
    """Outcome of a ``seed_tenant`` call."""

    tenant: str
    company_id: UUID
    domain_pack: str
    reset: bool = False
    rows_deleted: int = 0
    warmup_ran: bool = False
    warmup_already_warm: bool = False
    warmup_entries_written: int = 0
    history_entries_written: int = 0
    history_entries_skipped: int = 0
    history_days: int = 0
    # W7.A1 — set by the CLI (``cmd_seed``) when ``rich=True`` plumbs a
    # full Beat-9-ready enrichment through ``seed_rich`` after the
    # canonical persona seed lands. ``seed_tenant`` itself does not own
    # the rich phase (it has no HTTP context); the field is recorded
    # here so the ``SeedReport`` JSON dump surfaces what actually ran.
    rich: bool = False


# ---------------------------------------------------------------------------
# Beats — deterministic-by-construction Slack chatter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _HistoryBeat:
    """One simulated past-week Slack message; message_id is deterministic."""

    days_ago: int
    persona: str  # alice | bob | carol — matches personas.yml
    channel_id: str
    text: str

    @property
    def message_id(self) -> str:
        # Format chosen so a re-run (same beats) produces the same id.
        return f"seed:T-{self.days_ago}d:{self.persona}"


# 8 beats spanning T-7d ... T-1d. Realistic chatter that matches the
# personas in apps/sim-harness/personas.yml: alice (marketing, growth /
# retention), bob (data engineering, files), carol (CFO, revenue / unit
# economics). Topics cover quarterly close, sprint planning, customer
# interviews — matching the assignment's "realistic-sounding past Slack
# chatter" requirement.
#
# E5 note: the persona ids referenced below are *bot identities* in
# `personas.yml` — they tell ``slack_user_to_person`` how to synthesize
# a UUID5 sender_person for the chat-history fake. The canonical Person
# rows for the same humans live in the ledger via
# ``emit_person_proposed`` (see ``seed_personas`` and Block A1). The
# two paths converge: the UUIDs synthesized here match the
# ``platform_user_id`` values in ``CANONICAL_PERSONAS``, so any
# downstream join against the Person projection finds the same row.
_HISTORY_BEATS: tuple[_HistoryBeat, ...] = (
    _HistoryBeat(
        days_ago=7,
        persona="carol",
        channel_id="C_FINANCE",
        text=(
            "Heads up — quarterly close kicks off Monday. Need actuals "
            "vs forecast variance by EOD Friday."
        ),
    ),
    _HistoryBeat(
        days_ago=6,
        persona="alice",
        channel_id="C_GROWTH",
        text=(
            "Customer interview block landed — 8 power users next week. "
            "Going to ask about onboarding drop-off + retention triggers."
        ),
    ),
    _HistoryBeat(
        days_ago=5,
        persona="bob",
        channel_id="C_DATA",
        text=(
            "Pushed the new revenue rollup table; columns are documented "
            "in the README. Yell if the schema breaks anything."
        ),
    ),
    _HistoryBeat(
        days_ago=4,
        persona="alice",
        channel_id="C_GROWTH",
        text=(
            "Sprint planning thread — top of list is the activation funnel "
            "instrumentation gap. We're flying blind past step 3."
        ),
    ),
    _HistoryBeat(
        days_ago=3,
        persona="carol",
        channel_id="C_FINANCE",
        text=(
            "Quick one: what's our blended CAC trending at this quarter? "
            "Need the number for the board pre-read."
        ),
    ),
    _HistoryBeat(
        days_ago=2,
        persona="bob",
        channel_id="C_DATA",
        text=(
            "Backfill completed for the Q1 events; reconciliation matches "
            "Stripe to within $112 across the period. Filing the diff."
        ),
    ),
    _HistoryBeat(
        days_ago=2,
        persona="alice",
        channel_id="C_GROWTH",
        text=(
            "Customer interview takeaway: three of eight users mentioned "
            "they wished onboarding remembered prior context. Logging."
        ),
    ),
    _HistoryBeat(
        days_ago=1,
        persona="carol",
        channel_id="C_FINANCE",
        text=(
            "Forecast vs actual for ARR is +2.1% favorable. Net revenue "
            "retention 108%. Will flag unit-economics callouts in close."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def seed_tenant(
    *,
    ledger_dsn: str | None = None,
    ledger: Ledger | InMemoryLedger | None = None,
    tenant: str = "baseworm",
    domain_pack: str = "saas",
    reset_first: bool = False,
    write_history: bool = False,
    history_days: int = 7,
    seed_loader: Loader | None = None,
    now: datetime | None = None,
    rich: bool = False,
) -> SeedReport:
    """Seed a tenant for demo / pilot use.

    Either ``ledger_dsn`` or ``ledger`` must be supplied. Tests pass an
    ``InMemoryLedger`` directly; the CLI passes a DSN string. When a DSN
    is given a fresh ``Ledger`` is built and disposed before return.

    ``write_history`` defaults to ``False``. The historical chat-history
    direct-write path is retained for back-compat with existing tests
    (which exercise the dedupe / window-clipping logic) but is not
    surfaced by the production CLI. Use the CLI's ``--replay-history``
    flag instead — that drives the channel-adapter's wire-replay tool
    against a recorded JSONL, the production-equivalent way to fast-
    forward a tenant past the empty-channel state.

    ``rich`` (W7.A1) is a marker the CLI uses to gate the post-personas
    rich enrichment phase (KPI + role grants + decisions + process map +
    data product, written via the worm-core HTTP write API). The
    ``seed_tenant`` function itself only records the flag in the
    ``SeedReport`` — it has no HTTP context to drive the enrichment.
    The CLI's ``cmd_seed`` reads the flag back and conditionally calls
    ``seed_rich`` after personas are confirmed. See
    ``apps/sim-harness/src/wormbase_sim_harness/seed_rich.py`` for the
    enrichment surface.
    """
    if ledger is None and ledger_dsn is None:
        raise ValueError("seed_tenant requires either ledger or ledger_dsn")

    company_id = tenant_to_uuid(tenant)
    owns_ledger = ledger is None
    if ledger is None:
        assert ledger_dsn is not None  # for type-checkers
        ledger = Ledger(ledger_dsn)
    seed_loader = seed_loader or Loader()
    fixed_now = now or datetime.now(UTC)

    report = SeedReport(
        tenant=tenant,
        company_id=company_id,
        domain_pack=domain_pack,
        history_days=history_days,
        rich=rich,
    )

    try:
        # 1) Optional reset.
        if reset_first:
            report.rows_deleted = await _reset_tenant(ledger, company_id)
            report.reset = True
            logger.info(
                "reset tenant=%s company_id=%s rows_deleted=%d",
                tenant, company_id, report.rows_deleted,
            )

        # 2) Warmup — idempotent; CompanyWarmup short-circuits if a prior
        # `company_warmup_completed` marker exists for this tenant.
        before = len(await ledger.fetch(company_id))
        warmup = CompanyWarmup(ledger, seed_loader)
        warmup_report = await warmup.warmup(company_id, domain_pack)
        after = len(await ledger.fetch(company_id))
        report.warmup_ran = True
        report.warmup_already_warm = warmup_report.already_warm
        report.warmup_entries_written = max(0, after - before)

        # 3) Optional history.
        if write_history:
            written, skipped = await _write_history(
                ledger,
                company_id,
                fixed_now=fixed_now,
                history_days=history_days,
            )
            report.history_entries_written = written
            report.history_entries_skipped = skipped

        return report
    finally:
        if owns_ledger:
            try:
                # Ledger has dispose; InMemoryLedger does not.
                dispose = getattr(ledger, "dispose", None)
                if dispose is not None:
                    await dispose()
            except Exception as exc:  # noqa: BLE001
                logger.warning("ledger dispose failed: %s", exc)


# ---------------------------------------------------------------------------
# Reset helper
# ---------------------------------------------------------------------------


async def _reset_tenant(
    ledger: Ledger | InMemoryLedger, company_id: UUID,
) -> int:
    """Delete all ledger rows for ``company_id``. Returns rows deleted.

    Path A (real Postgres): raw SQLAlchemy ``DELETE`` against the
    ``ledger`` table via ``ledger.engine``. Bypasses the PEVR primitive
    on purpose — this is destructive admin, not a normal write.

    Path B (InMemoryLedger): clear the in-process list directly. The
    public API doesn't expose a delete; we touch ``_entries`` because
    no public method exists and the assignment explicitly authorizes
    this fallback.
    """
    engine = getattr(ledger, "engine", None)
    if engine is None:
        # InMemoryLedger path — no engine; clear in-memory rows.
        rows: dict[Any, list[Any]] | None = getattr(ledger, "_entries", None)
        if rows is None:
            return 0
        deleted = len(rows.get(company_id, []))
        rows[company_id] = []
        return deleted

    async with engine.begin() as conn:
        result = await conn.execute(
            _sql_text("DELETE FROM ledger WHERE company_id = :cid"),
            {"cid": company_id},
        )
        # rowcount may be -1 on some drivers; clamp to 0 in that case.
        return max(int(result.rowcount or 0), 0)


# ---------------------------------------------------------------------------
# History writer
# ---------------------------------------------------------------------------


async def _write_history(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    *,
    fixed_now: datetime,
    history_days: int,
) -> tuple[int, int]:
    """Write the simulated past-week chat_received entries.

    Idempotency: each beat carries a deterministic ``message_id`` of the
    form ``seed:T-{n}d:{persona}``. Before writing we fetch the existing
    ledger and skip any beat whose message_id already appears in an
    ``execute`` row tagged with one of the known chat_received tools.
    """
    # Build the existing-ids set so a re-run doesn't double-write.
    existing = await ledger.fetch(company_id)
    existing_ids: set[tuple[str, str]] = set()
    for row in existing:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        tool = payload.get("tool")
        if tool not in (
            "emit_chat_received",
            "channel_adapter.emit_chat_received",
            "sim-harness.seed.emit_chat_received",
        ):
            continue
        args = payload.get("args") or {}
        ch = args.get("channel_id") or ""
        mid = args.get("message_id") or ""
        if ch and mid:
            existing_ids.add((ch, mid))

    written = 0
    skipped = 0
    for beat in _HISTORY_BEATS:
        if beat.days_ago > history_days:
            # Outside the window — skip silently.
            continue
        if (beat.channel_id, beat.message_id) in existing_ids:
            skipped += 1
            continue

        sender_person = slack_user_to_person(beat.persona)
        # Sanity: that helper returns uuid5(SLACK_USER_NAMESPACE, persona)
        # which keeps the convention with the lurker / channel-adapter.
        assert sender_person  # appease type-checkers; uuid5 never None.
        _ = SLACK_USER_NAMESPACE  # imported so the constant is reachable

        try:
            payload_obj = ChatReceivedPayload(
                channel_id=beat.channel_id,
                message_id=beat.message_id,
                sender_person=sender_person,
                text=beat.text,
                classification="internal",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "seed history payload validation failed for %s: %s",
                beat.message_id, exc,
            )
            continue

        args = payload_obj.model_dump(mode="json")
        ts = fixed_now - timedelta(days=beat.days_ago)
        ref_id = uuid4()

        try:
            await ledger.write(
                company_id=company_id,
                propose={
                    "target_kind": "chat_received",
                    "ref_id": str(ref_id),
                    "reason": (
                        f"sim-harness seed history beat T-{beat.days_ago}d "
                        f"from {beat.persona}"
                    ),
                    "proposed_by": "sim-harness.seed",
                },
                execute_fn=lambda a=args, b=beat: {
                    "tool": "sim-harness.seed.emit_chat_received",
                    "args": a,
                    "result_ref": b.message_id,
                },
                verify_fn=lambda _r: {
                    "checks": [{"name": "payload_valid", "ok": True}],
                    "passed": True,
                },
                resolve_fn=lambda _v: {
                    "outcome": "keep",
                    "rationale": "seed history persisted",
                },
                timestamp=ts,
                quadrant="passive_probabilistic",
            )
            written += 1
            existing_ids.add((beat.channel_id, beat.message_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "seed history write failed for %s: %s", beat.message_id, exc,
            )

    return written, skipped


__all__ = ["SeedReport", "seed_tenant"]
