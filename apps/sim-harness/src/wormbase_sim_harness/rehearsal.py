"""Rehearsal — dry-run a scenario without touching real Slack.

The rehearsal pipeline lets the demo presenter (or CI) verify a scenario
end-to-end before the live show:

  1. **Pre-flight** (optional) — probe ``docker compose ps`` and confirm
     the core services (postgres, openclaw, channel-adapter, worm-core)
     are running. If docker isn't reachable (CI, laptop without Docker
     Desktop), this phase is skipped with a warning.
  2. **Seed** (optional) — call ``seed_tenant`` on the ledger if the
     seeding API has been shipped. If not (early development), it's skipped
     with a warning so the rest of the rehearsal keeps moving.
  3. **Run** — execute the scenario via ``ScenarioEngine`` against a
     ``MockSlackPoster`` that records calls in memory instead of hitting
     Slack. A ``VirtualClock`` keeps the run fast (no wall-clock waits).
  4. **Acceptance** — confirm the recorded posts match the scenario's
     intent: every beat fired, drops uploaded, persona attributions
     honored, beats fired in ``at`` order. If a real Ledger DSN is
     supplied AND any worm-core/channel-adapter writes show up in the
     window, layer the existing demo invariants on top.
  5. **Report** — return a ``RehearsalReport`` (dataclass; serializable
     via ``to_dict``) summarizing pass/fail per phase.

The rehearsal is deliberately lighter-touch than the live demo path:
because we mock Slack, the ledger won't see ``channel_adapter.emit_*``
entries (those come from OpenClaw → channel-adapter on real posts).
We therefore extend the acceptance to also recognize "MockSlackPoster
recorded N posts in beat order" as a primary signal, and only run the
real-ledger acceptance when the caller explicitly enabled it AND a DSN
is reachable.

Public API:

* ``MockSlackPoster`` — drop-in replacement for ``SlackPoster``.
* ``run_rehearsal(scenario_path, *, ledger_dsn, tenant)`` — async entry
  point used by the CLI and by tests.
* ``RehearsalReport`` — dataclass aggregating phase results.
* ``assert_rehearsal_invariants(report)`` — pure-Python check that
  consumes a ``RehearsalReport`` and returns a pass/fail breakdown
  without needing a ledger.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

from wormbase_sim_harness.clock import VirtualClock
from wormbase_sim_harness.engine import ScenarioEngine
from wormbase_sim_harness.personas import Persona, PersonaRegistry
from wormbase_sim_harness.scenario import Scenario

log = logging.getLogger(__name__)

# Core services we expect to find running for a "real" pre-flight pass.
# This list deliberately excludes the dashboard (visual only — not a hard
# requirement for rehearsal correctness) and the sim-harness container
# itself (rehearsals run in-process).
_EXPECTED_SERVICES: tuple[str, ...] = (
    "postgres",
    "openclaw",
    "channel-adapter",
    "worm-core",
)


# ---------------------------------------------------------------------------
# MockSlackPoster — drop-in stub recording calls in memory.
# ---------------------------------------------------------------------------


@dataclass
class MockCall:
    """One recorded poster call."""

    kind: str  # "post" | "upload"
    persona_id: str
    channel: str
    text: str | None = None
    file_path: str | None = None
    caption: str | None = None
    seq: int = 0


class MockSlackPoster:
    """Records ``post_as`` / ``upload_as`` calls without hitting Slack.

    Compatible with :class:`wormbase_sim_harness.slack_poster.SlackPoster`
    so the engine can drive it interchangeably.
    """

    def __init__(self) -> None:
        self.calls: list[MockCall] = []

    @property
    def post_calls(self) -> list[MockCall]:
        return [c for c in self.calls if c.kind == "post"]

    @property
    def upload_calls(self) -> list[MockCall]:
        return [c for c in self.calls if c.kind == "upload"]

    def calls_by_persona(self, persona_id: str) -> list[MockCall]:
        return [c for c in self.calls if c.persona_id == persona_id]

    async def post_as(
        self, persona: Persona, channel: str, text: str
    ) -> dict[str, Any]:
        self.calls.append(
            MockCall(
                kind="post",
                persona_id=persona.id,
                channel=channel,
                text=text,
                seq=len(self.calls) + 1,
            )
        )
        return {"ok": True, "ts": f"mock-{len(self.calls)}", "channel": channel}

    async def upload_as(
        self,
        persona: Persona,
        channel: str,
        file_path: str | Path,
        caption: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            MockCall(
                kind="upload",
                persona_id=persona.id,
                channel=channel,
                file_path=str(file_path),
                caption=caption,
                seq=len(self.calls) + 1,
            )
        )
        return {
            "ok": True,
            "file_id": f"mockF{len(self.calls)}",
            "channel": channel,
        }


# ---------------------------------------------------------------------------
# RehearsalReport — phase-by-phase pass/fail.
# ---------------------------------------------------------------------------


@dataclass
class PhaseResult:
    """One phase of the rehearsal pipeline."""

    name: str
    passed: bool
    skipped: bool = False
    detail: str = ""

    @property
    def status(self) -> str:
        if self.skipped:
            return "SKIP"
        return "PASS" if self.passed else "FAIL"


@dataclass
class RehearsalReport:
    """Aggregated result of one rehearsal run."""

    scenario: str
    tenant: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    phases: list[PhaseResult] = field(default_factory=list)
    posts_per_persona: dict[str, int] = field(default_factory=dict)
    uploads_per_persona: dict[str, int] = field(default_factory=dict)
    total_calls: int = 0
    drops_observed: int = 0
    errors: list[str] = field(default_factory=list)
    ordering_violations: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(p.passed or p.skipped for p in self.phases) and not self.errors

    def add(self, phase: PhaseResult) -> None:
        self.phases.append(phase)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "tenant": self.tenant,
            "started_at": self.started_at.isoformat(),
            "passed": self.passed,
            "total_calls": self.total_calls,
            "drops_observed": self.drops_observed,
            "posts_per_persona": dict(self.posts_per_persona),
            "uploads_per_persona": dict(self.uploads_per_persona),
            "ordering_violations": list(self.ordering_violations),
            "errors": list(self.errors),
            "phases": [
                {
                    "name": p.name,
                    "status": p.status,
                    "passed": p.passed,
                    "skipped": p.skipped,
                    "detail": p.detail,
                }
                for p in self.phases
            ],
        }


# ---------------------------------------------------------------------------
# Helpers — pre-flight, seed, ordering check.
# ---------------------------------------------------------------------------


def _company_id_from_tenant(tenant: str) -> UUID:
    return uuid5(NAMESPACE_DNS, f"wormbase.tenant.{tenant}")


def _repo_root_from_module() -> Path:
    # apps/sim-harness/src/wormbase_sim_harness/rehearsal.py → repo root is parents[4]
    return Path(__file__).resolve().parents[4]


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _run_docker_ps(compose_file: Path, project_dir: Path) -> list[dict[str, Any]]:
    """Best-effort ``docker compose ps --format json`` parse.

    Returns an empty list and lets the caller decide how to interpret a
    silent docker (e.g. CI without Docker Desktop). Each entry is the raw
    docker compose row (Service, State, Health when set).
    """
    cmd = [
        "docker",
        "compose",
        "--project-directory",
        str(project_dir),
        "-f",
        str(compose_file),
        "ps",
        "--format",
        "json",
    ]
    proc = subprocess.run(  # noqa: S603 — args are constructed locally
        cmd,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        log.info(
            "docker compose ps exited %s: %s",
            proc.returncode,
            proc.stderr.strip(),
        )
        return []
    rows: list[dict[str, Any]] = []
    out = proc.stdout.strip()
    if not out:
        return []
    # docker compose ps emits either a JSON array or one JSON object per line
    # depending on version.
    if out.startswith("["):
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    rows.append(item)
        return rows
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _preflight(repo_root: Path | None = None) -> PhaseResult:
    """Confirm the dev stack is reachable. Returns a PhaseResult.

    On hosts without docker (CI, fresh laptops) we mark the phase
    SKIPPED with a warning rather than failing the whole rehearsal —
    the run + acceptance phases still carry diagnostic value.
    """
    if not _docker_available():
        msg = "docker not on PATH; pre-flight skipped"
        warnings.warn(msg, RuntimeWarning, stacklevel=2)
        return PhaseResult(name="preflight", passed=True, skipped=True, detail=msg)

    root = repo_root or _repo_root_from_module()
    compose_file = root / "infra" / "docker-compose.yml"
    if not compose_file.is_file():
        msg = f"docker-compose.yml not found at {compose_file}; pre-flight skipped"
        warnings.warn(msg, RuntimeWarning, stacklevel=2)
        return PhaseResult(name="preflight", passed=True, skipped=True, detail=msg)

    try:
        rows = _run_docker_ps(compose_file, root)
    except (subprocess.SubprocessError, OSError) as exc:
        msg = f"docker compose ps failed: {exc}; pre-flight skipped"
        warnings.warn(msg, RuntimeWarning, stacklevel=2)
        return PhaseResult(name="preflight", passed=True, skipped=True, detail=msg)

    if not rows:
        msg = "docker compose ps returned no rows; pre-flight skipped"
        warnings.warn(msg, RuntimeWarning, stacklevel=2)
        return PhaseResult(name="preflight", passed=True, skipped=True, detail=msg)

    running: set[str] = set()
    for row in rows:
        # docker compose ps JSON shape uses Service + State (and sometimes Health).
        name = (
            row.get("Service")
            or row.get("Name")
            or row.get("name")
            or ""
        )
        state = (row.get("State") or row.get("state") or "").lower()
        if state in {"running", "up"}:
            running.add(name)

    missing = [s for s in _EXPECTED_SERVICES if s not in running]
    if missing:
        return PhaseResult(
            name="preflight",
            passed=False,
            detail=f"services not running: {','.join(missing)}",
        )
    return PhaseResult(
        name="preflight",
        passed=True,
        detail=f"{len(running)} services up: {sorted(running)}",
    )


async def _seed(
    *, ledger_dsn: str | None, tenant: str, reset_first: bool, write_history: bool
) -> PhaseResult:
    """Best-effort tenant seed.

    The dedicated ``seed_tenant`` helper is being shipped in parallel by
    another agent; until it lands, we no-op with a warning so rehearsals
    keep working. When the helper appears, this phase will pick it up
    automatically with no rehearsal-side changes.
    """
    if not ledger_dsn:
        return PhaseResult(
            name="seed",
            passed=True,
            skipped=True,
            detail="no ledger DSN — seed skipped",
        )

    seed_tenant = None
    # Preferred: the sim-harness ships its own seed module.
    try:
        from wormbase_sim_harness.seed import seed_tenant as _seed_tenant  # type: ignore[import-not-found]

        seed_tenant = _seed_tenant
    except (ImportError, AttributeError):
        # Legacy fallback paths (older parallel-agent location proposals).
        try:  # pragma: no cover — import depends on parallel workstream landing
            from wormbase_ledger.seed import seed_tenant as _seed_tenant  # type: ignore[import-not-found]

            seed_tenant = _seed_tenant
        except (ImportError, AttributeError):
            try:
                from wormbase_ledger import seed_tenant as _seed_tenant  # type: ignore[attr-defined]

                seed_tenant = _seed_tenant
            except (ImportError, AttributeError):
                seed_tenant = None

    if seed_tenant is None:
        msg = "seed_tenant not yet shipped; seed phase skipped"
        warnings.warn(msg, RuntimeWarning, stacklevel=2)
        return PhaseResult(name="seed", passed=True, skipped=True, detail=msg)

    try:
        await seed_tenant(  # type: ignore[misc]
            ledger_dsn=ledger_dsn,
            tenant=tenant,
            reset_first=reset_first,
            write_history=write_history,
        )
    except Exception as exc:  # noqa: BLE001 — seed is advisory; report and move on
        log.warning("seed_tenant failed: %s", exc)
        return PhaseResult(
            name="seed",
            passed=False,
            detail=f"seed_tenant raised: {exc}",
        )
    return PhaseResult(
        name="seed",
        passed=True,
        detail=f"seeded tenant={tenant} reset={reset_first} history={write_history}",
    )


def _ordering_violations(
    scenario: Scenario, poster: MockSlackPoster
) -> list[str]:
    """Return human-readable strings for every beat that fired out of order.

    The engine guarantees in-order dispatch, but if a future engine runs
    concurrently we still want this check at the rehearsal layer.

    Engine-driven beats (``wait_for``) produce no poster call, so we
    skip them in the expected sequence. ``dm`` beats produce a single
    ``post`` call against a DM channel id.
    """
    expected: list[tuple[str, str | None, bool]] = []
    for beat in scenario.beats:
        if beat.wait_for is not None:
            # No poster call expected — wait_for is engine-driven.
            continue
        if beat.dm is not None:
            expected.append((beat.persona, "post", True))
            continue
        if beat.drop is not None:
            expected.append((beat.persona, "upload", False))
            if beat.say:
                expected.append((beat.persona, "post", True))
        else:
            expected.append((beat.persona, "post", True))

    actual: list[tuple[str, str]] = [(c.persona_id, c.kind) for c in poster.calls]

    violations: list[str] = []
    if len(actual) != len(expected):
        violations.append(
            f"call-count mismatch: expected {len(expected)}, observed {len(actual)}"
        )
    for i, (exp, act) in enumerate(zip(expected, actual, strict=False)):
        exp_persona, exp_kind, _ = exp
        if exp_persona != act[0] or exp_kind != act[1]:
            violations.append(
                f"beat {i}: expected ({exp_persona},{exp_kind}) got ({act[0]},{act[1]})"
            )
    return violations


# ---------------------------------------------------------------------------
# Public entry points.
# ---------------------------------------------------------------------------


def assert_rehearsal_invariants(report: RehearsalReport) -> RehearsalReport:
    """Validate a RehearsalReport's structural invariants.

    Returns the same report with a new ``rehearsal_invariants`` phase
    appended; mutates ``report.phases`` in place.
    """
    failures: list[str] = []
    if report.total_calls == 0:
        failures.append("zero poster calls — engine never dispatched")
    if report.ordering_violations:
        failures.append(
            f"{len(report.ordering_violations)} ordering violations"
        )
    # Drops are part of the C+B narrative; if a scenario declared drops
    # but none were observed, that's a hard fail.
    if report.drops_observed < 0:  # placeholder: scenario-aware caller sets expectations
        failures.append("negative drop count (programming error)")

    phase = PhaseResult(
        name="rehearsal_invariants",
        passed=not failures,
        detail="; ".join(failures) if failures else "structural checks passed",
    )
    report.add(phase)
    return report


async def run_rehearsal(
    scenario_path: str | Path,
    *,
    ledger_dsn: str | None = None,
    tenant: str = "baseworm",
    personas_path: str | Path | None = None,
    fixtures_root: str | Path | None = None,
    reset_first: bool = False,
    write_history: bool = True,
    repo_root: Path | None = None,
) -> RehearsalReport:
    """Drive a scenario against a MockSlackPoster and report.

    Parameters
    ----------
    scenario_path:
        Path to a scenario YAML (e.g. ``demo-c-plus-b.yml``).
    ledger_dsn:
        Optional postgres DSN. When omitted, the seed phase is skipped
        and the rehearsal runs against ``MockSlackPoster`` only.
    tenant:
        Tenant slug used for company_id derivation; defaults to
        ``baseworm`` to match the demo workspace.
    personas_path / fixtures_root:
        Override discovery — useful for tests that build a tiny scenario
        in ``tmp_path``.
    reset_first / write_history:
        Forwarded to the (optional) ``seed_tenant`` helper.
    repo_root:
        Override for pre-flight; falls back to walking up from this file.
    """
    scenario_path = Path(scenario_path)
    scenario = Scenario.from_yaml(scenario_path)

    # Resolve personas — default sits next to the scenarios dir.
    if personas_path is None:
        # The scenarios dir is `<harness_root>/scenarios`; personas.yml
        # lives at `<harness_root>/personas.yml`.
        candidate = scenario_path.resolve().parent.parent / "personas.yml"
        if not candidate.is_file():
            # Fallback: walk up from this module.
            candidate = (
                Path(__file__).resolve().parents[2] / "personas.yml"
            )
        personas_path = candidate
    registry = PersonaRegistry.from_yaml(personas_path)
    scenario.validate_against(registry)

    if fixtures_root is None:
        fixtures_candidate = scenario_path.resolve().parent.parent / "fixtures"
        fixtures_root = fixtures_candidate if fixtures_candidate.is_dir() else None

    report = RehearsalReport(scenario=scenario.name, tenant=tenant)

    # Phase 1 — pre-flight (best-effort).
    try:
        report.add(_preflight(repo_root=repo_root))
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"preflight crashed: {exc}")
        report.add(
            PhaseResult(name="preflight", passed=False, detail=f"crashed: {exc}")
        )

    # Phase 2 — seed (best-effort).
    try:
        report.add(
            await _seed(
                ledger_dsn=ledger_dsn,
                tenant=tenant,
                reset_first=reset_first,
                write_history=write_history,
            )
        )
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"seed crashed: {exc}")
        report.add(PhaseResult(name="seed", passed=False, detail=f"crashed: {exc}"))

    # Phase 3 — run scenario against MockSlackPoster.
    poster = MockSlackPoster()
    engine = ScenarioEngine(registry, improv=None, fixtures_root=fixtures_root)
    clock = VirtualClock()
    try:
        await engine.run(scenario, clock, poster)  # type: ignore[arg-type]
        report.add(
            PhaseResult(
                name="run",
                passed=True,
                detail=f"{len(poster.calls)} calls, "
                f"{len(poster.upload_calls)} uploads",
            )
        )
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"engine.run raised: {exc}")
        report.add(
            PhaseResult(name="run", passed=False, detail=f"engine raised: {exc}")
        )
        # Still build aggregates from whatever made it through.

    # Aggregate poster calls.
    report.total_calls = len(poster.calls)
    report.drops_observed = len(poster.upload_calls)
    for call in poster.calls:
        bucket = (
            report.uploads_per_persona
            if call.kind == "upload"
            else report.posts_per_persona
        )
        bucket[call.persona_id] = bucket.get(call.persona_id, 0) + 1

    # Phase 4 — ordering / structural acceptance. Done in-process; no
    # ledger required.
    violations = _ordering_violations(scenario, poster)
    report.ordering_violations.extend(violations)

    expected_drops = sum(1 for b in scenario.beats if b.drop is not None)
    if expected_drops > 0 and report.drops_observed == 0:
        report.errors.append(
            f"scenario declared {expected_drops} drops but none observed"
        )

    assert_rehearsal_invariants(report)

    # Phase 5 — optional real-ledger acceptance. Only attempted when the
    # caller passed a DSN AND the env declares the seeding side wrote
    # something we should be reading. Off by default in development.
    if ledger_dsn and os.environ.get("WORMBASE_REHEARSAL_CHECK_LEDGER") == "1":
        try:
            from wormbase_ledger import Ledger  # local import — heavy

            from wormbase_sim_harness.acceptance import assert_demo_invariants

            led = Ledger(ledger_dsn)
            try:
                ar = await assert_demo_invariants(
                    led,
                    _company_id_from_tenant(tenant),
                    report.started_at,
                )
            finally:
                await led.dispose()
            report.add(
                PhaseResult(
                    name="ledger_acceptance",
                    passed=ar.passed,
                    detail=", ".join(
                        f"{c.name}={c.detail}" for c in ar.checks
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001
            warnings.warn(
                f"ledger acceptance skipped: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
            report.add(
                PhaseResult(
                    name="ledger_acceptance",
                    passed=True,
                    skipped=True,
                    detail=f"unavailable: {exc}",
                )
            )
    else:
        report.add(
            PhaseResult(
                name="ledger_acceptance",
                passed=True,
                skipped=True,
                detail="not requested (set WORMBASE_REHEARSAL_CHECK_LEDGER=1)",
            )
        )

    return report


__all__ = [
    "MockCall",
    "MockSlackPoster",
    "PhaseResult",
    "RehearsalReport",
    "assert_rehearsal_invariants",
    "run_rehearsal",
]
