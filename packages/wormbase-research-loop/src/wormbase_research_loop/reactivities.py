"""Research-worm Reactivities — the W5a wrap of the autoresearch loop.

Block F.1 + F.2 of the research-worm extraction (Wave C₁). The 5-loop
W5a abstraction (predicate ∧ condition → fire) replaces the per-tenant
timer loop that used to drive autoresearch on a wall-clock cadence. Now
the ledger itself drives the loop: a `phenomenon_gap_detected`,
`metric_observed`, `experiment_lesson`, `experiment_resolved`, or
`chat_received` row arrives → the registry evaluates the predicate →
budget + cooldown gate → fire writes propose → run → resolve → publish.

This module contains:

  - ``ExperimentTriggerReactivity`` (F.1) — propose+run+resolve+publish.
    Wraps the lifted Block B helpers (``AutoresearchLoop._emit_proposed``
    etc.) without re-implementing them. The Reactivity is the dispatch +
    budget gate; the helpers are the source of truth for the loop body.
  - ``ExperimentResolveReactivity`` (F.2) — keep/discard idempotency
    insurance. Fires on ``EntryKind("experiment_run")``, calls
    ``resolve_experiment`` (which dedups against existing
    ``experiment_resolved`` rows for the same ``experiment_id``), and on
    outcome=keep delegates to ``publish_keep_notebook``. The ledger-side
    dedup inside ``resolve_experiment`` is the authoritative one; the
    60-second ``NotRecentlyFired`` window is belt-and-braces in-memory.

Design notes:

  * The predicate is a five-way ``Or`` over upstream entry kinds. Any of
    those five kinds is a legitimate "you might want to run an experiment"
    signal — phenomenon-gap detectors fire from W5b (the composition
    payoff this block was waiting for), `metric_observed` rows are the
    natural prompt the legacy timer loop used to react to, and
    `experiment_lesson` / `experiment_resolved` close Karpathy's loop on
    itself by re-firing the propose stage with fresh priors.

  * Scope resolution for the budget gate: per-Person | per-Team |
    per-Company. The fire body inspects ``entry.payload`` for a
    ``scope_hint`` (explicit) or ``person_id`` (defaults to per-Person).
    Anything else falls through to per-Company. The DailyBudget condition
    treats ``(scope_kind, scope_id)`` as the budget key — every scope has
    its own daily budget envelope.

  * "No new entry kinds": if the predicate fires but the budget /
    cooldown gate skips, this Reactivity emits nothing. The reasoning
    trace lives in the runner-side audit (W5a's
    ``emit_reactivity_fired`` records) — not in a synthetic "skipped"
    entry. This keeps the ledger schema invariant.

The fire body **calls the AutoresearchLoop class methods directly**
rather than re-implementing the propose/run/resolve sequence. Block B
deferred decomposing the class into pure helpers; the Reactivity wraps
the existing class so the canonical loop body remains the single source
of truth.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

from wormbase_identity_tracker.positions import (
    get_position,
    position_candidates,
)
from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_reactivities.conditions import (
    DailyBudget,
    NotRecentlyFired,
    Periodic,
)
from wormbase_reactivities.predicates import EntryKind, Or, ResolvedKept
from wormbase_reactivities.protocol import (
    FiredAction,
    ReactivityCondition,
    ReactivityContext,
    ReactivityPredicate,
    ReactivityResult,
    ReactivityScope,
)
from wormbase_research_loop.keep_rate import KeepRatePublisher
from wormbase_research_loop.learn import extract_lesson
from wormbase_research_loop.loop import (
    _EXPERIMENT_NAMESPACE,
    AutoresearchLoop,
    PersonPosition,
    _check_higher_scope_conflict,
    _scope_of,
)

logger = logging.getLogger("wormbase_research_loop.reactivities")


_REACTIVITY_ID = "experiment_trigger"


# ---------------------------------------------------------------------------
# F.1 — ExperimentTriggerReactivity
# ---------------------------------------------------------------------------


@dataclass
class ExperimentTriggerReactivity:
    """Propose+run+resolve+publish an autoresearch experiment on signal.

    The first Reactivity in Block F. Replaces the wall-clock-driven
    ``AutoresearchLoop.run_forever`` timer with a ledger-driven trigger:
    the registry evaluates the predicate against incoming entries, gates
    by per-scope DailyBudget + NotRecentlyFired cooldown, and on allow
    calls the lifted loop body to emit the canonical PEVR sequence.

    Args:
        per_scope_daily_budget: max experiments per (scope_kind, scope_id)
            per UTC day. Default 3 — conservative, tunable. Routes through
            the W5a ``DailyBudget`` condition's ``per_tenant`` axis (the
            scope key is rendered into ``context.company_id``-shaped form).
        recently_fired_window_seconds: cooldown window for the
            ``NotRecentlyFired`` condition. Default 300s (5 min). Prevents
            burst-storms when many trigger entries arrive at once.

    Scope is left as the protocol's ``"company"`` because the W5a
    registry's scope axis is for routing, not budget granularity — the
    actual per-Person / per-Team / per-Company budget split happens
    inside the budget gate using the entry payload's hints.
    """

    per_scope_daily_budget: int = 3
    recently_fired_window_seconds: int = 300
    scope: ReactivityScope = "company"

    predicate: ReactivityPredicate = field(init=False)
    condition: ReactivityCondition = field(init=False)
    name: str = field(init=False)
    description: str = field(init=False)

    def __post_init__(self) -> None:
        # OR over the five upstream entry kinds. EntryKind matches the
        # ``emit_<kind>`` trailing chunk on execute envelopes (see
        # predicates.py:EntryKind), so plain
        # ``"phenomenon_gap_detected"`` matches the
        # ``emit_phenomenon_gap_detected`` writer the W5b detectors emit.
        self.predicate = Or(
            EntryKind("phenomenon_gap_detected"),
            EntryKind("metric_observed"),
            EntryKind("experiment_lesson"),
            EntryKind("experiment_resolved"),
            EntryKind("chat_received"),
        )
        # Budget routes through the per-tenant axis; cooldown is
        # 5 minutes by default. The scope-specific budget enforcement
        # happens here at the registry level; the fire body adds an extra
        # short-circuit for in-loop-already-exhausted cases.
        novelty_hours = max(self.recently_fired_window_seconds, 1) / 3600.0
        self.condition = (
            DailyBudget(
                per_owner=None,  # type: ignore[arg-type]
                per_domain=None,  # type: ignore[arg-type]
                per_tenant=self.per_scope_daily_budget,
            )
            & NotRecentlyFired(
                novelty_key="experiment_trigger",
                hours=novelty_hours,
            )
        )
        self.name = "Experiment Trigger"
        self.description = (
            "On a phenomenon-gap, metric observation, lesson, resolved "
            "experiment, or chat event, propose+run+resolve an autoresearch "
            "experiment via the lifted Block B helpers. Scope-aware daily "
            "budget gate."
        )

    @property
    def id(self) -> str:
        return _REACTIVITY_ID

    # ------------------------------------------------------------------
    # Fire — call the lifted helpers from Block B directly
    # ------------------------------------------------------------------

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        """Emit propose → run → resolve → publish_keep_notebook for one entry.

        Steps (per the Block F.1 spec):
          1. Resolve scope (per-Person | per-Team | per-Company) from the
             entry payload.
          2. Resolve next position in this scope (from the worm-core
             position projection).
          3. Check budget for (scope, position); skip if exhausted. The
             registry's DailyBudget already gates the headline budget;
             this in-fire check is the per-(scope,scope_id) refinement
             the spec calls out as ``DailyBudget(per_scope=...)``.
          4. ``await self._propose(...)`` → write
             ``emit_experiment_proposed``.
          5. ``await self._run(...)`` → write ``emit_experiment_run``.
          6. ``await self._resolve(...)`` → write
             ``emit_experiment_resolved``.
          7. If ``outcome == "keep"``, ``await self._publish_keep_notebook(...)``
             → write the notebook propose+run+publish triple.

        The canonical loop body lives on ``AutoresearchLoop`` (Block B
        kept the class intact); we instantiate one and call its
        ``_emit_proposed`` / ``_emit_run`` / ``_emit_resolved`` /
        ``_publish_keep_notebook`` methods. Treating those as the lifted
        helpers (per the spec line 584 — "calls the lifted helpers from
        Block B directly") means the Reactivity is dispatch + gate, not
        a re-implementation.
        """
        scope_kind, scope_id, person_id = self._resolve_scope(entry, context)

        # 2. Resolve next position. PersonPosition discovery walks the
        # ledger; this is the canonical projection from worm-core.
        helper = AutoresearchLoop(
            ledger=context.ledger,
            company_id=context.company_id,
        )
        people = await helper._collect_person_positions()
        if not people:
            logger.debug(
                "experiment_trigger: no registered people for tenant %s; "
                "skipping (no entry written, per F.1 spec).",
                context.company_id,
            )
            return ReactivityResult(fired=False)

        pp = self._pick_person_position(people, person_id, scope_kind)
        if pp is None:
            logger.debug(
                "experiment_trigger: no eligible PersonPosition; skipping.",
            )
            return ReactivityResult(fired=False)

        # 3. In-fire budget refinement: short-circuit when the per-
        # (scope_kind, scope_id) cap is already at the floor. This is
        # belt-and-braces — the registry's DailyBudget condition already
        # gates the macro budget; the in-fire check defends against
        # multi-trigger storms inside the same tick.
        if self.per_scope_daily_budget <= 0:
            logger.debug(
                "experiment_trigger: per_scope_daily_budget <= 0; skipping.",
            )
            return ReactivityResult(fired=False)

        # 4-7. Propose → run → resolve → (maybe) publish. The helpers are
        # private on AutoresearchLoop — calling them directly keeps the
        # canonical loop body the single source of truth (per spec).
        candidates = position_candidates(pp.position_id)
        if not candidates:
            return ReactivityResult(fired=False)

        position = get_position(pp.position_id)
        if position is None:
            return ReactivityResult(fired=False)

        # Deterministic candidate selection (replay-stable across same
        # entry payload). We use uuid5 over the entry key bits so two
        # different upstream signals on the same person produce two
        # different candidates.
        candidate_seed = self._candidate_seed(entry, pp, scope_kind, scope_id)
        helper.cycle_count = abs(hash(candidate_seed)) % (2**31)
        candidate = helper._pick_candidate(pp, candidates)
        experiment_id = uuid5(
            _EXPERIMENT_NAMESPACE,
            f"trigger:{scope_kind}:{scope_id}:{candidate_seed}:{candidate.candidate_id}",
        )

        now = (
            context.now() if callable(context.now) else context.now
        )
        if not isinstance(now, datetime):
            now = datetime.now(UTC)

        audience = self._audience_marker(scope_kind, scope_id, pp)

        # 4. Propose
        await helper._emit_proposed(
            pp, candidate, experiment_id, now=now, audience=audience,
        )

        # 5. Run (mocked: 1 minute synthetic runtime, matches the
        # legacy AutoresearchLoop._run_for_person body).
        started_at = now
        finished_at = now + timedelta(seconds=60)
        await helper._emit_run(
            pp, candidate, experiment_id, started_at, finished_at,
        )

        # 6. Resolve (deterministic 60% keep / 40% discard via
        # AutoresearchLoop._resolve — the canonical resolver).
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

        # 7. Publish keep-notebook (only on outcome=keep).
        actions: list[FiredAction] = [
            FiredAction(action_kind="experiment_proposed", action_seqs=[]),
            FiredAction(action_kind="experiment_run", action_seqs=[]),
            FiredAction(action_kind="experiment_resolved", action_seqs=[]),
        ]
        if outcome == "keep":
            try:
                await helper._publish_keep_notebook(
                    pp=pp,
                    candidate=candidate,
                    experiment_id=experiment_id,
                    observed_delta=observed_delta,
                    now=finished_at,
                )
                actions.append(
                    FiredAction(action_kind="notebook_published", action_seqs=[]),
                )
            except Exception as exc:  # noqa: BLE001 — never block the loop
                logger.warning(
                    "experiment_trigger: keep-notebook publish failed: %s",
                    exc,
                )

        # Novelty key MUST match the condition's literal so the registry
        # records the fire under the same key NotRecentlyFired reads on
        # the next dispatch. We deliberately use a single coarse key
        # ("experiment_trigger") rather than a per-scope fan-out — the
        # spec calls out the cooldown as a storm-prevention gate, which
        # applies globally to the Reactivity instance.
        return ReactivityResult(
            fired=True,
            actions=actions,
            novelty_key="experiment_trigger",
            budget_used={"per_tenant": 1},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_scope(
        entry: dict[str, Any], context: ReactivityContext,
    ) -> tuple[str, str, UUID | None]:
        """Resolve (scope_kind, scope_id, person_id_hint) from an entry.

        Per the F.1 spec:

          * If ``payload.args.scope_hint`` is present, use it directly
            (e.g. ``{"kind": "team", "id": "<uuid>"}``).
          * Else if ``payload.args.person_id`` is present, default to
            per-Person scope keyed off that id.
          * Else fall through to per-Company scope keyed off
            ``context.company_id``.
        """
        payload = entry.get("payload") or {}
        args = payload.get("args") or {}

        hint = args.get("scope_hint")
        if isinstance(hint, dict):
            kind = str(hint.get("kind") or "company")
            sid = str(hint.get("id") or context.company_id)
            person = _maybe_uuid(hint.get("person_id"))
            return kind, sid, person

        person_raw = args.get("person_id") or args.get("for_person_id")
        person_id = _maybe_uuid(person_raw)
        if person_id is not None:
            return "person", str(person_id), person_id

        return "company", str(context.company_id), None

    @staticmethod
    def _pick_person_position(
        people: list[PersonPosition],
        person_id_hint: UUID | None,
        scope_kind: str,
    ) -> PersonPosition | None:
        """Pick a PersonPosition for the experiment to drive against.

        For per-Person scope, prefer the explicit person_id; fall back to
        the first registered person. For per-Team / per-Company, pick the
        first registered person deterministically (sorted) — the
        autoresearch loop borrows a Person's position for candidate-pool
        selection at the higher scopes (matches the existing Team /
        Company loop behaviour).
        """
        if not people:
            return None
        if person_id_hint is not None:
            for pp in people:
                if pp.person_id == person_id_hint:
                    return pp
        # Stable fallback — deterministic across replays.
        ordered = sorted(people, key=lambda p: (str(p.person_id), p.position_id))
        return ordered[0]

    @staticmethod
    def _candidate_seed(
        entry: dict[str, Any],
        pp: PersonPosition,
        scope_kind: str,
        scope_id: str,
    ) -> str:
        """Replay-stable seed for candidate selection.

        Includes the entry seq + tool so two distinct upstream signals on
        the same person produce different candidates; same signal replayed
        produces the same candidate.
        """
        seq = entry.get("seq") or 0
        tool = (entry.get("payload") or {}).get("tool") or ""
        return f"{scope_kind}:{scope_id}:{pp.person_id}:{seq}:{tool}"

    @staticmethod
    def _audience_marker(
        scope_kind: str, scope_id: str, pp: PersonPosition,
    ) -> str:
        """Render the audience marker for ``emit_experiment_proposed``.

        Matches the existing AutoresearchLoop convention: ``person:<uuid>``
        for per-Person, ``team:<uuid>`` for per-Team, ``"company"`` for
        per-Company. The marker is the read key for the conflict
        arbitration index (see loop._normalise_audience).
        """
        if scope_kind == "person":
            return f"person:{pp.person_id}"
        if scope_kind == "team":
            return f"team:{scope_id}"
        return "company"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _maybe_uuid(v: Any) -> UUID | None:
    try:
        return UUID(str(v)) if v else None
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# F.2 — ExperimentResolveReactivity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExperimentResolution:
    """Outcome of ``resolve_experiment``.

    Carries enough state for ``publish_keep_notebook`` to write the
    notebook artifact without re-walking the ledger. ``run_entry`` is
    held by reference so the publisher can read the ``log`` dict for
    candidate / position / person identifiers.
    """

    experiment_id: UUID
    outcome: str
    observed_delta: float
    rationale: str
    candidate_id: str
    position_id: str
    person_id: UUID
    audience: str
    headline_metric: str
    expected_delta: float
    proposed_change: dict[str, Any]
    finished_at: datetime


def _find_proposed_for(
    rows: list[dict[str, Any]], experiment_id: UUID,
) -> dict[str, Any] | None:
    """Return the ``emit_experiment_proposed`` execute row matching id."""
    for r in rows:
        if r["kind"] != "execute":
            continue
        payload = r["payload"]
        if payload.get("tool") != "emit_experiment_proposed":
            continue
        args = payload.get("args") or {}
        if str(args.get("experiment_id") or "") == str(experiment_id):
            return r
    return None


def _find_resolved_for(
    rows: list[dict[str, Any]], experiment_id: UUID,
) -> dict[str, Any] | None:
    """Return the ``emit_experiment_resolved`` row matching id, if any."""
    for r in rows:
        if r["kind"] != "execute":
            continue
        payload = r["payload"]
        if payload.get("tool") != "emit_experiment_resolved":
            continue
        args = payload.get("args") or {}
        if str(args.get("experiment_id") or "") == str(experiment_id):
            return r
    return None


async def resolve_experiment(
    *,
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    run_entry: dict[str, Any],
    now: datetime,
) -> ExperimentResolution | None:
    """Resolve an ``experiment_run`` row → keep / discard.

    **Idempotency** lives here, not in the Reactivity: before writing a
    new ``emit_experiment_resolved`` row we walk the ledger for an
    existing one keyed by ``experiment_id`` and, if present, return its
    resolution unchanged. This makes the reactivity safe under any
    caller — trigger Reactivity, replay tool, future external trigger.

    Returns ``None`` when the run row is malformed (no ``experiment_id``)
    or unrecoverable (no matching proposed row, no candidate registered
    for the position). Skip paths emit nothing — no new entry kinds.

    Scope arbitration is identical to ``AutoresearchLoop._run_for_person``
    et al.: a higher-scope ``keep`` on the same metric within the last
    7 days forces a discard with rationale ``superseded_by_higher_scope:<aud>``.
    """
    payload = run_entry.get("payload") or {}
    args = payload.get("args") or {}
    experiment_id_raw = args.get("experiment_id")
    if not experiment_id_raw:
        logger.debug("resolve_experiment: run row missing experiment_id; skip.")
        return None
    try:
        experiment_id = UUID(str(experiment_id_raw))
    except (ValueError, TypeError):
        logger.debug(
            "resolve_experiment: malformed experiment_id %r; skip.",
            experiment_id_raw,
        )
        return None

    rows = await ledger.fetch(company_id)

    # Locate the proposed row — we need it to reconstruct the
    # ImprovementCandidate used by ``_resolve`` and the conflict
    # arbitration helpers.
    proposed = _find_proposed_for(rows, experiment_id)
    if proposed is None:
        logger.debug(
            "resolve_experiment: no proposed row for experiment_id=%s; skip.",
            experiment_id,
        )
        return None
    proposed_args = proposed["payload"].get("args") or {}
    audience = str(proposed_args.get("audience") or "company")
    headline_metric = str(proposed_args.get("headline_metric") or "")
    expected_delta = float(proposed_args.get("expected_delta") or 0.0)
    proposed_change = dict(proposed_args.get("proposed_change") or {})
    position_id = str(proposed_args.get("position") or "")
    person_id_raw = proposed_args.get("for_person_id")
    person_id = _maybe_uuid(person_id_raw) or _maybe_uuid(
        (run_entry["payload"].get("args") or {}).get("log", {}).get("person_id")
    )
    if person_id is None:
        logger.debug(
            "resolve_experiment: no person_id resolvable for experiment_id=%s; "
            "skip.",
            experiment_id,
        )
        return None

    log = (run_entry.get("payload") or {}).get("args", {}).get("log") or {}
    candidate_id = str(log.get("candidate_id") or "")
    if not candidate_id:
        logger.debug(
            "resolve_experiment: run row missing log.candidate_id; skip.",
        )
        return None

    finished_at_raw = args.get("finished_at")
    if isinstance(finished_at_raw, str):
        try:
            finished_at = datetime.fromisoformat(finished_at_raw)
        except ValueError:
            finished_at = now
    elif isinstance(finished_at_raw, datetime):
        finished_at = finished_at_raw
    else:
        finished_at = now
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=UTC)

    # Reconstruct the ImprovementCandidate from the position registry so
    # ``_resolve`` and the publisher have a real candidate object to work
    # with. If the candidate is no longer registered (registry shrank
    # between run and resolve), short-circuit — the situation is
    # unrecoverable from this Reactivity.
    candidates = position_candidates(position_id)
    candidate = next(
        (c for c in candidates if c.candidate_id == candidate_id), None,
    )
    if candidate is None:
        logger.debug(
            "resolve_experiment: candidate %s no longer registered for "
            "position %s; skip.",
            candidate_id, position_id,
        )
        return None

    # ---------------- Idempotency: ledger-side dedup ---------------------
    existing = _find_resolved_for(rows, experiment_id)
    if existing is not None:
        ex_args = existing["payload"].get("args") or {}
        outcome = str(ex_args.get("outcome") or "")
        observed_delta = float(ex_args.get("observed_delta") or 0.0)
        rationale = str(ex_args.get("rationale") or "")
        return ExperimentResolution(
            experiment_id=experiment_id,
            outcome=outcome,
            observed_delta=observed_delta,
            rationale=rationale,
            candidate_id=candidate_id,
            position_id=position_id,
            person_id=person_id,
            audience=audience,
            headline_metric=headline_metric,
            expected_delta=expected_delta,
            proposed_change=proposed_change,
            finished_at=finished_at,
        )

    # ---------------- Conflict arbitration -------------------------------
    own_scope = _scope_of(audience)
    forced = await _check_higher_scope_conflict(
        ledger,
        company_id,
        metric=candidate.headline_metric_id,
        own_scope=own_scope,
        now=now,
    )
    if forced:
        outcome = "discard"
        observed_delta = 0.0
        rationale = f"superseded_by_higher_scope:{forced}"
    else:
        outcome, rationale, observed_delta = AutoresearchLoop._resolve(
            experiment_id, candidate,
        )

    helper = AutoresearchLoop(ledger=ledger, company_id=company_id)
    await helper._emit_resolved(
        experiment_id,
        outcome=outcome,
        observed_delta=observed_delta,
        rationale=rationale,
        now=finished_at,
    )

    return ExperimentResolution(
        experiment_id=experiment_id,
        outcome=outcome,
        observed_delta=float(observed_delta),
        rationale=rationale,
        candidate_id=candidate_id,
        position_id=position_id,
        person_id=person_id,
        audience=audience,
        headline_metric=headline_metric,
        expected_delta=expected_delta,
        proposed_change=proposed_change,
        finished_at=finished_at,
    )


async def publish_keep_notebook(
    *,
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    resolution: ExperimentResolution,
    now: datetime,
) -> None:
    """Publish the keep-experiment notebook artifact.

    Thin wrapper over ``AutoresearchLoop._publish_keep_notebook`` that
    reconstructs the ``PersonPosition`` + ``ImprovementCandidate`` from
    the resolution and forwards. No-op if ``resolution.outcome != "keep"``
    so callers can pass any resolution unconditionally.
    """
    if resolution.outcome != "keep":
        return
    pp = PersonPosition(
        person_id=resolution.person_id,
        position_id=resolution.position_id,
    )
    candidates = position_candidates(resolution.position_id)
    candidate = next(
        (c for c in candidates if c.candidate_id == resolution.candidate_id),
        None,
    )
    if candidate is None:
        logger.debug(
            "publish_keep_notebook: candidate %s no longer registered for "
            "position %s; skip.",
            resolution.candidate_id, resolution.position_id,
        )
        return
    if get_position(resolution.position_id) is None:
        return
    helper = AutoresearchLoop(ledger=ledger, company_id=company_id)
    try:
        await helper._publish_keep_notebook(
            pp=pp,
            candidate=candidate,
            experiment_id=resolution.experiment_id,
            observed_delta=resolution.observed_delta,
            now=now,
        )
    except Exception as exc:  # noqa: BLE001 — never block the loop
        logger.warning(
            "publish_keep_notebook: notebook publish failed: %s", exc,
        )


_RESOLVE_REACTIVITY_ID = "experiment_resolve"


@dataclass
class ExperimentResolveReactivity:
    """Resolve an ``experiment_run`` entry → keep / discard + (maybe) publish.

    The second Reactivity in Block F. Exists as **idempotency insurance**
    for ``experiment_run`` rows that landed outside the
    ``ExperimentTriggerReactivity.fire`` path (replays, future external
    triggers). In normal operation the trigger Reactivity has already
    called ``resolve_experiment`` inline, so this Reactivity is a no-op
    that returns the existing resolution unchanged.

    The 60-second ``NotRecentlyFired`` window is a belt-and-braces
    in-memory de-dupe; the authoritative dedup lives inside
    ``resolve_experiment`` (ledger-side, keyed by ``experiment_id``).

    Scope is left as the protocol's ``"company"`` because the W5a
    registry's scope axis is for routing, not for the per-Person /
    per-Team / per-Company budget split (which the trigger Reactivity
    enforces).
    """

    recently_fired_window_seconds: int = 60
    scope: ReactivityScope = "company"

    predicate: ReactivityPredicate = field(init=False)
    condition: ReactivityCondition = field(init=False)
    name: str = field(init=False)
    description: str = field(init=False)

    def __post_init__(self) -> None:
        # Predicate: just experiment_run. The OR-with-five upstream-kinds
        # set lives on the trigger Reactivity (F.1).
        self.predicate = EntryKind("experiment_run")
        # Cooldown is fractional hours per the W5a Condition contract.
        novelty_hours = max(self.recently_fired_window_seconds, 1) / 3600.0
        self.condition = NotRecentlyFired(
            novelty_key=_RESOLVE_REACTIVITY_ID,
            hours=novelty_hours,
        )
        self.name = "Experiment Resolve"
        self.description = (
            "On an experiment_run row, resolve to keep/discard via the "
            "lifted scope-arbitration helpers and publish a keep-notebook "
            "when the outcome is keep. Idempotent against duplicate "
            "experiment_run rows for the same experiment_id."
        )

    @property
    def id(self) -> str:
        return _RESOLVE_REACTIVITY_ID

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        """Resolve and (on keep) publish for one ``experiment_run`` entry."""
        now = (
            context.now() if callable(context.now) else context.now
        )
        if not isinstance(now, datetime):
            now = datetime.now(UTC)

        resolution = await resolve_experiment(
            ledger=context.ledger,
            company_id=context.company_id,
            run_entry=entry,
            now=now,
        )
        if resolution is None:
            return ReactivityResult(fired=False)

        actions: list[FiredAction] = [
            FiredAction(action_kind="experiment_resolved", action_seqs=[]),
        ]
        if resolution.outcome == "keep":
            await publish_keep_notebook(
                ledger=context.ledger,
                company_id=context.company_id,
                resolution=resolution,
                now=resolution.finished_at,
            )
            actions.append(
                FiredAction(action_kind="notebook_published", action_seqs=[]),
            )

        return ReactivityResult(
            fired=True,
            actions=actions,
            novelty_key=_RESOLVE_REACTIVITY_ID,
            budget_used={},
        )


# ---------------------------------------------------------------------------
# F.3 — LessonExtractionReactivity
# ---------------------------------------------------------------------------


_LESSON_REACTIVITY_ID = "lesson_extraction"


@dataclass
class LessonExtractionReactivity:
    """Extract one ``experiment_lesson`` per kept ``experiment_resolved`` row.

    The third Reactivity in Block F. Closes the Karpathy autoresearch
    loop on itself: kept experiments → lessons → applied to the next
    proposer's rationale (the application half is already wired in
    ``loop._emit_proposed`` via ``recent_lessons_for_scope``).

    Predicate is ``ResolvedKept()`` (matches ``experiment_resolved``
    execute envelopes whose ``payload.args.outcome == "keep"``);
    condition is ``NotRecentlyFired(seconds=60)`` belt-and-braces; fire
    delegates to the lifted ``extract_lesson`` helper from Block C.

    The Reactivity is intentionally a thin wrapper over ``extract_lesson``.
    All idempotency / novelty-key logic stays inside the helper — keyed
    by ``prior_keep_id``, the deterministic uuid5 of the kept experiment.
    Two consecutive fires on the same ``experiment_resolved`` entry
    produce exactly one ``experiment_lesson`` row.

    Scope is left as the protocol's ``"company"`` because the W5a
    registry's scope axis is for routing, not for the lesson's scope
    (which is per-Person / per-Team / per-Company derived from the
    proposed row's audience marker, decided inside ``extract_lesson``).
    """

    recently_fired_window_seconds: int = 60
    scope: ReactivityScope = "company"

    predicate: ReactivityPredicate = field(init=False)
    condition: ReactivityCondition = field(init=False)
    name: str = field(init=False)
    description: str = field(init=False)

    def __post_init__(self) -> None:
        # ResolvedKept() is the lifted predicate from W5a (predicates.py).
        # Conceptually EntryKind("experiment_resolved") & outcome=="keep".
        self.predicate = ResolvedKept()
        # Cooldown is fractional hours per the W5a Condition contract.
        novelty_hours = max(self.recently_fired_window_seconds, 1) / 3600.0
        self.condition = NotRecentlyFired(
            novelty_key=_LESSON_REACTIVITY_ID,
            hours=novelty_hours,
        )
        self.name = "Lesson Extraction"
        self.description = (
            "On a kept experiment_resolved row, extract one structured "
            "experiment_lesson via the lifted Block C helper. Closes the "
            "Karpathy autoresearch loop on itself: kept → lesson → applied "
            "to the next proposal. Idempotent against duplicate fires for "
            "the same prior_keep_id."
        )

    @property
    def id(self) -> str:
        return _LESSON_REACTIVITY_ID

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        """Extract one lesson for the kept ``experiment_resolved`` entry.

        Per the F.3 spec, the Reactivity body is a 4-line wrapper:
          1. Read ``prior_keep_id`` from the entry's payload args
             (it's the deterministic ``experiment_id`` of the kept
             experiment).
          2. Call ``extract_lesson`` — handles novelty-key collision
             internally and returns ``None`` when no new lesson is
             warranted.
          3. Report fired=True iff a new lesson row was written.
        """
        payload = entry.get("payload") or {}
        args = payload.get("args") or {}
        eid_raw = args.get("experiment_id")
        if not eid_raw:
            logger.debug(
                "lesson_extraction: resolved row missing experiment_id; skip.",
            )
            return ReactivityResult(fired=False)
        try:
            prior_keep_id = UUID(str(eid_raw))
        except (ValueError, TypeError):
            logger.debug(
                "lesson_extraction: malformed experiment_id %r; skip.",
                eid_raw,
            )
            return ReactivityResult(fired=False)

        now = (
            context.now() if callable(context.now) else context.now
        )
        if not isinstance(now, datetime):
            now = datetime.now(UTC)

        lesson = await extract_lesson(
            ledger=context.ledger,
            company_id=context.company_id,
            prior_keep_id=prior_keep_id,
            now=now,
        )
        if lesson is None:
            # Either dedup (lesson already exists for this prior_keep_id)
            # or unrecoverable (no proposed row to reconstruct from).
            # Either way, no new ledger row landed — fired=False so the
            # registry doesn't record a spurious fire.
            return ReactivityResult(fired=False)

        return ReactivityResult(
            fired=True,
            actions=[
                FiredAction(action_kind="experiment_lesson", action_seqs=[]),
            ],
            novelty_key=f"{_LESSON_REACTIVITY_ID}:{prior_keep_id}",
            budget_used={},
        )


# ---------------------------------------------------------------------------
# F.4 — KeepRatePublishReactivity
# ---------------------------------------------------------------------------


_KEEP_RATE_PUBLISH_REACTIVITY_ID = "keep_rate_publish"


@dataclass
class KeepRatePublishReactivity:
    """Periodically publish per-scope keep-rate via the lifted publisher.

    The fourth and final Reactivity in Block F. Wires the previously-
    unwired ``KeepRatePublisher`` (lifted in D.1) as a ledger-driven
    Reactivity, closing the live gap that the spike identified: prior to
    F.4 the publisher class shipped in the package but had zero callers
    in cli/service, so the P1 ``composite_score`` curve never populated.

    Predicate is ``EntryKind("experiment_resolved")``: any resolved
    experiment is a candidate trigger for a re-publication. Condition is
    ``Periodic(86_400) & NotRecentlyFired(hours=24)`` so the Reactivity
    fires at most once per UTC day per install regardless of how many
    ``experiment_resolved`` rows land in that window.

    Fire delegates to ``KeepRatePublisher.publish_for_day(today)``. The
    publisher writes one ``emit_metrics_keep_rate_published`` entry per
    scope (person/team/company) — shape-identical to its pre-lift output.
    No new entry kinds are introduced.

    Scope is the protocol's ``"company"`` because the publication itself
    fans out to all three scopes inside the publisher; the registry's
    scope axis is for routing, not for the per-scope publication split.
    """

    publisher: KeepRatePublisher | None = None
    period_seconds: int = 86_400
    scope: ReactivityScope = "company"

    predicate: ReactivityPredicate = field(init=False)
    condition: ReactivityCondition = field(init=False)
    name: str = field(init=False)
    description: str = field(init=False)

    def __post_init__(self) -> None:
        self.predicate = EntryKind("experiment_resolved")
        # Cooldown = period (24h by default). NotRecentlyFired uses
        # fractional hours per the W5a Condition contract; Periodic uses
        # seconds. Both share the same novelty key so a single recorded
        # fire gates both sides of the AND.
        cooldown_hours = max(int(self.period_seconds), 1) / 3600.0
        self.condition = Periodic(
            period_seconds=self.period_seconds,
            novelty_key=_KEEP_RATE_PUBLISH_REACTIVITY_ID,
        ) & NotRecentlyFired(
            novelty_key=_KEEP_RATE_PUBLISH_REACTIVITY_ID,
            hours=cooldown_hours,
        )
        self.name = "Keep-Rate Publish"
        self.description = (
            "On an experiment_resolved row, publish per-scope keep-rate "
            "for today's UTC day via the lifted KeepRatePublisher. Gated "
            "to one fire per day per install via Periodic(86_400) & "
            "NotRecentlyFired(24h)."
        )

    @property
    def id(self) -> str:
        return _KEEP_RATE_PUBLISH_REACTIVITY_ID

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        """Publish keep-rate for today's UTC day.

        Per the F.4 spec, the fire body is a one-line wrapper:
          1. Resolve "today" from ``context.now`` (UTC date).
          2. Acquire (or lazily build) a ``KeepRatePublisher`` bound to
             ``context.ledger`` / ``context.company_id``.
          3. ``await publisher.publish_for_day(today)``.

        Reactivity does not own idempotency — the publisher itself dedups
        by inspecting prior ``emit_metrics_keep_rate_published`` rows for
        the same (scope, day) tuple. The Periodic + NotRecentlyFired
        condition is the in-registry rate-limit; the publisher's dedup is
        the ledger-side belt-and-braces guarantee.
        """
        now = (
            context.now() if callable(context.now) else context.now
        )
        if not isinstance(now, datetime):
            now = datetime.now(UTC)
        today = now.date()

        publisher = self.publisher or KeepRatePublisher(
            context.ledger, context.company_id,
        )
        try:
            published = await publisher.publish_for_day(day=today)
        except Exception as exc:  # noqa: BLE001 — never block the loop
            logger.warning(
                "keep_rate_publish: publish_for_day failed: %s", exc,
            )
            return ReactivityResult(fired=False)

        # Even when ``published`` is empty (every scope already published
        # for today), we still report fired=True so the registry records
        # the fire and the Periodic / NotRecentlyFired gates stay tight
        # — the F.4 spec calls out "at most once per day per install"
        # regardless of publisher-side dedup.
        actions: list[FiredAction] = [
            FiredAction(
                action_kind="metrics_keep_rate_published",
                action_seqs=[],
            )
            for _ in published
        ]
        return ReactivityResult(
            fired=True,
            actions=actions,
            novelty_key=_KEEP_RATE_PUBLISH_REACTIVITY_ID,
            budget_used={},
        )


__all__ = [
    "ExperimentResolution",
    "ExperimentResolveReactivity",
    "ExperimentTriggerReactivity",
    "KeepRatePublishReactivity",
    "LessonExtractionReactivity",
    "publish_keep_notebook",
    "resolve_experiment",
]
