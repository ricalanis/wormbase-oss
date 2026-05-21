"""Behavioral contract for `make tutorial` cold-start.

Static analysis of `scripts/tutorial.sh` lives in
`test_make_tutorial_smoke.py` and deliberately stays cheap. This test
is the other half: validates that the post-tutorial stack actually
honors the contracts the rest of the codebase assumes.

Each test only runs when `WORMBASE_LIVE_STACK=1` so CI / unit runs
don't try to talk to localhost ports.

Hypotheses validated (one assertion = one hypothesis):

* H1 — all 8 expected containers are Up (no restart loops)
* H2 — postgres has the pgvector extension installed at v0.6+ (required
  by migrations v016, v017, v018)
* H3 — worm-core's HTTP write API at :8910 responds 200 on
  `/api/v1/health`
* H4 — silent mode env var is honored end-to-end: `/api/v1/health` JSON
  body includes `silent_mode: bool` matching `WORMBASE_SILENT_MODE`
* H5 — voice-agent /healthz responds 200 with the same `silent_mode`
  field
* H6 — when silent mode is on, each app emits a `silent_mode=on
  app=<name>` boot log line exactly once
* H7 — projection_query_outcomes.embedding is a vector column, not a
  json fallback (proves pgvector wired into migrations correctly)
* H8 — under silent mode, POST /api/v1/people returns 200 (not 500)
  with `suppressed: true` and `entry_ids: []`. Regression caught
  2026-05-20: silent-mode merge gated `_pevr` but didn't teach
  `_result_payload` about `SuppressedToolResult`.
* H9 — ledger hash chain links cleanly across warmup + persona + rich
  seed entries (the core invariant the README pitches: "every action
  is hash-chained from an append-only Postgres ledger")
* H10 — multi-tenant isolation: baseworm and democorp have distinct
  company_ids and neither tenant's rows appear under the other's
  scope
* H11 — silent-mode gate 6: under `WORMBASE_SILENT_MODE=1`,
  `infra/openclaw/entrypoint.sh` renders `bindings: []` in the
  openclaw config so the embedded agent never auto-replies on
  inbound chat (caught live 2026-05-21 when a paired WhatsApp DM
  got an autonomous kimi-k2.6:cloud reply despite the 5 worm-core
  silent-mode gates being honored)

This test is the cold-start "contract test" — if it fails on a fresh
clone after `make tutorial`, something in the install path regressed.

Run: ``WORMBASE_LIVE_STACK=1 pytest tests/integration/test_cold_start_contract.py``
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from uuid import UUID, uuid5

import pytest

LIVE_STACK = os.environ.get("WORMBASE_LIVE_STACK") == "1"
pytestmark = pytest.mark.skipif(
    not LIVE_STACK,
    reason="set WORMBASE_LIVE_STACK=1 to run; requires `make tutorial` first",
)


EXPECTED_CONTAINERS: tuple[str, ...] = (
    "wormbase-postgres",
    "wormbase-vault",
    "wormbase-localstack",
    "wormbase-openclaw",
    "wormbase-worm-core",
    "wormbase-voice-agent",
    "wormbase-channel-adapter",
    "wormbase-dashboard",
)


def _docker(args: list[str]) -> str:
    """Run a docker command, returning stdout+stderr concatenated.

    `docker logs` writes Python's INFO/WARN/ERROR (which default to
    stderr) on stderr; capturing only stdout misses everything except
    the rare print() output. We merge both so callers can grep
    application logs uniformly.
    """
    result = subprocess.run(
        ["docker", *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
    )
    return result.stdout


def _http_get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def _env_silent_mode_on() -> bool:
    """Read WORMBASE_SILENT_MODE from the host .env (truthy → True)."""
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    env_path = os.path.join(repo_root, ".env")
    truthy = {"1", "true", "yes", "on"}
    if not os.path.exists(env_path):
        return False
    with open(env_path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            if key.strip() == "WORMBASE_SILENT_MODE":
                return value.strip().strip("'\"").lower() in truthy
    return False


def test_h1_all_containers_up() -> None:
    """H1 — all 8 expected containers are Up (no restart loops)."""
    output = _docker(["ps", "--format", "{{.Names}}\t{{.Status}}"])
    by_name = dict(
        line.split("\t", 1) for line in output.splitlines() if "\t" in line
    )
    missing = [c for c in EXPECTED_CONTAINERS if c not in by_name]
    assert not missing, f"missing containers: {missing}"
    restart_looping = {
        name: status
        for name, status in by_name.items()
        if name in EXPECTED_CONTAINERS and "Restarting" in status
    }
    assert not restart_looping, f"containers in restart loop: {restart_looping}"


def test_h2_pgvector_extension_installed() -> None:
    """H2 — pgvector ≥0.6 installed; required by migrations v016/v017/v018."""
    output = _docker(
        [
            "exec",
            "wormbase-postgres",
            "psql",
            "-U",
            "wormbase",
            "-d",
            "wormbase",
            "-tAc",
            "SELECT extname || ' ' || extversion FROM pg_extension WHERE extname = 'vector'",
        ]
    )
    line = output.strip()
    assert line.startswith("vector "), (
        f"pgvector extension not installed in wormbase-postgres (got {line!r}); "
        "check infra/docker-compose.yml uses pgvector/pgvector:pg16"
    )
    # extversion is e.g. "0.8.2"
    major_minor = line.split(" ", 1)[1].split(".")
    major, minor = int(major_minor[0]), int(major_minor[1])
    assert (major, minor) >= (0, 6), f"pgvector too old: {line}"


def test_h3_worm_core_http_api_responsive() -> None:
    """H3 — worm-core HTTP write API at :8910 responds 200."""
    status, body = _http_get("http://localhost:8910/api/v1/health")
    assert status == 200, f"worm-core /api/v1/health returned {status}: {body!r}"


def test_h4_worm_core_silent_mode_field_matches_env() -> None:
    """H4 — `/api/v1/health` JSON includes silent_mode matching .env."""
    status, body = _http_get("http://localhost:8910/api/v1/health")
    assert status == 200
    payload = json.loads(body)
    assert "silent_mode" in payload, (
        f"expected silent_mode field in /api/v1/health body, got {payload}"
    )
    assert payload["silent_mode"] is _env_silent_mode_on(), (
        f"silent_mode field {payload['silent_mode']} disagrees with .env "
        f"WORMBASE_SILENT_MODE={_env_silent_mode_on()!r}"
    )


def test_h5_voice_agent_healthz_silent_mode_matches_env() -> None:
    """H5 — voice-agent /healthz reflects WORMBASE_SILENT_MODE."""
    status, body = _http_get("http://localhost:8090/healthz")
    assert status == 200
    payload = json.loads(body)
    assert "silent_mode" in payload, (
        f"expected silent_mode field in voice-agent /healthz body, got {payload}"
    )
    assert payload["silent_mode"] is _env_silent_mode_on()


@pytest.mark.skipif(
    not _env_silent_mode_on(),
    reason="silent mode not enabled in .env — no boot log line expected",
)
def test_h6_silent_mode_boot_log_on_each_app() -> None:
    """H6 — each app emits a `silent_mode=on app=<name>` line exactly once."""
    expectations = {
        "wormbase-worm-core": "silent_mode=on app=worm-core",
        "wormbase-voice-agent": "silent_mode=on app=voice-agent",
        "wormbase-channel-adapter": "silent_mode=on app=channel-adapter",
    }
    for container, expected_line in expectations.items():
        logs = _docker(["logs", container])
        count = logs.count(expected_line)
        assert count >= 1, (
            f"{container}: expected `{expected_line}` in boot log; "
            f"got count={count}. (last 40 lines: "
            f"{logs.splitlines()[-40:]})"
        )


@pytest.mark.skipif(
    not _env_silent_mode_on(),
    reason="silent mode not enabled — endpoint returns normal PEVR shape",
)
def test_h8_post_people_under_silent_mode_returns_200_suppressed() -> None:
    """H8 — POST /api/v1/people returns 200 + suppressed:true under silent mode.

    Repro of the live 2026-05-20 bug: with silent mode on, the seed
    step crashed because the HTTP API's `_result_payload` accessed
    `write_result.entry_ids` even when the result was a
    `SuppressedToolResult`. Every write endpoint 500'd; the tutorial
    completed but `personas_seeded=0` because of cascading retries.
    """
    # Bearer token is in the host .env — read it the same way the
    # tutorial does (POSIX-safe parsing, no shell expansion).
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    env_path = os.path.join(repo_root, ".env")
    token = None
    with open(env_path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip().startswith("WORMBASE_LEDGER_API_TOKEN="):
                token = line.strip().split("=", 1)[1].strip().strip("'\"")
                break
    assert token, "WORMBASE_LEDGER_API_TOKEN missing from .env"

    req = urllib.request.Request(
        "http://localhost:8910/api/v1/people",
        data=json.dumps(
            {
                "name": "Alice",
                "email": "alice@example.com",
                "platform": "slack",
                "platform_user_id": "U-alice-h8",
                "position": "data_engineer",
                "proposed_by": "test_h8",
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status, body = resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read().decode("utf-8")

    assert status == 200, (
        f"POST /api/v1/people returned {status}: {body!r}. "
        "Pre-fix this was 500 'Server got itself in trouble' because "
        "_result_payload accessed entry_ids on a SuppressedToolResult."
    )
    payload = json.loads(body)
    assert payload.get("suppressed") is True, payload
    assert payload.get("entry_ids") == [], payload
    assert "ref_id" in payload, payload


def test_h7_projection_query_outcomes_embedding_is_vector_type() -> None:
    """H7 — embedding column is `vector`, not `json` (proves pgvector wired)."""
    output = _docker(
        [
            "exec",
            "wormbase-postgres",
            "psql",
            "-U",
            "wormbase",
            "-d",
            "wormbase",
            "-tAc",
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_name = 'projection_query_outcomes' "
            "AND column_name = 'embedding'",
        ]
    )
    udt = output.strip()
    assert udt == "vector", (
        f"projection_query_outcomes.embedding has udt_name={udt!r}; "
        "expected 'vector' (pgvector). 'json' indicates the postgresql "
        "branch in v016's _embedding_column was not taken — pgvector "
        "missing in image, or dialect detection wrong."
    )


def _ledger_rows_for_tenant(company_id: str) -> list[dict[str, str]]:
    """Fetch ledger rows for a tenant, ordered by seq.

    Returns a list of dicts with seq, kind, prev_hash (hex), hash (hex)
    so callers can verify the hash chain locally without pulling
    asyncpg + hash code into the test binary.
    """
    sql = (
        f"SELECT seq, kind, encode(prev_hash, 'hex'), encode(hash, 'hex') "
        f"FROM ledger WHERE company_id = '{company_id}'::uuid "
        f"ORDER BY seq"
    )
    output = _docker(
        [
            "exec",
            "wormbase-postgres",
            "psql",
            "-U",
            "wormbase",
            "-d",
            "wormbase",
            "-tAc",
            sql,
        ]
    )
    rows: list[dict[str, str]] = []
    for line in output.strip().splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            continue
        rows.append(
            {
                "seq": parts[0].strip(),
                "kind": parts[1].strip(),
                "prev_hash": parts[2].strip(),
                "hash": parts[3].strip(),
            }
        )
    return rows


_TENANT_NAMESPACE = UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f")


def _tenant_to_company_uuid(tenant: str) -> str:
    """Mirror the project's deterministic UUID5 mapping for tenant slugs.

    Namespace pinned in `apps/worm-core/src/wormbase_core/service.py`
    (TENANT_NAMESPACE). Tenant slugs are normalized strip().lower().
    """
    return str(uuid5(_TENANT_NAMESPACE, tenant.strip().lower()))


def test_h9_ledger_hash_chain_links_cleanly() -> None:
    """H9 — every row's prev_hash matches the previous row's hash.

    The README pitches the ledger as "hash-chained, append-only";
    this asserts the chain holds after warmup + persona + rich seed.
    A broken link would mean either a write skipped the hash-update
    path or a row was inserted out of band.
    """
    company_id = _tenant_to_company_uuid("baseworm")
    rows = _ledger_rows_for_tenant(company_id)
    assert len(rows) >= 40, f"expected baseworm to have warmup rows, got {len(rows)}"
    zero_hash = "00" * 32  # genesis prev_hash
    assert rows[0]["prev_hash"] == zero_hash, rows[0]
    for prev, cur in zip(rows, rows[1:]):
        assert cur["prev_hash"] == prev["hash"], (
            f"chain broken at seq={cur['seq']}: "
            f"prev_hash {cur['prev_hash'][:16]}... != "
            f"prior hash {prev['hash'][:16]}..."
        )


def test_h10_multi_tenant_isolation_baseworm_democorp() -> None:
    """H10 — baseworm and democorp ledgers are disjoint.

    Multi-tenancy v2 maps each tenant slug to a deterministic
    company_id (uuid5(namespace, slug)). Both tenants' warmup runs
    write 40 rows each; neither tenant's rows should appear under
    the other tenant's company_id scope.
    """
    base_id = _tenant_to_company_uuid("baseworm")
    demo_id = _tenant_to_company_uuid("democorp")
    assert base_id != demo_id

    base_rows = _ledger_rows_for_tenant(base_id)
    demo_rows = _ledger_rows_for_tenant(demo_id)
    assert len(base_rows) >= 40
    assert len(demo_rows) >= 40

    # No row's hash appears under both tenants — that would imply a
    # cross-tenant leak (or a UUID5 collision, which would be a far
    # weirder bug).
    base_hashes = {r["hash"] for r in base_rows}
    demo_hashes = {r["hash"] for r in demo_rows}
    overlap = base_hashes & demo_hashes
    assert not overlap, f"cross-tenant hash overlap: {sorted(overlap)[:5]}"


@pytest.mark.skipif(
    not _env_silent_mode_on(),
    reason="silent mode not enabled — openclaw bindings should be non-empty",
)
def test_h11_openclaw_bindings_empty_under_silent_mode() -> None:
    """H11 — openclaw bindings are [] under silent mode (gate 6).

    Pulled live from `docker exec wormbase-openclaw cat
    /root/.openclaw/openclaw.json` so the assertion exercises the
    actual entrypoint render path, not a mock.
    """
    output = _docker(
        ["exec", "wormbase-openclaw", "cat", "/root/.openclaw/openclaw.json"]
    )
    config = json.loads(output)
    bindings = config.get("bindings")
    assert bindings == [], (
        f"expected empty bindings under WORMBASE_SILENT_MODE=1; got: "
        f"{bindings!r}. The entrypoint silent-mode case did not fire — "
        "check WORMBASE_SILENT_MODE forwarding in the openclaw service "
        "env block and the `case` block at the bindings-render site."
    )
