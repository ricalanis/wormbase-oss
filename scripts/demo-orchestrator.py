#!/usr/bin/env python3
"""Demo orchestrator with per-beat auto-recovery (W3.A11).

Wraps the canonical 7+1 beat install-arc scenario so that
``make demo`` succeeds first try, every try.

For each beat:

1. Start the beat (post message / drop file / wait_for ledger entry)
   by running ``wormbase demo run --script <single-beat-slice>`` inside
   the sim-harness service.
2. Wait for the beat's expected ledger entries with a hard timeout.
3. On timeout: detect which side stalled by running short health
   probes (worm-core ``/api/v1/health``, dashboard ``/``, channel
   adapter container state, postgres TCP).
4. Auto-recover via ``make worm-restart`` / ``make adapter-restart``
   per the beat's ``failure_recovery`` directive in the YAML, then
   re-run the beat once.
5. If the second attempt fails, fall back to wire-replay for THAT
   beat using ``apps/sim-harness/fixtures/install-arc-7beat-canonical.jsonl``
   filtered by ``beat_index``. Same code path as the live
   channel-adapter — wire-replay is the only deterministic backstop
   per the project quality bar (no flow-bypass).
6. If wire-replay also fails: halt with a clear "human-in-the-loop
   required" message; preserve stack state.

Beat 8 has its own canonical recovery hook
(``scripts/demo/mcp_beat8_run.sh``); for that beat the orchestrator
runs the helper script BEFORE wire-replay.

Quality bar:

* No flow-bypass — every fallback path goes through the live
  channel-adapter. Wire-replay is the only acceptable determinism
  backstop.
* Recovery actions are timestamped log lines so the narrator can
  reference them on stage.
* The orchestrator exits non-zero if the demo could not complete;
  the operator's error message names the specific beat + recovery
  paths attempted.

Usage:

    python scripts/demo-orchestrator.py --scenario install-arc-7beat \
        --pace wall

Environment overrides:

    WORMBASE_DEMO_SKIP_RUN=1     # dry-run mode (parse + plan, no compose calls)
    WORMBASE_DEMO_FAIL_BEAT=2    # force the named 1-based beat index to time
                                  # out on first attempt (sandbox testing)
    WORMBASE_DEMO_FAIL_RECOVERY=1 # force the recovery attempt to fail too
                                  # (drives the wire-replay fallback path)
    WORMBASE_DEMO_FAIL_REPLAY=1  # force wire-replay to fail (halts run)
    WORMBASE_DEMO_RUNNER=path    # override the wormbase-demo-run subprocess
                                  # (used by tests to inject mock behaviour)
    WORMBASE_DEMO_SKIP_INSTALLED_FAKE=...
                                  # sandbox testing helper for the
                                  # ``--skip-installed`` probe — see
                                  # ``_probe_existing_install`` below.

Skip-installed mode (W7.A3)
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Beat 1 of the install-arc scenario waits for ``emit_install_completed``,
which is only emitted after a human clicks through the OAuth consent
screen at ``/onboarding``. The orchestrator cannot script the click,
so when the operator runs ``make demo`` after a one-time OAuth seed
(``make seed --install-from-env`` writes the same install row), the
orchestrator should resume from the first non-OAuth beat.

``--skip-installed`` (default ``true``) probes
``GET /api/v1/installs`` for the current tenant. When at least one
``status=active`` install row exists, every beat marked
``skippable_if_pre_installed: true`` in the YAML is skipped with a
clear log line. ``--no-skip-installed`` forces the full arc even when
an install exists.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIO = "install-arc-7beat"
SCENARIOS_DIR = REPO_ROOT / "apps" / "sim-harness" / "scenarios"
FIXTURES_DIR = REPO_ROOT / "apps" / "sim-harness" / "fixtures"
CANONICAL_FIXTURE = FIXTURES_DIR / "install-arc-7beat-canonical.jsonl"
MCP_BEAT8_SCRIPT = REPO_ROOT / "scripts" / "demo" / "mcp_beat8_run.sh"


# ──────────────────────────────────────────────────────────────────────
# Logging — every line carries a wall-clock timestamp so the narrator
# can correlate recovery actions with on-stage cues.
# ──────────────────────────────────────────────────────────────────────


def _setup_logging(level: str = "INFO") -> logging.Logger:
    fmt = "%(asctime)s.%(msecs)03dZ [orchestrator] %(message)s"
    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )
    # Use UTC for the asctime field, matching the ledger's tz-aware ts.
    logging.Formatter.converter = time.gmtime
    return logging.getLogger("wormbase.demo.orchestrator")


# ──────────────────────────────────────────────────────────────────────
# Data classes — beat metadata + run telemetry.
# ──────────────────────────────────────────────────────────────────────


@dataclass
class BeatPlan:
    """One scenario beat as the orchestrator sees it."""

    index: int                       # 1-based for human-friendly logs
    at: float
    kind: str                        # post | upload | dm | wait_for
    description: str
    raw: dict[str, Any]              # YAML dict (forwarded to engine)
    failure_recovery: str            # worm-restart | adapter-restart | beat8-script | none
    timeout_s: float
    # W7.A3 — beats marked ``skippable_if_pre_installed: true`` in the
    # scenario YAML are skipped when ``--skip-installed`` is in effect
    # AND the orchestrator's pre-flight probe finds an active install
    # row for the target tenant. Beats without the flag run normally
    # even when an install exists, so non-OAuth beats can still be
    # exercised against a pre-seeded tenant.
    skippable_if_pre_installed: bool = False


@dataclass
class BeatOutcome:
    """Result of running one beat (with all recovery attempts)."""

    beat_index: int
    description: str
    attempts: list[str] = field(default_factory=list)
    succeeded: bool = False
    # "first-try" | "<recovery>" | "wire-replay" | "halted" |
    # "skipped-pre-installed" (W7.A3)
    final_path: str = "unrun"
    error: str | None = None
    started_at: str = ""
    finished_at: str = ""
    # W7.A3 — populated when the beat was skipped due to the
    # ``--skip-installed`` pre-flight probe finding an active install.
    skip_reason: str | None = None


@dataclass
class RunReport:
    scenario: str
    pace: str
    started_at: str
    finished_at: str = ""
    beats: list[BeatOutcome] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(b.succeeded for b in self.beats)


# ──────────────────────────────────────────────────────────────────────
# Scenario loading + per-beat slicing.
# ──────────────────────────────────────────────────────────────────────


def _scenario_path(scenario: str) -> Path:
    p = Path(scenario)
    if p.is_file():
        return p
    candidate = SCENARIOS_DIR / f"{scenario}.yml"
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(
        f"scenario not found: {scenario} "
        f"(checked: {p}, {candidate})"
    )


def _describe_beat(idx: int, raw: dict[str, Any]) -> tuple[str, str]:
    """Return (kind, human-readable description) for a beat."""
    if raw.get("wait_for") is not None:
        wf = raw["wait_for"]
        tool = wf if isinstance(wf, str) else wf.get("tool", "?")
        return "wait_for", f"#{idx} wait_for {tool}"
    if raw.get("drop") is not None:
        persona = raw.get("persona", "?")
        fname = (raw["drop"] or {}).get("file", "?")
        return "upload", f"#{idx} {persona} drops {fname}"
    if raw.get("dm") is not None:
        persona = raw.get("persona", "?")
        return "dm", f"#{idx} {persona} DMs the worm"
    if raw.get("say") is not None:
        persona = raw.get("persona", "?")
        text = raw["say"][:48].replace("\n", " ")
        return "post", f"#{idx} {persona} says \"{text}\""
    return "unknown", f"#{idx} (unknown beat)"


def _beat_timeout(raw: dict[str, Any]) -> float:
    # wait_for with structured form carries timeout_s on the WaitFor;
    # bare-string wait_for carries it as a sibling. say/drop/dm beats
    # don't have an intrinsic ledger-level timeout, so we use a wall-clock
    # default: 30s for messages, 60s for file uploads.
    wf = raw.get("wait_for")
    if isinstance(wf, dict):
        return float(wf.get("timeout_s", 30.0))
    if isinstance(wf, str) and "timeout_s" in raw:
        return float(raw["timeout_s"])
    if isinstance(wf, str):
        return 30.0
    if raw.get("drop") is not None:
        return 60.0
    if raw.get("dm") is not None:
        return 30.0
    return 30.0


def load_scenario_plan(scenario: str) -> tuple[Path, list[BeatPlan], dict[str, Any]]:
    """Load the YAML and return per-beat plans + the parsed scenario dict."""
    path = _scenario_path(scenario)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"scenario {path} is not a YAML mapping")
    beats_raw: Iterable[dict[str, Any]] = raw.get("beats") or []
    plans: list[BeatPlan] = []
    for i, b in enumerate(beats_raw, start=1):
        kind, descr = _describe_beat(i, b)
        plans.append(
            BeatPlan(
                index=i,
                at=float(b.get("at", 0.0)),
                kind=kind,
                description=descr,
                raw=b,
                failure_recovery=str(b.get("failure_recovery") or "none"),
                timeout_s=_beat_timeout(b),
                skippable_if_pre_installed=bool(
                    b.get("skippable_if_pre_installed", False)
                ),
            )
        )
    return path, plans, raw


def write_single_beat_scenario(
    *,
    out_path: Path,
    scenario_dict: dict[str, Any],
    beat: BeatPlan,
) -> None:
    """Materialize a single-beat slice as a complete scenario YAML.

    The slice rebases ``at`` to 0 so the engine doesn't burn wall-clock
    seconds re-walking earlier beats; orchestration manages timing
    between beats explicitly.
    """
    sliced_beat = dict(beat.raw)  # shallow copy
    sliced_beat["at"] = 0
    # Strip the orchestrator-only directive — the sim-harness engine
    # ignores extras but keeping the YAML clean helps when debugging.
    sliced_beat.pop("failure_recovery", None)
    sliced = {
        "name": f"{scenario_dict.get('name', 'scenario')}-beat-{beat.index}",
        "description": (
            f"Single-beat slice for {beat.description}. "
            f"Generated by scripts/demo-orchestrator.py."
        ),
        "default_channel": scenario_dict.get("default_channel", "#general"),
        "beats": [sliced_beat],
    }
    out_path.write_text(yaml.safe_dump(sliced, sort_keys=False), encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────
# Health probes — read-only, short-timeout, never restart anything.
# ──────────────────────────────────────────────────────────────────────


def _http_probe(url: str, timeout_s: float = 2.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            return resp.status == 200, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        # 404 is honest-empty for some endpoints (MCP catalog when disabled).
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError) as exc:
        return False, f"unreachable ({exc})"


# ──────────────────────────────────────────────────────────────────────
# W7.A3 — install detection.
#
# `--skip-installed` queries `GET /api/v1/installs` against worm-core
# and returns the list of active installs. The orchestrator uses this
# to decide whether to skip the OAuth-click beats (1a/1b in the
# install-arc-7beat scenario).
#
# The probe is intentionally tolerant: a network flake or 5xx falls
# back to running every beat (the operator gets the full arc, plus a
# logged warning). Only an unambiguous "install exists" answer triggers
# skipping.
# ──────────────────────────────────────────────────────────────────────


@dataclass
class InstallProbeResult:
    """Outcome of the pre-flight install probe.

    `state` ∈ {"present", "absent", "unknown"}.

    - ``present`` — at least one ``status=active`` install row was
      returned. ``installs`` carries the rows so the log can name the
      ``install_id`` of the row that triggered the skip.
    - ``absent`` — the endpoint returned an empty list. Run all beats.
    - ``unknown`` — the endpoint failed (network, 5xx, JSON parse).
      Run all beats and warn so the operator can investigate.
    """

    state: str
    installs: list[dict[str, Any]] = field(default_factory=list)
    detail: str = ""


_INSTALLS_ENDPOINT_DEFAULT = "http://localhost:8910/api/v1/installs"


def _probe_existing_install(
    *,
    log: logging.Logger,
    sandbox: bool,
    runner: _SandboxRunner | None,
    tenant_slug: str | None = None,
    api_token: str | None = None,
    endpoint: str | None = None,
    timeout_s: float = 5.0,
) -> InstallProbeResult:
    """Query ``GET /api/v1/installs`` and return the parsed result.

    Sandbox mode is driven by the
    ``WORMBASE_DEMO_SKIP_INSTALLED_FAKE`` env var so the test suite can
    exercise every branch deterministically:

      - ``present``  → return one fake active install row
      - ``absent``   → return an empty list
      - ``unknown``  → return a probe failure (forces run-all-beats +
                       warning log)

    In real runs the function builds an authenticated request against
    worm-core's HTTP API. The orchestrator's bearer token defaults to
    the local-dev token; the tenant slug defaults to ``baseworm``.
    """
    if sandbox:
        fake = os.environ.get("WORMBASE_DEMO_SKIP_INSTALLED_FAKE", "absent")
        if fake == "present":
            row = {
                "install_id": "00000000-0000-4000-8000-000000000001",
                "platform": "slack",
                "installer_person_id": "00000000-0000-4000-8000-000000000002",
                "installed_at": "2026-04-29T00:00:00+00:00",
                "status": "active",
                "scopes": ["channels:read", "chat:write"],
                "bot_user_id": "UBOT",
                "oauth_grant_ref": "vault://local-dev/sandbox",
            }
            log.info(
                "[sandbox] /api/v1/installs probe → present "
                "(fake install id=%s)", row["install_id"],
            )
            return InstallProbeResult(state="present", installs=[row])
        if fake == "unknown":
            log.info("[sandbox] /api/v1/installs probe → unknown (forced)")
            return InstallProbeResult(state="unknown", detail="sandbox: forced unknown")
        log.info("[sandbox] /api/v1/installs probe → absent")
        return InstallProbeResult(state="absent")

    url = (
        endpoint
        or os.environ.get("WORMBASE_INSTALLS_API")
        or _INSTALLS_ENDPOINT_DEFAULT
    )
    token = (
        api_token
        or os.environ.get("WORMBASE_LEDGER_API_TOKEN", "").strip()
        or "dev-only-token-rotate-in-prod"
    )
    slug = (
        tenant_slug
        or os.environ.get("WORMBASE_TENANT_SLUG", "").strip()
        or "baseworm"
    )

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "X-Tenant-Slug": slug,
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            if resp.status != 200:
                detail = f"HTTP {resp.status}"
                log.warning(
                    "  install probe non-200 (%s); will run every beat",
                    detail,
                )
                return InstallProbeResult(state="unknown", detail=detail)
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # 401 / 422 / 5xx — distinguish "no install" from other errors.
        # A 404 is honest-empty for old worm-core builds without the
        # endpoint; treat as absent so demos against pre-W7.A3 builds
        # still work, but log loud enough for the operator to notice.
        if exc.code == 404:
            log.warning(
                "  install probe 404 — worm-core may predate W7.A3. "
                "Treating as absent; running every beat.",
            )
            return InstallProbeResult(state="absent", detail="HTTP 404")
        detail = f"HTTP {exc.code}"
        log.warning("  install probe %s; will run every beat", detail)
        return InstallProbeResult(state="unknown", detail=detail)
    except (urllib.error.URLError, OSError) as exc:
        log.warning(
            "  install probe failed (%s); will run every beat", exc,
        )
        return InstallProbeResult(state="unknown", detail=f"unreachable: {exc}")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        log.warning(
            "  install probe returned non-JSON (%s); will run every beat",
            exc,
        )
        return InstallProbeResult(state="unknown", detail=f"json: {exc}")

    rows = payload.get("installs") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        log.warning(
            "  install probe payload missing 'installs' array; "
            "will run every beat",
        )
        return InstallProbeResult(
            state="unknown", detail="payload-missing-installs",
        )

    active = [
        r for r in rows
        if isinstance(r, dict) and r.get("status") == "active"
    ]
    if not active:
        return InstallProbeResult(state="absent", installs=rows, detail="no-active")
    return InstallProbeResult(state="present", installs=active)


def detect_failure_mode() -> dict[str, Any]:
    """Probe each service; return a small JSON-ish dict the log can carry."""
    worm_ok, worm_detail = _http_probe("http://localhost:8910/api/v1/health")
    dash_ok, dash_detail = _http_probe("http://localhost:3000/")
    mode = "unknown"
    if not worm_ok and dash_ok:
        mode = "worm-core-down"
    elif worm_ok and not dash_ok:
        mode = "dashboard-down"
    elif worm_ok and dash_ok:
        mode = "wire-stalled"
    elif not worm_ok and not dash_ok:
        mode = "stack-down"
    return {
        "mode": mode,
        "worm_core": {"ok": worm_ok, "detail": worm_detail},
        "dashboard": {"ok": dash_ok, "detail": dash_detail},
    }


# ──────────────────────────────────────────────────────────────────────
# Subprocess wrappers.
#
# We deliberately go through `make` for restart targets so the project
# Makefile remains the single source of truth for compose invocations.
# Recovery commands are echoed before they run so the operator (and
# the narrator) sees what the orchestrator chose.
# ──────────────────────────────────────────────────────────────────────


class _SandboxRunner:
    """Test-time mock: pretends to run the demo without touching docker.

    Activated by ``WORMBASE_DEMO_SKIP_RUN=1``. The orchestrator delegates
    to this when running in sandbox mode (e.g. CI integration tests
    that exercise the recovery decision-tree without a live stack).

    Honours ``WORMBASE_DEMO_FAIL_BEAT`` / ``WORMBASE_DEMO_FAIL_RECOVERY``
    / ``WORMBASE_DEMO_FAIL_REPLAY`` to drive each branch of the recovery
    state machine deterministically.
    """

    def __init__(self) -> None:
        self.fail_beat = os.environ.get("WORMBASE_DEMO_FAIL_BEAT")
        self.fail_recovery = os.environ.get("WORMBASE_DEMO_FAIL_RECOVERY") == "1"
        self.fail_replay = os.environ.get("WORMBASE_DEMO_FAIL_REPLAY") == "1"
        self.attempt_counts: dict[int, int] = {}

    def should_fail_beat(self, beat_idx: int) -> bool:
        if self.fail_beat is None:
            return False
        try:
            return int(self.fail_beat) == beat_idx
        except ValueError:
            return False

    def record_attempt(self, beat_idx: int) -> int:
        n = self.attempt_counts.get(beat_idx, 0) + 1
        self.attempt_counts[beat_idx] = n
        return n


def _run_subprocess(
    cmd: list[str],
    *,
    timeout_s: float,
    cwd: Path | None = None,
    log: logging.Logger,
) -> subprocess.CompletedProcess[str]:
    log.info("$ %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )


def run_beat_via_compose(
    *,
    scenario_yaml: Path,
    pace: str,
    timeout_s: float,
    log: logging.Logger,
    runner: _SandboxRunner | None,
    beat: BeatPlan,
) -> tuple[bool, str]:
    """Drive one beat via ``compose run --rm sim-harness wormbase demo run``.

    Returns ``(succeeded, detail)``. Detail is a short string for the log;
    on subprocess failure it carries stderr's last 200 chars.

    In sandbox mode (``WORMBASE_DEMO_SKIP_RUN=1``), the call is mocked and
    the failure switches above drive the return value.
    """
    if runner is not None:
        attempt = runner.record_attempt(beat.index)
        if runner.should_fail_beat(beat.index) and attempt == 1:
            return False, "sandbox: forced first-attempt timeout"
        if (
            runner.should_fail_beat(beat.index)
            and runner.fail_recovery
            and attempt == 2
        ):
            return False, "sandbox: forced recovery-attempt timeout"
        return True, "sandbox: simulated beat success"

    # The compose service mounts ``apps/sim-harness/scenarios`` read-only,
    # so the sliced YAML must live underneath that path. We therefore
    # write slices into a tempdir alongside the canonical scenarios dir
    # and reference them with a container-side path.
    container_path = (
        f"/workspace/apps/sim-harness/scenarios/{scenario_yaml.name}"
    )
    # The sim-harness ENTRYPOINT is already
    # ``uv run --package wormbase-sim-harness wormbase``, so we pass the
    # subcommand args directly. Repeating ``wormbase`` here would cause
    # Click to look for ``wormbase`` as a subcommand and fail with
    # ``Error: No such command 'wormbase'``.
    cmd = [
        "docker", "compose",
        "--project-directory", str(REPO_ROOT),
        "-f", str(REPO_ROOT / "infra" / "docker-compose.yml"),
        "run", "--rm",
        "sim-harness",
        "demo", "run",
        "--script", container_path,
        "--pace", pace,
        "--skip-acceptance",
    ]
    try:
        result = _run_subprocess(cmd, timeout_s=timeout_s + 30.0, log=log)
    except subprocess.TimeoutExpired as exc:
        return False, f"timed out after {exc.timeout:.0f}s"
    if result.returncode == 0:
        return True, "compose run exit 0"
    tail = (result.stderr or result.stdout or "").strip()[-200:]
    return False, f"exit {result.returncode}: {tail}"


def run_make_target(
    target: str,
    *,
    timeout_s: float,
    log: logging.Logger,
    sandbox: bool,
) -> bool:
    """Run a Makefile target. In sandbox mode, no-op + return True."""
    if sandbox:
        log.info("[sandbox] make %s (skipped)", target)
        return True
    try:
        result = _run_subprocess(
            ["make", target], timeout_s=timeout_s, log=log,
        )
    except subprocess.TimeoutExpired:
        log.error("make %s timed out after %.0fs", target, timeout_s)
        return False
    if result.returncode != 0:
        log.error(
            "make %s failed (exit %d): %s",
            target, result.returncode, (result.stderr or "").strip()[-200:],
        )
        return False
    return True


def run_wire_replay_for_beat(
    *,
    beat: BeatPlan,
    log: logging.Logger,
    sandbox: bool,
    runner: _SandboxRunner | None,
) -> tuple[bool, str]:
    """Filter the canonical fixture to this beat's events and replay them.

    Wire-replay goes through the production channel-adapter PEVR primitive
    (``WireReplayer``) — same code path as the live wire, deterministic
    input. This is the only acceptable determinism backstop per the
    project quality bar.
    """
    if not CANONICAL_FIXTURE.exists():
        return False, f"canonical fixture missing: {CANONICAL_FIXTURE}"

    # Filter the canonical JSONL down to events tagged with this beat.
    # If no events are tagged for the beat, wire-replay can't help —
    # the beat is engine-driven (wait_for) and needs the worm itself.
    matching: list[str] = []
    with CANONICAL_FIXTURE.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("beat_index") == beat.index:
                # Strip orchestrator-only metadata before replay; the
                # WireReplayer rejects unknown top-level keys benignly,
                # but a clean slice is easier to debug.
                rec.pop("beat_index", None)
                rec.pop("beat_label", None)
                matching.append(json.dumps(rec))

    if not matching:
        return False, (
            f"no canonical wire events for beat #{beat.index} "
            f"({beat.description}); this beat is engine-driven and "
            f"cannot be backstopped via wire-replay alone"
        )

    # Sandbox mode honours the FAIL_REPLAY switch.
    if sandbox and runner is not None and runner.fail_replay:
        return False, "sandbox: forced wire-replay failure"
    if sandbox:
        return True, f"sandbox: would replay {len(matching)} event(s)"

    with tempfile.TemporaryDirectory(prefix="wormbase-replay-") as tdir:
        slice_path = Path(tdir) / f"beat-{beat.index}.jsonl"
        slice_path.write_text("\n".join(matching) + "\n", encoding="utf-8")
        # The channel-adapter container mounts only its own state volume,
        # so we copy the slice into a host-visible location and bind-mount
        # it via `docker compose run` exec. Simpler: use the worm-core
        # service (which has the wormbase_channel_adapter package
        # installed) to invoke WireReplayer in-process.
        cmd = [
            "docker", "compose",
            "--project-directory", str(REPO_ROOT),
            "-f", str(REPO_ROOT / "infra" / "docker-compose.yml"),
            "run", "--rm",
            "-v", f"{slice_path}:/tmp/wire-replay.jsonl:ro",
            "sim-harness",
            "wormbase", "demo", "seed",
            "--no-personas",
            "--no-install-from-env",
            "--no-provision-local-lake",
            "--replay-history", "/tmp/wire-replay.jsonl",
        ]
        try:
            result = _run_subprocess(cmd, timeout_s=120.0, log=log)
        except subprocess.TimeoutExpired:
            return False, "wire-replay timed out"
    if result.returncode == 0:
        return True, f"wire-replay landed {len(matching)} event(s)"
    tail = (result.stderr or result.stdout or "").strip()[-200:]
    return False, f"wire-replay exit {result.returncode}: {tail}"


def run_beat8_script(
    *,
    log: logging.Logger,
    sandbox: bool,
) -> tuple[bool, str]:
    """Beat 8 has its own canonical recovery hook (Block J)."""
    if not MCP_BEAT8_SCRIPT.is_file():
        return False, f"beat-8 script missing: {MCP_BEAT8_SCRIPT}"
    if sandbox:
        return True, "sandbox: would run mcp_beat8_run.sh"
    decision_id = os.environ.get("DECISION_ID", "").strip()
    if not decision_id:
        return False, (
            "DECISION_ID env unset — beat-8 fallback needs the canonical "
            "decision id from the seeded baseworm tenant"
        )
    try:
        result = _run_subprocess(
            ["bash", str(MCP_BEAT8_SCRIPT)],
            timeout_s=120.0, log=log,
        )
    except subprocess.TimeoutExpired:
        return False, "mcp_beat8_run.sh timed out"
    if result.returncode == 0:
        return True, "mcp_beat8_run.sh exit 0"
    tail = (result.stderr or result.stdout or "").strip()[-200:]
    return False, f"mcp_beat8_run.sh exit {result.returncode}: {tail}"


# ──────────────────────────────────────────────────────────────────────
# Per-beat recovery state machine.
# ──────────────────────────────────────────────────────────────────────


def _slice_path_for(beat: BeatPlan, *, scratch: Path) -> Path:
    return scratch / f"_orchestrator-slice-beat-{beat.index}.yml"


def execute_beat(
    *,
    beat: BeatPlan,
    pace: str,
    scenario_dict: dict[str, Any],
    scratch: Path,
    log: logging.Logger,
    sandbox: bool,
    runner: _SandboxRunner | None,
) -> BeatOutcome:
    """Run one beat; on stall, follow the failure_recovery directive."""
    out = BeatOutcome(
        beat_index=beat.index,
        description=beat.description,
        started_at=datetime.now(UTC).isoformat(),
    )
    log.info(
        "─── beat %d/%d ─── %s (timeout=%.0fs, recovery=%s)",
        beat.index, len(scenario_dict.get("beats") or []),
        beat.description, beat.timeout_s, beat.failure_recovery,
    )

    # Materialize the single-beat slice into the scenarios dir so the
    # sim-harness service (which mounts the dir read-only) can find it.
    slice_path = _slice_path_for(beat, scratch=scratch)
    write_single_beat_scenario(
        out_path=slice_path,
        scenario_dict=scenario_dict,
        beat=beat,
    )

    # ─── Attempt 1: real wire ─────────────────────────────────────────
    out.attempts.append("first-try")
    ok, detail = run_beat_via_compose(
        scenario_yaml=slice_path,
        pace=pace,
        timeout_s=beat.timeout_s,
        log=log,
        runner=runner,
        beat=beat,
    )
    if ok:
        out.succeeded = True
        out.final_path = "first-try"
        out.finished_at = datetime.now(UTC).isoformat()
        log.info("  ✓ beat %d succeeded on first try (%s)", beat.index, detail)
        return out
    log.warning("  ✗ beat %d first try failed: %s", beat.index, detail)

    # ─── Diagnose ─────────────────────────────────────────────────────
    if sandbox:
        diag = {"mode": "sandbox", "worm_core": {"ok": True}, "dashboard": {"ok": True}}
    else:
        diag = detect_failure_mode()
    log.info("  diagnose: %s", json.dumps(diag, sort_keys=True))

    # ─── Attempt 2: declared recovery ─────────────────────────────────
    recovery = beat.failure_recovery
    out.attempts.append(f"recovery:{recovery}")
    if recovery == "worm-restart":
        ok_restart = run_make_target(
            "worm-restart", timeout_s=120.0, log=log, sandbox=sandbox,
        )
    elif recovery == "adapter-restart":
        ok_restart = run_make_target(
            "adapter-restart", timeout_s=120.0, log=log, sandbox=sandbox,
        )
    elif recovery == "beat8-script":
        # Beat 8's canonical recovery is the helper script, NOT a service
        # restart. The script itself goes through the live MCP path so the
        # ledger receipt the wait_for is looking for lands.
        ok, detail = run_beat8_script(log=log, sandbox=sandbox)
        out.attempts.append("recovery:beat8-script-result")
        if ok:
            out.succeeded = True
            out.final_path = "beat8-script"
            out.finished_at = datetime.now(UTC).isoformat()
            log.info("  ✓ beat %d recovered via mcp_beat8_run.sh (%s)", beat.index, detail)
            return out
        log.warning("  ✗ beat %d beat8-script recovery failed: %s", beat.index, detail)
        ok_restart = True  # we still try wire-replay below
    elif recovery == "none":
        log.info("  no recovery directive on beat %d; skipping to wire-replay", beat.index)
        ok_restart = True
    else:
        log.warning(
            "  unknown failure_recovery=%r on beat %d; skipping to wire-replay",
            recovery, beat.index,
        )
        ok_restart = True

    if recovery in ("worm-restart", "adapter-restart"):
        if not ok_restart:
            log.warning(
                "  recovery target failed on beat %d; falling through to wire-replay",
                beat.index,
            )
        else:
            # Wait briefly for the restarted service to come back. Health
            # probes should turn green within ~10s on a warm machine.
            if not sandbox:
                _wait_until_healthy(log)
            ok, detail = run_beat_via_compose(
                scenario_yaml=slice_path,
                pace=pace,
                timeout_s=beat.timeout_s,
                log=log,
                runner=runner,
                beat=beat,
            )
            if ok:
                out.succeeded = True
                out.final_path = recovery
                out.finished_at = datetime.now(UTC).isoformat()
                log.info(
                    "  ✓ beat %d recovered via %s (%s)",
                    beat.index, recovery, detail,
                )
                return out
            log.warning(
                "  ✗ beat %d second attempt after %s failed: %s",
                beat.index, recovery, detail,
            )

    # ─── Attempt 3: wire-replay ───────────────────────────────────────
    out.attempts.append("wire-replay")
    ok, detail = run_wire_replay_for_beat(
        beat=beat, log=log, sandbox=sandbox, runner=runner,
    )
    if ok:
        out.succeeded = True
        out.final_path = "wire-replay"
        out.finished_at = datetime.now(UTC).isoformat()
        log.info("  ✓ beat %d recovered via wire-replay (%s)", beat.index, detail)
        return out
    log.error("  ✗ beat %d wire-replay failed: %s", beat.index, detail)

    # ─── Halt ─────────────────────────────────────────────────────────
    out.error = (
        f"beat #{beat.index} ({beat.description}) could not complete: "
        f"first-try failed, {recovery} recovery failed, "
        f"wire-replay fallback failed ({detail}). "
        f"human-in-the-loop required; stack state preserved."
    )
    out.final_path = "halted"
    out.finished_at = datetime.now(UTC).isoformat()
    log.error("HALT: %s", out.error)
    return out


def _wait_until_healthy(log: logging.Logger, *, deadline_s: float = 30.0) -> None:
    """Poll worm-core /health + dashboard / until both return 200."""
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        worm_ok, _ = _http_probe("http://localhost:8910/api/v1/health")
        dash_ok, _ = _http_probe("http://localhost:3000/")
        if worm_ok and dash_ok:
            log.info("  stack healthy after restart")
            return
        time.sleep(1.0)
    log.warning("  stack did not return to healthy within %.0fs", deadline_s)


# ──────────────────────────────────────────────────────────────────────
# Entry point.
# ──────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="demo-orchestrator",
        description="Run the install-arc demo with per-beat auto-recovery.",
    )
    p.add_argument(
        "--scenario",
        default=DEFAULT_SCENARIO,
        help="Scenario name (under apps/sim-harness/scenarios/) "
             "or absolute path to a YAML.",
    )
    p.add_argument(
        "--pace",
        choices=["wall", "virtual"],
        default="wall",
        help="Clock pace forwarded to the engine.",
    )
    p.add_argument(
        "--report",
        default=None,
        help="Optional path to write a JSON run report.",
    )
    p.add_argument(
        "--sandbox",
        action="store_true",
        default=os.environ.get("WORMBASE_DEMO_SKIP_RUN") == "1",
        help="Sandbox / dry-run mode: parse + plan, no compose calls. "
             "Set WORMBASE_DEMO_SKIP_RUN=1 to enable via env.",
    )
    # W7.A3 — `--skip-installed` (default true) probes
    # GET /api/v1/installs before running Beat 1; on a hit it skips
    # every beat marked `skippable_if_pre_installed: true` in the
    # scenario YAML so `make demo` runs unattended after a one-time
    # OAuth seed. `--no-skip-installed` forces the full arc.
    p.add_argument(
        "--skip-installed",
        dest="skip_installed",
        action="store_true",
        default=True,
        help="Detect a pre-existing install (default: on). When an "
             "active install exists, skip beats marked "
             "`skippable_if_pre_installed: true` in the scenario YAML.",
    )
    p.add_argument(
        "--no-skip-installed",
        dest="skip_installed",
        action="store_false",
        help="Force every beat to run even when an active install is "
             "already present in the ledger.",
    )
    p.add_argument(
        "--tenant-slug",
        default=os.environ.get("WORMBASE_TENANT_SLUG", "").strip() or None,
        help="Tenant slug used by the install probe (defaults to "
             "WORMBASE_TENANT_SLUG or 'baseworm').",
    )
    p.add_argument(
        "--log-level",
        default=os.environ.get("WORMBASE_DEMO_LOG_LEVEL", "INFO"),
    )
    return p.parse_args(argv)


def _skipped_beat_outcome(
    beat: BeatPlan, *, reason: str,
) -> BeatOutcome:
    """Build a successful BeatOutcome for a beat that the orchestrator
    short-circuited (W7.A3 ``--skip-installed`` mode).

    Skipped beats count as passing — the install state they would have
    waited on is already in the ledger, so the beat's invariant is
    upheld by the seeded data, not by the run.
    """
    now = datetime.now(UTC).isoformat()
    return BeatOutcome(
        beat_index=beat.index,
        description=beat.description,
        attempts=["skipped-pre-installed"],
        succeeded=True,
        final_path="skipped-pre-installed",
        error=None,
        started_at=now,
        finished_at=now,
        skip_reason=reason,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    log = _setup_logging(args.log_level)

    log.info(
        "orchestrator starting (scenario=%s, pace=%s, sandbox=%s, "
        "skip_installed=%s)",
        args.scenario, args.pace, args.sandbox, args.skip_installed,
    )

    try:
        scenario_path, plans, scenario_dict = load_scenario_plan(args.scenario)
    except (FileNotFoundError, ValueError) as exc:
        log.error("failed to load scenario: %s", exc)
        return 2

    log.info("loaded %d beats from %s", len(plans), scenario_path)
    if not CANONICAL_FIXTURE.exists():
        log.warning(
            "canonical fixture missing: %s — wire-replay fallback unavailable. "
            "regenerate via `wormbase demo wire-record` against a known-good run.",
            CANONICAL_FIXTURE,
        )

    runner = _SandboxRunner() if args.sandbox else None

    # ─── W7.A3: pre-flight install probe ────────────────────────────
    skip_pre_installed = False
    skip_install_id: str | None = None
    if args.skip_installed:
        probe = _probe_existing_install(
            log=log, sandbox=args.sandbox, runner=runner,
            tenant_slug=args.tenant_slug,
        )
        if probe.state == "present":
            skip_pre_installed = True
            if probe.installs:
                skip_install_id = str(probe.installs[0].get("install_id") or "")
            log.info(
                "orchestrator: install probe found active install (id=%s); "
                "beats marked skippable_if_pre_installed will be skipped",
                skip_install_id or "?",
            )
        elif probe.state == "absent":
            log.info(
                "orchestrator: install probe found no active install; "
                "running every beat normally",
            )
        else:
            log.warning(
                "orchestrator: install probe state=%s detail=%r; "
                "running every beat normally to be safe",
                probe.state, probe.detail,
            )
    else:
        log.info(
            "orchestrator: --no-skip-installed set; running every beat "
            "regardless of install state",
        )

    report = RunReport(
        scenario=scenario_dict.get("name", scenario_path.stem),
        pace=args.pace,
        started_at=datetime.now(UTC).isoformat(),
    )

    # Slices live next to the scenarios so the sim-harness bind-mount sees
    # them. The orchestrator cleans them up on exit.
    scratch_dir = SCENARIOS_DIR
    written: list[Path] = []
    skipped_count = 0
    try:
        for plan in plans:
            if skip_pre_installed and plan.skippable_if_pre_installed:
                reason = (
                    f"skippable_if_pre_installed=true; install "
                    f"{skip_install_id or '<unknown>'} already exists"
                )
                log.info(
                    "orchestrator: skipping beat %d (%s)",
                    plan.index, reason,
                )
                report.beats.append(
                    _skipped_beat_outcome(plan, reason=reason),
                )
                skipped_count += 1
                continue

            outcome = execute_beat(
                beat=plan,
                pace=args.pace,
                scenario_dict=scenario_dict,
                scratch=scratch_dir,
                log=log,
                sandbox=args.sandbox,
                runner=runner,
            )
            report.beats.append(outcome)
            slice_path = _slice_path_for(plan, scratch=scratch_dir)
            if slice_path.exists():
                written.append(slice_path)
            if not outcome.succeeded:
                log.error(
                    "stopping after beat %d (paths attempted: %s)",
                    plan.index, ", ".join(outcome.attempts),
                )
                break
    finally:
        report.finished_at = datetime.now(UTC).isoformat()
        for p in written:
            with contextlib.suppress(OSError):
                p.unlink(missing_ok=True)
        if args.report:
            try:
                Path(args.report).write_text(
                    json.dumps(_serialize_report(report), indent=2),
                    encoding="utf-8",
                )
                log.info("wrote run report to %s", args.report)
            except OSError as exc:
                log.warning("could not write report to %s: %s", args.report, exc)

    log.info("─── summary ───")
    for b in report.beats:
        if b.final_path == "skipped-pre-installed":
            status = "↷"
        else:
            status = "✓" if b.succeeded else "✗"
        log.info(
            "  %s beat %d %s via %s (attempts: %s)",
            status, b.beat_index, b.description, b.final_path,
            ", ".join(b.attempts),
        )
    if skipped_count:
        log.info(
            "orchestrator: skipped %d beat%s due to pre-existing install",
            skipped_count, "" if skipped_count == 1 else "s",
        )
    if report.passed:
        log.info("orchestrator: all %d beats passed", len(report.beats))
        return 0
    halted = next((b for b in report.beats if b.final_path == "halted"), None)
    if halted is not None:
        log.error("orchestrator: HALTED on beat %d", halted.beat_index)
        log.error("  %s", halted.error)
    return 1


def _serialize_report(report: RunReport) -> dict[str, Any]:
    d = asdict(report)
    d["passed"] = report.passed
    return d


# Helper used by tests to drive the recovery state machine without
# touching docker. Importing this from a test module is the contract.
__all__ = [
    "BeatOutcome",
    "BeatPlan",
    "InstallProbeResult",
    "RunReport",
    "_probe_existing_install",
    "_skipped_beat_outcome",
    "execute_beat",
    "load_scenario_plan",
    "main",
    "parse_args",
    "run_make_target",
    "run_wire_replay_for_beat",
    "write_single_beat_scenario",
]


if __name__ == "__main__":
    sys.exit(main())
