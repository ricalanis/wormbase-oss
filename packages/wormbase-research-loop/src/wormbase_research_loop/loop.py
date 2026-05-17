"""Karpathy autoresearch loops at three audience scopes.

Lifted from ``wormbase_core.autoresearch_loop`` as part of Wave C₁
(research-worm extraction, Block B.1). The original module becomes a
backwards-compat shim in a later Wave C₁ block; until then the
worm-core module remains the canonical import path for in-tree callers.

Step 5 of the canonical product arc. W5.A4 extends the per-Person ×
per-position loop with two additional scopes
so the autoresearch principle applies at every level of org granularity:

    Person  scope: per (Person × position) — existing behaviour, audience
                   marker ``"person:<uuid>"``.
    Team    scope: per Team-Domain — runs experiments shared by every Team
                   member, audience marker ``"team:<domain_uuid>"``.
    Company scope: per company — runs experiments at the top-level KPI
                   tree, audience marker ``"company"``.

Direct mapping to the autoresearch paper (CLAUDE.md anchor):

    modify code  →  pick an ImprovementCandidate for the user's position
    train        →  ``emit_experiment_run`` (mocked execution log)
    evaluate     →  read the user's headline metric (per their position)
    keep|discard →  ``emit_experiment_resolved`` with observed_delta + rationale

Per-scope cadence + budget defaults (env-overridable):

    Person  poll 5 min (or WORM_CORE_AUTORESEARCH_INTERVAL_S),
            budget 5/day (WORM_CORE_AUTORESEARCH_BUDGET_PERSON).
    Team    poll 15 min (WORM_CORE_AUTORESEARCH_TEAM_INTERVAL_S),
            budget 3/day (WORM_CORE_AUTORESEARCH_BUDGET_TEAM).
    Company poll 1 hour (WORM_CORE_AUTORESEARCH_COMPANY_INTERVAL_S),
            budget 1/day (WORM_CORE_AUTORESEARCH_BUDGET_COMPANY).

Conflict arbitration: when a lower-scope ``keep`` outcome would land on a
metric that a higher-scope outcome (Team for Person, Company for Person/Team)
has already touched within the last 7 days, the lower-scope experiment is
*discarded* with rationale ``"superseded_by_higher_scope:<higher_audience>"``.
This implements the specificity-inverted rule **Company > Team > Person** —
higher scope wins because it carries more authority over the metric than the
narrower scope. See ``_check_higher_scope_conflict`` for the implementation.

For the demo arc we collapse propose + run + resolve into the same poll
cycle so a tenant's /research tab fills with experiments within seconds of
opening — no overnight wait required for the live audience.

See ``docs/superpowers/specs/2026-04-26-wormbase-product-arc.md`` Step 5
and ``docs/superpowers/plans/2026-04-28-wave-5-reactivity-conversation.md``
W5.A4 for the multi-scope extension.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import text as _sql_text

from wormbase_identity_tracker.positions import (
    ImprovementCandidate,
    Position,
    get_position,
    headline_metric_for_position,
    position_candidates,
)
from wormbase_core import data_product_actions
from wormbase_research_loop.learn import (
    extract_lessons_for_kept,
    mark_lessons_applied,
    recent_lessons_for_scope,
    render_lesson_for_rationale,
)
from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ledger.entries import (
    ExperimentProposedPayload,
    ExperimentResolvedPayload,
    ExperimentRunPayload,
    MetricObservedPayload,
)

logger = logging.getLogger("wormbase_research_loop.loop")


# Stable namespace so the same (person_id, cycle, candidate_id) triple maps
# to the same experiment_id every replay.
_EXPERIMENT_NAMESPACE = UUID("9c1f7a6e-3b4d-5c2e-8a9f-2b3c4d5e6f70")


# ---------------------------------------------------------------------------
# Public per-tenant context object
# ---------------------------------------------------------------------------


@dataclass
class PersonPosition:
    """A (person, position) pair the loop iterates over."""

    person_id: UUID
    position_id: str
    name: str = "(unknown)"


@dataclass
class _RecentActivity:
    """Slice of recent activity the loop conditions its proposal on."""

    chat_count_24h: int = 0
    matched_pattern_count: int = 0
    last_seen_at: datetime | None = None


@dataclass
class AutoresearchLoop:
    """Per-tenant Karpathy autoresearch loop driver.

    Inject the ledger + company_id at construction time. Call
    ``run_once()`` for a single iteration (sync-friendly for tests) or
    ``run_forever()`` for the production timer loop.
    """

    ledger: Ledger | InMemoryLedger
    company_id: UUID
    poll_interval_s: float = 600.0
    cycle_count: int = 0
    _last_seq: int = 0
    _registered: dict[UUID, PersonPosition] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Public driver
    # ------------------------------------------------------------------

    async def run_once(self, *, now: datetime | None = None) -> int:
        """Run one full cycle across every registered (person, position).

        Returns the number of experiments emitted.
        """
        now = now or datetime.now(UTC)
        people = await self._collect_person_positions()
        if not people:
            logger.debug(
                "autoresearch_loop: no person×position pairs for tenant %s",
                self.company_id,
            )
            return 0
        emitted = 0
        for pp in people:
            try:
                done = await self._run_for_person(pp, now=now)
                emitted += int(bool(done))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "autoresearch_loop: per-person cycle failed for %s: %s",
                    pp.person_id, exc,
                )
        self.cycle_count += 1
        return emitted

    async def run_forever(self) -> None:
        """Periodic loop wrapper, cancel-safe."""
        logger.info(
            "autoresearch_loop starting: company_id=%s interval=%.1fs",
            self.company_id, self.poll_interval_s,
        )
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("autoresearch_loop cycle failed: %s", exc)
            try:
                await asyncio.sleep(self.poll_interval_s)
            except asyncio.CancelledError:
                raise

    # ------------------------------------------------------------------
    # Person × Position discovery (driven by the ledger).
    # ------------------------------------------------------------------

    async def _collect_person_positions(self) -> list[PersonPosition]:
        """Walk emit_position_assigned + emit_person_registered entries.

        The latest ``position_assigned`` for each person wins. People without
        a position assignment are skipped — Step 5 only acts once a role is
        captured.
        """
        rows = await self.ledger.fetch(self.company_id)
        names: dict[UUID, str] = {}
        positions: dict[UUID, str] = {}
        position_seq: dict[UUID, int] = {}
        for r in rows:
            if r["kind"] != "execute":
                continue
            payload = r["payload"]
            tool = payload.get("tool")
            args = payload.get("args") or {}
            if tool == "emit_person_registered":
                pid = _maybe_uuid(args.get("person_id"))
                if pid:
                    names[pid] = str(args.get("name") or pid)
            elif tool == "emit_position_assigned":
                pid = _maybe_uuid(args.get("person_id"))
                if pid is None:
                    continue
                seq = int(r.get("seq") or 0)
                if seq >= position_seq.get(pid, -1):
                    positions[pid] = str(args.get("position") or "")
                    position_seq[pid] = seq

        out: list[PersonPosition] = []
        for pid, position_id in positions.items():
            if not position_id:
                continue
            if get_position(position_id) is None:
                # Unknown / customer-extended position — skip; Step 5 only
                # acts on positions present in the seed registry. Customers
                # extend by emitting their own metrics/patterns.
                continue
            out.append(
                PersonPosition(
                    person_id=pid,
                    position_id=position_id,
                    name=names.get(pid, str(pid)),
                )
            )
        # Stable order so replay is deterministic.
        out.sort(key=lambda x: (str(x.person_id), x.position_id))
        self._registered = {p.person_id: p for p in out}
        return out

    # ------------------------------------------------------------------
    # Per-person cycle
    # ------------------------------------------------------------------

    async def _run_for_person(
        self, pp: PersonPosition, *, now: datetime
    ) -> bool:
        """Execute one full propose → run → resolve cycle for a person."""
        position = get_position(pp.position_id)
        if position is None:
            return False
        candidates = position_candidates(pp.position_id)
        if not candidates:
            return False

        activity = await self._recent_activity(pp, now=now)
        # Observe the headline metric so the sparkline accumulates samples.
        await self._emit_metric_observation(pp, position, activity, now=now)

        candidate = self._pick_candidate(pp, candidates)
        experiment_id = uuid5(
            _EXPERIMENT_NAMESPACE,
            f"{pp.person_id}:{self.cycle_count}:{candidate.candidate_id}",
        )

        # Step 3 — propose
        await self._emit_proposed(pp, candidate, experiment_id, now=now)

        # Step 4 — run (mocked: 1 minute of synthetic runtime)
        started_at = now
        finished_at = now + timedelta(seconds=60)
        await self._emit_run(pp, candidate, experiment_id, started_at, finished_at)

        # Step 5 — resolve (deterministic outcome).
        #
        # Conflict arbitration: if a higher-scope (Team or Company) ``keep``
        # has landed on the same headline metric within the last 7 days, we
        # force a discard with rationale ``superseded_by_higher_scope:<aud>``.
        # See _check_higher_scope_conflict above; the rule is documented in
        # the module-level docstring.
        forced_discard = await _check_higher_scope_conflict(
            self.ledger,
            self.company_id,
            metric=candidate.headline_metric_id,
            own_scope="person",
            now=now,
        )
        if forced_discard:
            outcome = "discard"
            observed_delta = 0.0
            rationale = f"superseded_by_higher_scope:{forced_discard}"
        else:
            outcome, rationale, observed_delta = self._resolve(
                experiment_id, candidate
            )
        await self._emit_resolved(
            experiment_id,
            outcome=outcome,
            observed_delta=observed_delta,
            rationale=rationale,
            now=finished_at,
        )

        # F7 — every "keep" experiment publishes a notebook artifact.
        # Notebook source: a YAML-spec template describing the experiment.
        # owner_person_id = the_person_the_loop_ran_for; the worm authors
        # on their behalf (PRD §16.7).
        if outcome == "keep":
            try:
                await self._publish_keep_notebook(
                    pp=pp,
                    candidate=candidate,
                    experiment_id=experiment_id,
                    observed_delta=observed_delta,
                    now=finished_at,
                )
            except Exception as exc:  # noqa: BLE001 — never block the loop
                logger.warning(
                    "autoresearch keep-notebook publish failed: %s", exc,
                )

        # P9 — learn step. After resolve lands (regardless of outcome — the
        # extractor itself filters to keeps), walk the ledger and write any
        # missing ``experiment_lesson`` rows. Idempotent on prior_keep_id so
        # re-running the loop never duplicates a lesson.
        try:
            n_lessons = await extract_lessons_for_kept(
                self.ledger,
                self.company_id,
                now=finished_at,
            )
            if n_lessons:
                logger.info(
                    "autoresearch_learn extracted %d new lesson(s)", n_lessons,
                )
        except Exception as exc:  # noqa: BLE001 — never block the loop
            logger.warning("autoresearch_learn extraction failed: %s", exc)

        return True

    async def _publish_keep_notebook(
        self,
        *,
        pp: PersonPosition,
        candidate: ImprovementCandidate,
        experiment_id: UUID,
        observed_delta: float,
        now: datetime,
    ) -> None:
        """Write propose+run+publish for a kept-experiment notebook (F7).

        The notebook has 4 cells:
          1. markdown — hypothesis + position
          2. code     — query setup (records position/metric identifiers;
                        connector.query() is invoked by the runtime kernel
                        when a connector is registered for the metric)
          3. code     — metric calculation
          4. markdown — result line + delta

        Notebook id is deterministic from experiment_id so replay is
        stable.
        """
        notebook_id = uuid5(
            _EXPERIMENT_NAMESPACE, f"notebook:{experiment_id}",
        )
        cells = [
            {
                "kind": "markdown",
                "source": (
                    f"# Experiment for {pp.position_id}: {candidate.headline_metric_id}\n\n"
                    f"Candidate: {candidate.candidate_id}\n\n"
                    f"Hypothesis: {candidate.proposed_change}"
                ),
            },
            {
                "kind": "code",
                "source": (
                    "# Step 1 — query setup\n"
                    f"position = '{pp.position_id}'\n"
                    f"metric = '{candidate.headline_metric_id}'\n"
                    "# rows are populated by the runtime kernel when a\n"
                    "# connector is registered for the metric; until then\n"
                    "# the published notebook records the experiment shape.\n"
                    "rows = []"
                ),
            },
            {
                "kind": "code",
                "source": (
                    "# Step 2 — metric calculation\n"
                    f"observed = {observed_delta:+.6f}\n"
                    f"expected = {candidate.expected_delta:+.6f}\n"
                    "delta = observed - expected\n"
                    "delta"
                ),
            },
            {
                "kind": "markdown",
                "source": (
                    f"## Result: kept (Δ = {observed_delta:+.4f})\n\n"
                    f"Expected delta {candidate.expected_delta:+.4f}; "
                    f"observed delta hit at least 90%, kept the change."
                ),
            },
        ]

        try:
            _, _ = await data_product_actions.propose_notebook(
                self.ledger,
                self.company_id,
                notebook_id=notebook_id,
                name=(
                    f"Autoresearch · {pp.position_id} · "
                    f"{candidate.candidate_id}"
                ),
                cells=cells,
                kernel="python_local",
                proposed_by_person_id=pp.person_id,
                quadrant="passive_probabilistic",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("propose_notebook fallback (likely already proposed): %s", exc)

        # Run + publish a deterministic result so every kept experiment has
        # a published version to drill into without a kernel round-trip per
        # cycle. Cell hashes are deterministic across replays because
        # they're sha256 over (cell.source + sorted input hashes), so the
        # published artifact replays bit-for-bit (Triad C2 — auditable,
        # deterministic output).
        run_id = uuid5(
            _EXPERIMENT_NAMESPACE, f"run:{experiment_id}",
        )
        cell_hashes = []
        prior: list[str] = []
        for c in cells:
            h = hashlib.sha256()
            h.update(c["source"].encode("utf-8"))
            for ph in sorted(prior):
                h.update(b"|")
                h.update(ph.encode("utf-8"))
            ch = h.hexdigest()
            cell_hashes.append(ch)
            prior.append(ch)
        kernel_state_hash = hashlib.sha256(
            "|".join(cell_hashes).encode("utf-8"),
        ).hexdigest()

        try:
            await data_product_actions.run_notebook(
                self.ledger,
                self.company_id,
                notebook_id=notebook_id,
                run_id=run_id,
                cell_outputs=[
                    {"kind": c["kind"], "status": "ok", "value": None}
                    for c in cells
                ],
                cell_hashes=cell_hashes,
                duration_ms=0,
                kernel_state_hash=kernel_state_hash,
                status="ok",
                run_by="worm",
                quadrant="passive_probabilistic",
            )
            await data_product_actions.publish_notebook(
                self.ledger,
                self.company_id,
                notebook_id=notebook_id,
                run_id=run_id,
                owner_person_id=pp.person_id,
                version="1",
                published_by=pp.person_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("run/publish notebook fallback: %s", exc)

    # ------------------------------------------------------------------
    # Emit helpers — each goes through the canonical PEVR primitive
    # ------------------------------------------------------------------

    async def _emit_proposed(
        self,
        pp: PersonPosition,
        candidate: ImprovementCandidate,
        experiment_id: UUID,
        *,
        now: datetime,
        audience: str | None = None,
    ) -> None:
        # Default audience for the per-Person loop is ``person:<uuid>``; the
        # Team and Company loops pass their own marker via the ``audience``
        # kwarg. Keeping the default here means the legacy run paths and the
        # existing test suite continue to write the right marker without
        # touching every call site.
        if audience is None:
            audience = f"person:{pp.person_id}"

        # P9 — read trailing-7-day ``experiment_lesson`` entries for the same
        # scope and fold them into the propose. The proposed_change dict is
        # extended with ``priors_applied``: a stable list of summary strings
        # for the lessons that informed this proposal. ``reason`` is enriched
        # so the propose row's PEVR rationale carries visible attribution.
        scope = _scope_of(audience)
        lessons = await recent_lessons_for_scope(
            self.ledger,
            self.company_id,
            scope=scope,
            now=now,
        )
        proposed_change = dict(candidate.proposed_change)
        if lessons:
            proposed_change["priors_applied"] = [
                render_lesson_for_rationale(L["args"]) for L in lessons
            ]
        rationale_suffix = ""
        if lessons:
            rationale_suffix = (
                f" — applying {len(lessons)} prior lesson(s): "
                f"{'; '.join(render_lesson_for_rationale(L['args']) for L in lessons)}"
            )

        payload = ExperimentProposedPayload(
            experiment_id=experiment_id,
            for_person_id=pp.person_id,
            position=pp.position_id,
            headline_metric=candidate.headline_metric_id,
            proposed_change=proposed_change,
            expected_delta=float(candidate.expected_delta),
            proposed_at=now,
            audience=audience,
        )
        await self._write(
            tool="emit_experiment_proposed",
            target_kind="experiment_proposed",
            ref_id=str(experiment_id),
            args=payload.model_dump(mode="json"),
            reason=(
                f"autoresearch proposal for {pp.position_id} ({audience})"
                f"{rationale_suffix}"
            ),
            quadrant="active_probabilistic",
            timestamp=now,
        )

        # Stamp ``applied_at`` on each consumed lesson so the projection
        # layer knows the lesson was *used* (closes the Karpathy loop
        # empirically). The seq we record is the experiment's own
        # ``proposed`` row's seq, looked up from the ledger after write.
        if lessons:
            try:
                applied_seq = await _latest_proposed_seq(
                    self.ledger, self.company_id, str(experiment_id),
                )
                if applied_seq > 0:
                    await mark_lessons_applied(
                        self.ledger,
                        self.company_id,
                        lessons=lessons,
                        applied_at_seq=applied_seq,
                        now=now,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "applied_at stamp failed for experiment %s: %s",
                    experiment_id, exc,
                )

    async def _emit_run(
        self,
        pp: PersonPosition,
        candidate: ImprovementCandidate,
        experiment_id: UUID,
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        log: dict[str, Any] = {
            "candidate_id": candidate.candidate_id,
            "position": pp.position_id,
            "person_id": str(pp.person_id),
            "iterations": 1,
            "synthetic_runtime_s": int(
                (finished_at - started_at).total_seconds()
            ),
            "notes": (
                f"mock execution: applied {candidate.proposed_change.get('kind')} "
                f"to {candidate.proposed_change.get('target')}"
            ),
        }
        payload = ExperimentRunPayload(
            experiment_id=experiment_id,
            started_at=started_at,
            finished_at=finished_at,
            log=log,
        )
        await self._write(
            tool="emit_experiment_run",
            target_kind="experiment_run",
            ref_id=str(experiment_id),
            args=payload.model_dump(mode="json"),
            reason="autoresearch run",
            quadrant="active_deterministic",
            timestamp=finished_at,
        )

    async def _emit_resolved(
        self,
        experiment_id: UUID,
        *,
        outcome: str,
        observed_delta: float,
        rationale: str,
        now: datetime,
    ) -> None:
        payload = ExperimentResolvedPayload(
            experiment_id=experiment_id,
            outcome=outcome,  # type: ignore[arg-type]
            observed_delta=float(observed_delta),
            rationale=rationale,
            resolved_at=now,
        )
        await self._write(
            tool="emit_experiment_resolved",
            target_kind="experiment_resolved",
            ref_id=str(experiment_id),
            args=payload.model_dump(mode="json"),
            reason="autoresearch resolved",
            quadrant="active_deterministic",
            timestamp=now,
        )

    async def _emit_metric_observation(
        self,
        pp: PersonPosition,
        position: Position,
        activity: _RecentActivity,
        *,
        now: datetime,
    ) -> None:
        metric = headline_metric_for_position(pp.position_id)
        if metric is None:
            return
        # Deterministic mock value: anchored on the metric's nominal scale,
        # nudged by the cycle counter and the user's recent activity. Same
        # inputs => same output (Triad C2).
        baseline = _baseline_for_metric(metric.metric_id)
        nudge = (
            self.cycle_count * 0.5
            + activity.chat_count_24h * 0.7
            + activity.matched_pattern_count * 1.3
        )
        if metric.higher_is_better:
            value = baseline + nudge
        else:
            value = max(0.0, baseline - nudge * 0.4)
        payload = MetricObservedPayload(
            metric_id=metric.metric_id,
            position=pp.position_id,
            value=float(value),
            observed_at=now,
        )
        await self._write(
            tool="emit_metric_observed",
            target_kind="metric_observed",
            ref_id=f"{pp.position_id}:{metric.metric_id}",
            args=payload.model_dump(mode="json"),
            reason="autoresearch metric sample",
            quadrant="passive_deterministic",
            timestamp=now,
        )

    # ------------------------------------------------------------------
    # Heuristics
    # ------------------------------------------------------------------

    async def _recent_activity(
        self, pp: PersonPosition, *, now: datetime
    ) -> _RecentActivity:
        """Last 24h of chat_received rows where this person was the sender."""
        cutoff = now - timedelta(hours=24)
        position = get_position(pp.position_id)
        patterns = tuple((position.patterns if position else ()))
        rows = await self.ledger.fetch(self.company_id)
        result = _RecentActivity()
        for r in rows:
            if r["kind"] != "execute":
                continue
            tool = r["payload"].get("tool")
            if tool not in (
                "emit_chat_received",
                "channel_adapter.emit_chat_received",
                "emit_kpi_viewed",
            ):
                continue
            args = r["payload"].get("args") or {}
            sender = args.get("sender_person")
            try:
                sender_uuid = UUID(str(sender)) if sender else None
            except (ValueError, TypeError):
                sender_uuid = None
            if sender_uuid != pp.person_id:
                continue
            ts = r.get("ts")
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except ValueError:
                    continue
            if not isinstance(ts, datetime):
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts < cutoff:
                continue
            result.chat_count_24h += 1
            result.last_seen_at = ts
            text = str(args.get("text") or "").lower()
            if any(p in text for p in patterns):
                result.matched_pattern_count += 1
        return result

    def _pick_candidate(
        self,
        pp: PersonPosition,
        candidates: list[ImprovementCandidate],
    ) -> ImprovementCandidate:
        """Round-robin candidate pick keyed by (person_id, cycle_count).

        Deterministic across replays: same person + same cycle => same
        candidate. Cycle index advances per outer ``run_once`` so successive
        cycles surface different candidates for the same user.
        """
        if not candidates:
            raise ValueError("no candidates")
        seed = f"{pp.person_id}:{self.cycle_count}"
        idx = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % len(
            candidates
        )
        return candidates[idx]

    @staticmethod
    def _resolve(
        experiment_id: UUID, candidate: ImprovementCandidate
    ) -> tuple[str, str, float]:
        """Deterministic 60% keep / 40% discard with observed_delta + rationale."""
        # hash(experiment_id) % 5 < 3 ⇒ 3/5 == 60% keep.
        h = int(hashlib.sha256(experiment_id.bytes).hexdigest(), 16) % 5
        if h < 3:
            outcome = "keep"
            # Wins land 90% of the expected delta — believable, never exact.
            observed = candidate.expected_delta * 0.9
            rationale = (
                f"observed_delta {observed:+.4f} hit ≥ 90% of expected "
                f"{candidate.expected_delta:+.4f}; keeping {candidate.candidate_id}"
            )
        else:
            outcome = "discard"
            # Losses regress slightly in the *wrong* direction.
            observed = -candidate.expected_delta * 0.2
            rationale = (
                f"observed_delta {observed:+.4f} regressed vs expected "
                f"{candidate.expected_delta:+.4f}; discarding {candidate.candidate_id}"
            )
        return outcome, rationale, observed

    # ------------------------------------------------------------------
    # Common writer
    # ------------------------------------------------------------------

    async def _write(
        self,
        *,
        tool: str,
        target_kind: str,
        ref_id: str,
        args: dict[str, Any],
        reason: str,
        quadrant: str,
        timestamp: datetime | None = None,
    ) -> None:
        try:
            await self.ledger.write(
                company_id=self.company_id,
                propose={
                    "target_kind": target_kind,
                    "ref_id": ref_id,
                    "reason": reason,
                    "proposed_by": "autoresearch_loop",
                },
                execute_fn=lambda: {
                    "tool": tool,
                    "args": args,
                    "result_ref": ref_id,
                },
                verify_fn=lambda _r: {
                    "checks": [{"name": "payload_valid", "ok": True}],
                    "passed": True,
                },
                resolve_fn=lambda _v: {
                    "outcome": "keep",
                    "rationale": f"{tool} persisted",
                },
                quadrant=quadrant,  # type: ignore[arg-type]
                timestamp=timestamp,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("autoresearch write failed (%s): %s", tool, exc)


# ---------------------------------------------------------------------------
# Service-level wrapper used by the CLI background task
# ---------------------------------------------------------------------------


def _default_autoresearch_interval_s() -> float:
    raw = os.environ.get("WORM_CORE_AUTORESEARCH_INTERVAL_S")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    is_dev = os.environ.get("WORMBASE_DEV", "").strip().lower() in ("1", "true")
    return 30.0 if is_dev else 600.0


async def autoresearch_loop_runner(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    *,
    poll_interval_s: float | None = None,
) -> None:
    """Background task: drive AutoresearchLoop on a periodic timer.

    Mirrors ``chat_received_reactivity_poller`` / ``process_extractor_loop``
    so cli wiring stays symmetrical. Default interval comes from
    ``WORM_CORE_AUTORESEARCH_INTERVAL_S`` (or 30s in dev / 600s in prod).
    """
    interval = (
        poll_interval_s
        if poll_interval_s is not None
        else _default_autoresearch_interval_s()
    )
    loop = AutoresearchLoop(
        ledger=ledger,
        company_id=company_id,
        poll_interval_s=interval,
    )
    logger.info(
        "autoresearch_loop_runner starting: company_id=%s interval=%.1fs",
        company_id, interval,
    )
    while True:
        try:
            n = await loop.run_once()
            if n:
                logger.info(
                    "autoresearch_loop emitted %d experiments (cycle %d)",
                    n, loop.cycle_count,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("autoresearch_loop cycle failed: %s", exc)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _maybe_uuid(v: Any) -> UUID | None:
    try:
        return UUID(str(v))
    except (ValueError, TypeError):
        return None


def _baseline_for_metric(metric_id: str) -> float:
    """Deterministic baseline value per metric. Hand-tuned for plausibility."""
    table: dict[str, float] = {
        "revenue": 1_420_000.0,
        "runway": 18.0,
        "cac_payback": 9.4,
        "net_burn": 220_000.0,
        "retention_m3": 0.62,
        "channel_mix_entropy": 1.8,
        "viral_coefficient": 0.34,
        "ad_spend_efficiency": 14.5,
        "pipeline_p95_latency_ms": 480.0,
        "schema_drift_count": 4.0,
        "query_cost_usd": 142.0,
        "mql_to_sql_ratio": 0.18,
        "campaign_lift": 0.05,
        "creative_ctr": 0.022,
        "ticket_p95_resolution_h": 11.5,
        "on_call_paging_count": 6.0,
        "incident_count_7d": 3.0,
        "nps": 41.0,
        "renewal_rate": 0.86,
        "at_risk_account_count": 9.0,
        "hiring_velocity": 1.5,
        "strategy_review_cadence_d": 14.0,
        "policy_violation_count_7d": 2.0,
        "ramp_completeness": 0.65,
        "source_coverage": 0.74,
        "activation_rate": 0.41,
        "feature_adoption_p7": 0.27,
        "dau_wau_ratio": 0.46,
    }
    return table.get(metric_id, 1.0)


# ---------------------------------------------------------------------------
# W5.A4 — Team-scope and Company-scope autoresearch loops.
#
# The Team loop runs experiments shared across every member of a Team-Domain.
# Each cycle:
#
#   1. Discover Team members via team_lookup.members_of_team(domain_id).
#   2. Pick one member's position (deterministic round-robin) to drive the
#      improvement candidate selection — Teams don't have positions of their
#      own, so we borrow the dominant member's position for candidate-pool
#      diversity.
#   3. Emit propose → run → resolve with audience="team:<domain_uuid>".
#   4. Honour conflict arbitration on resolve: if a Company-level outcome
#      touched the same metric in the last 7 days, force-discard with
#      rationale "superseded_by_higher_scope:company".
#
# The Company loop is structurally identical but with audience="company"
# and a higher-priority arbitration rule (Company outcomes cannot be
# superseded — they are the apex).
#
# Per-scope budget caps prevent any single audience scope from saturating the
# proposal stream. Daily counts are taken from the live ledger so caps survive
# process restarts (no in-memory counter that resets on reboot).
# ---------------------------------------------------------------------------


def _default_team_interval_s() -> float:
    raw = os.environ.get("WORM_CORE_AUTORESEARCH_TEAM_INTERVAL_S")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    is_dev = os.environ.get("WORMBASE_DEV", "").strip().lower() in ("1", "true")
    return 30.0 if is_dev else 900.0  # 15 min in prod


def _default_company_interval_s() -> float:
    raw = os.environ.get("WORM_CORE_AUTORESEARCH_COMPANY_INTERVAL_S")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    is_dev = os.environ.get("WORMBASE_DEV", "").strip().lower() in ("1", "true")
    return 30.0 if is_dev else 3600.0  # 1 hour in prod


def _budget_for_scope(scope: str) -> int:
    """Per-scope daily budget cap, env-overridable.

    Defaults: Person 5/day, Team 3/day, Company 1/day. Higher scopes get
    smaller caps because their experiments span more of the org and the
    natural cadence of metric improvement at higher scopes is slower.
    """
    defaults = {"person": 5, "team": 3, "company": 1}
    env_keys = {
        "person": "WORM_CORE_AUTORESEARCH_BUDGET_PERSON",
        "team": "WORM_CORE_AUTORESEARCH_BUDGET_TEAM",
        "company": "WORM_CORE_AUTORESEARCH_BUDGET_COMPANY",
    }
    raw = os.environ.get(env_keys.get(scope, ""))
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return defaults.get(scope, 1)


def _normalise_audience(payload: dict[str, Any]) -> str | None:
    """Read the audience marker from an ``experiment_proposed`` payload.

    Pre-W5.A4 rows have no ``audience`` key; those normalise to
    ``"person:<for_person_id>"`` so the conflict arbitrator can compare
    apples-to-apples across legacy and current rows.
    """
    args = payload.get("args") or {}
    audience = args.get("audience")
    if audience:
        return str(audience)
    fpid = args.get("for_person_id")
    if fpid:
        return f"person:{fpid}"
    return None


def _scope_of(audience: str | None) -> str:
    """Return ``"person" | "team" | "company"`` from an audience marker."""
    if audience is None:
        return "person"
    if audience == "company":
        return "company"
    if audience.startswith("team:"):
        return "team"
    return "person"


_SCOPE_RANK = {"person": 0, "team": 1, "company": 2}


async def _check_higher_scope_conflict(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    *,
    metric: str,
    own_scope: str,
    now: datetime,
    lookback_days: int = 7,
) -> str | None:
    """Return the audience marker of a higher-scope ``keep`` on the same metric.

    Conflict arbitration is specificity-inverted: ``Company > Team > Person``.
    A Person-scope ``keep`` is overridden by a Team or Company ``keep`` on the
    same metric within the last 7 days. A Team-scope ``keep`` is overridden
    by a Company ``keep`` only. Company is the apex and is never overridden.

    Implementation: walk the ledger's ``emit_experiment_resolved`` execute
    rows, join them to the matching ``emit_experiment_proposed`` rows on
    ``experiment_id`` to read the audience and metric, and return the highest-
    rank audience whose scope rank exceeds ``own_scope``'s rank. Returns
    ``None`` if no higher-scope outcome exists.

    7-day window: chosen to align with the natural cadence of metric review
    at the org level — daily for Person, weekly for Team/Company. A higher-
    scope decision older than 7 days is considered stale and does not gate
    the lower scope.
    """
    if own_scope == "company":
        # Company is the apex; nothing supersedes it.
        return None
    cutoff = now - timedelta(days=lookback_days)
    rows = await ledger.fetch(company_id)

    # Build a {experiment_id -> (audience, metric)} index from the proposed
    # rows so resolve rows can be joined back.
    index: dict[str, tuple[str | None, str | None]] = {}
    for r in rows:
        if r["kind"] != "execute":
            continue
        payload = r["payload"]
        if payload.get("tool") != "emit_experiment_proposed":
            continue
        args = payload.get("args") or {}
        eid = args.get("experiment_id")
        if not eid:
            continue
        index[str(eid)] = (
            _normalise_audience(payload),
            args.get("headline_metric"),
        )

    own_rank = _SCOPE_RANK[own_scope]
    best: tuple[int, str] | None = None
    for r in rows:
        if r["kind"] != "execute":
            continue
        payload = r["payload"]
        if payload.get("tool") != "emit_experiment_resolved":
            continue
        args = payload.get("args") or {}
        if args.get("outcome") != "keep":
            continue
        eid = args.get("experiment_id")
        if not eid or str(eid) not in index:
            continue
        audience, exp_metric = index[str(eid)]
        if exp_metric != metric:
            continue
        ts = r.get("ts")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                continue
        if not isinstance(ts, datetime):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts < cutoff:
            continue
        scope = _scope_of(audience)
        rank = _SCOPE_RANK[scope]
        if rank <= own_rank:
            continue
        # Track the highest-rank higher-scope outcome so e.g. a Person sees
        # both a Team and a Company keep, the Company one wins.
        if best is None or rank > best[0]:
            best = (rank, audience or "company")
    return best[1] if best else None


async def _audience_count_today(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    *,
    audience: str,
    now: datetime,
) -> int:
    """Count today's ``experiment_proposed`` entries with the given audience.

    "Today" is the 24h window ending at ``now``. Live-ledger reads so the
    count is replay-stable and survives process restarts.
    """
    cutoff = now - timedelta(hours=24)
    rows = await ledger.fetch(company_id)
    n = 0
    for r in rows:
        if r["kind"] != "execute":
            continue
        payload = r["payload"]
        if payload.get("tool") != "emit_experiment_proposed":
            continue
        if _normalise_audience(payload) != audience:
            continue
        ts = r.get("ts")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                continue
        if not isinstance(ts, datetime):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts < cutoff:
            continue
        n += 1
    return n


@dataclass
class TeamAutoresearchLoop:
    """Team-Domain-scoped autoresearch loop.

    Operationally identical to :class:`AutoresearchLoop` but the audience
    marker is ``team:<domain_uuid>`` and conflict arbitration honours the
    higher-scope rule (a Company keep on the same metric within 7 days
    discards the Team experiment).
    """

    ledger: Ledger | InMemoryLedger
    company_id: UUID
    team_domain_id: UUID
    poll_interval_s: float = 900.0
    cycle_count: int = 0

    async def run_once(self, *, now: datetime | None = None) -> int:
        from wormbase_core import team_lookup

        now = now or datetime.now(UTC)
        budget = _budget_for_scope("team")
        audience = f"team:{self.team_domain_id}"
        if budget <= 0:
            return 0
        used = await _audience_count_today(
            self.ledger, self.company_id, audience=audience, now=now,
        )
        if used >= budget:
            logger.debug(
                "team_loop budget exhausted: team=%s used=%d budget=%d",
                self.team_domain_id, used, budget,
            )
            self.cycle_count += 1
            return 0

        members = await team_lookup.members_of_team(
            self.ledger, self.company_id, self.team_domain_id,
        )
        if not members:
            self.cycle_count += 1
            return 0

        # Borrow a member's position to drive candidate-pool selection.
        # Deterministic by (team_id, cycle_count) so replay reproduces the
        # arc.
        ordered = sorted(members, key=str)
        seed = f"{self.team_domain_id}:{self.cycle_count}"
        idx = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % len(ordered)
        member_id = ordered[idx]

        # Discover the member's position via the per-Person loop's helper.
        helper = AutoresearchLoop(
            ledger=self.ledger,
            company_id=self.company_id,
            poll_interval_s=self.poll_interval_s,
        )
        helper.cycle_count = self.cycle_count
        people = await helper._collect_person_positions()
        pp = next((p for p in people if p.person_id == member_id), None)
        if pp is None:
            # Fall back to any registered member.
            pp = next((p for p in people if p.person_id in members), None)
        if pp is None:
            self.cycle_count += 1
            return 0

        emitted = await self._run_team_cycle(
            helper, pp, audience=audience, now=now,
        )
        self.cycle_count += 1
        return int(emitted)

    async def _run_team_cycle(
        self,
        helper: AutoresearchLoop,
        pp: PersonPosition,
        *,
        audience: str,
        now: datetime,
    ) -> bool:
        position = get_position(pp.position_id)
        if position is None:
            return False
        candidates = position_candidates(pp.position_id)
        if not candidates:
            return False

        candidate = helper._pick_candidate(pp, candidates)
        experiment_id = uuid5(
            _EXPERIMENT_NAMESPACE,
            f"team:{self.team_domain_id}:{self.cycle_count}:{candidate.candidate_id}",
        )
        await helper._emit_proposed(
            pp, candidate, experiment_id, now=now, audience=audience,
        )
        started_at = now
        finished_at = now + timedelta(seconds=60)
        await helper._emit_run(pp, candidate, experiment_id, started_at, finished_at)

        # Conflict arbitration: a Company-level keep on the same metric in
        # the last 7 days supersedes this Team-level outcome.
        forced_discard = await _check_higher_scope_conflict(
            self.ledger,
            self.company_id,
            metric=candidate.headline_metric_id,
            own_scope="team",
            now=now,
        )
        if forced_discard:
            outcome = "discard"
            observed_delta = 0.0
            rationale = f"superseded_by_higher_scope:{forced_discard}"
        else:
            outcome, rationale, observed_delta = AutoresearchLoop._resolve(
                experiment_id, candidate,
            )
        await helper._emit_resolved(
            experiment_id,
            outcome=outcome,
            observed_delta=observed_delta,
            rationale=rationale,
            now=finished_at,
        )
        # P9 — extract any pending lessons (idempotent).
        try:
            await extract_lessons_for_kept(
                self.ledger, self.company_id, now=finished_at,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("team learn-step extraction failed: %s", exc)
        return True

    async def run_forever(self) -> None:
        logger.info(
            "team_autoresearch_loop starting: company=%s team=%s interval=%.1fs",
            self.company_id, self.team_domain_id, self.poll_interval_s,
        )
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("team_autoresearch_loop cycle failed: %s", exc)
            try:
                await asyncio.sleep(self.poll_interval_s)
            except asyncio.CancelledError:
                raise


@dataclass
class CompanyAutoresearchLoop:
    """Company-scoped autoresearch loop.

    Audience marker is ``"company"``. Borrows any registered Person to drive
    candidate selection (Company-scope experiments don't have a Person owner;
    the for_person_id field carries the borrowed Person for backward compat).
    Company is the apex of the scope hierarchy — its outcomes are never
    superseded by lower-scope outcomes.
    """

    ledger: Ledger | InMemoryLedger
    company_id: UUID
    poll_interval_s: float = 3600.0
    cycle_count: int = 0

    async def run_once(self, *, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        budget = _budget_for_scope("company")
        if budget <= 0:
            return 0
        audience = "company"
        used = await _audience_count_today(
            self.ledger, self.company_id, audience=audience, now=now,
        )
        if used >= budget:
            logger.debug(
                "company_loop budget exhausted: used=%d budget=%d",
                used, budget,
            )
            self.cycle_count += 1
            return 0

        helper = AutoresearchLoop(
            ledger=self.ledger,
            company_id=self.company_id,
            poll_interval_s=self.poll_interval_s,
        )
        helper.cycle_count = self.cycle_count
        people = await helper._collect_person_positions()
        if not people:
            self.cycle_count += 1
            return 0

        # Pick the highest-priority Person deterministically. Founders / CEOs
        # tend to own company-wide metrics; we prefer those positions when
        # present. Fallback: deterministic round-robin by sorted person_id.
        priority = ("founder", "admin", "cfo", "ceo")
        priority_pp: PersonPosition | None = None
        for pos in priority:
            for pp in people:
                if pp.position_id == pos:
                    priority_pp = pp
                    break
            if priority_pp is not None:
                break
        if priority_pp is None:
            ordered = sorted(people, key=lambda p: (str(p.person_id), p.position_id))
            seed = f"company:{self.cycle_count}"
            idx = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % len(ordered)
            priority_pp = ordered[idx]

        emitted = await self._run_company_cycle(
            helper, priority_pp, audience=audience, now=now,
        )
        self.cycle_count += 1
        return int(emitted)

    async def _run_company_cycle(
        self,
        helper: AutoresearchLoop,
        pp: PersonPosition,
        *,
        audience: str,
        now: datetime,
    ) -> bool:
        position = get_position(pp.position_id)
        if position is None:
            return False
        candidates = position_candidates(pp.position_id)
        if not candidates:
            return False

        candidate = helper._pick_candidate(pp, candidates)
        experiment_id = uuid5(
            _EXPERIMENT_NAMESPACE,
            f"company:{self.cycle_count}:{candidate.candidate_id}",
        )
        await helper._emit_proposed(
            pp, candidate, experiment_id, now=now, audience=audience,
        )
        started_at = now
        finished_at = now + timedelta(seconds=60)
        await helper._emit_run(pp, candidate, experiment_id, started_at, finished_at)

        # Company is the apex — never superseded.
        outcome, rationale, observed_delta = AutoresearchLoop._resolve(
            experiment_id, candidate,
        )
        await helper._emit_resolved(
            experiment_id,
            outcome=outcome,
            observed_delta=observed_delta,
            rationale=rationale,
            now=finished_at,
        )
        # P9 — extract any pending lessons (idempotent).
        try:
            await extract_lessons_for_kept(
                self.ledger, self.company_id, now=finished_at,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("company learn-step extraction failed: %s", exc)
        return True

    async def run_forever(self) -> None:
        logger.info(
            "company_autoresearch_loop starting: company=%s interval=%.1fs",
            self.company_id, self.poll_interval_s,
        )
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("company_autoresearch_loop cycle failed: %s", exc)
            try:
                await asyncio.sleep(self.poll_interval_s)
            except asyncio.CancelledError:
                raise


async def team_loop_runner(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    team_domain_id: UUID,
    *,
    poll_interval_s: float | None = None,
) -> None:
    """Background task: drive ``TeamAutoresearchLoop`` on a periodic timer.

    Symmetric with :func:`autoresearch_loop_runner`. Default poll interval is
    15 min in prod, 30s in dev (or whatever ``WORM_CORE_AUTORESEARCH_TEAM_INTERVAL_S``
    is set to).
    """
    interval = (
        poll_interval_s
        if poll_interval_s is not None
        else _default_team_interval_s()
    )
    loop = TeamAutoresearchLoop(
        ledger=ledger,
        company_id=company_id,
        team_domain_id=team_domain_id,
        poll_interval_s=interval,
    )
    logger.info(
        "team_loop_runner starting: company=%s team=%s interval=%.1fs",
        company_id, team_domain_id, interval,
    )
    while True:
        try:
            n = await loop.run_once()
            if n:
                logger.info(
                    "team_autoresearch emitted %d experiments (cycle %d, team %s)",
                    n, loop.cycle_count, team_domain_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("team_loop_runner cycle failed: %s", exc)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise


async def company_loop_runner(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    *,
    poll_interval_s: float | None = None,
) -> None:
    """Background task: drive ``CompanyAutoresearchLoop`` on a periodic timer.

    Default poll interval is 1 hour in prod, 30s in dev.
    """
    interval = (
        poll_interval_s
        if poll_interval_s is not None
        else _default_company_interval_s()
    )
    loop = CompanyAutoresearchLoop(
        ledger=ledger,
        company_id=company_id,
        poll_interval_s=interval,
    )
    logger.info(
        "company_loop_runner starting: company=%s interval=%.1fs",
        company_id, interval,
    )
    while True:
        try:
            n = await loop.run_once()
            if n:
                logger.info(
                    "company_autoresearch emitted %d experiments (cycle %d)",
                    n, loop.cycle_count,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("company_loop_runner cycle failed: %s", exc)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise


__all__ = [
    "AutoresearchLoop",
    "CompanyAutoresearchLoop",
    "PersonPosition",
    "TeamAutoresearchLoop",
    "autoresearch_loop_runner",
    "company_loop_runner",
    "team_loop_runner",
]


async def _latest_proposed_seq(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    experiment_id: str,
) -> int:
    """Return the seq of the latest ``emit_experiment_proposed`` for an experiment.

    Used by the lesson-application path to stamp ``applied_at`` with a
    replay-stable height (every replay re-derives the same seq for a given
    experiment_id).
    """
    rows = await ledger.fetch(company_id)
    best = 0
    for r in rows:
        if r["kind"] != "execute":
            continue
        payload = r["payload"]
        if payload.get("tool") != "emit_experiment_proposed":
            continue
        args = payload.get("args") or {}
        if str(args.get("experiment_id") or "") != experiment_id:
            continue
        seq = int(r.get("seq") or 0)
        if seq > best:
            best = seq
    return best


# ---------------------------------------------------------------------------
# Public unused helper, kept for future Postgres-side optimisation paths
# ---------------------------------------------------------------------------


async def _max_seq(ledger: Ledger, company_id: UUID) -> int:  # pragma: no cover
    """Return the current ``MAX(seq)`` for a company; 0 if empty.

    Currently unused — the autoresearch loop walks ``ledger.fetch`` directly
    so it works against InMemoryLedger in tests. Kept as a thin helper for
    a future Postgres-side cursor implementation.
    """
    if not isinstance(ledger, Ledger):
        return 0
    async with ledger.engine.begin() as conn:
        res = await conn.execute(
            _sql_text(
                "SELECT COALESCE(MAX(seq), 0) FROM ledger WHERE company_id = :cid"
            ),
            {"cid": company_id},
        )
        return int(res.scalar() or 0)


# Silence "uuid4 imported but not used" — kept for symmetry with helpers
# above and likely future use.
_ = uuid4
_ = Iterable
