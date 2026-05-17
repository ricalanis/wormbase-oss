"""N2 demo gate: no placeholder text or demo-seam leakage on production paths.

E7 of ``docs/superpowers/plans/2026-04-26-production-dashboard.md``.

Two layers:

1. **Code-level grep** — always runs; greps the production paths for
   demo-seam patterns that should not exist:

   * ``simulate-flows`` — the deleted demo command (Block C3 deletion
     gate); must never reappear.
   * ``personas.yml`` references in production paths (allowed only
     inside ``apps/sim-harness/``; the dashboard reads canonical
     Person rows from the ledger).
   * ``fixtures/`` references in ``apps/dashboard/app/(app)/``
     (production tab paths) — fixtures stay sim-only; production
     reads ledger projections.
   * Hardcoded persona names ("alice", "bob", "carol", "dave")
     anywhere in ``apps/dashboard/`` outside ``tests/`` and outside
     the explicitly-named ``demo-fixture.ts`` file.
   * ``# TODO demo`` / ``# mock for demo`` / ``// fake for demo``
     comments — eliminate or escalate.

2. **Rendered DOM grep** — gated on Playwright availability; greps
   the rendered DOM of every demo-script page for placeholder strings
   ("Lorem", "TBD", "FIXME", "TODO"). Today this stays a stub
   pending the Playwright harness wiring; failure on layer 1 is
   sufficient to fail the gate.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Layer 1: code-level grep against production paths.
# ---------------------------------------------------------------------------


def _run_grep(
    pattern: str,
    *,
    path: str,
    extended: bool = True,
    include: list[str] | None = None,
    exclude_paths: list[str] | None = None,
) -> list[str]:
    """Run a `grep -rE` and return matching ``path:line:content`` rows.

    Returns an empty list when grep finds nothing. We don't error on
    missing paths — the test author knows the repo layout, and the
    failure surface is "grep finds something it shouldn't," not
    "grep doesn't run."
    """
    if not (REPO_ROOT / path).exists():
        return []

    cmd = ["grep", "-rnI"]
    if extended:
        cmd.append("-E")
    cmd.append(pattern)
    cmd.append(str(REPO_ROOT / path))
    if include:
        for inc in include:
            cmd.extend(["--include", inc])
    if exclude_paths:
        for excl in exclude_paths:
            cmd.extend(["--exclude-dir", excl])

    proc = subprocess.run(  # noqa: S603 — args constructed locally
        cmd, capture_output=True, text=True, check=False,
    )
    # grep exits 0 = matched, 1 = no match, 2 = error. Treat 1 as empty.
    if proc.returncode not in (0, 1):
        raise AssertionError(
            f"grep failed: cmd={cmd} rc={proc.returncode} "
            f"stderr={proc.stderr.strip()}"
        )
    if not proc.stdout.strip():
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _filter_self(rows: list[str], filename: str) -> list[str]:
    """Drop rows whose path is THIS test file (avoids self-referential hits).

    The test names + comments themselves contain the patterns we're
    grepping for — that's expected and not a violation.
    """
    return [r for r in rows if filename not in r]


def test_N2_no_simulate_flows_in_repo() -> None:
    """``simulate-flows`` was deleted in Block C3; it must never come back.

    We grep code paths (apps + packages); CLAUDE.md and historical
    plan/spec/note documents legitimately reference the deleted
    command as guard prose.
    """
    code_paths = ["apps", "packages", "tests", "infra", "Makefile"]
    all_rows: list[str] = []
    for cp in code_paths:
        all_rows.extend(
            _run_grep(
                r"simulate[-_]flows",
                path=cp,
                include=["*.py", "*.ts", "*.tsx", "*.yml", "*.yaml", "*.json"],
                exclude_paths=[
                    ".git",
                    "node_modules",
                    ".venv",
                    "venv",
                    ".junit",
                    "__pycache__",
                    ".pytest_cache",
                    ".next",
                    "dist",
                    "build",
                ],
            )
        )
    all_rows = _filter_self(all_rows, Path(__file__).name)
    assert not all_rows, (
        f"simulate-flows reappeared in the repo (deleted in Block C3): "
        f"{all_rows[:10]}"
    )


def test_N2_no_personas_yml_in_production_paths() -> None:
    """personas.yml is bot-roster-only after E5; production reads ledger."""
    # Allowed: anywhere under apps/sim-harness/ (the bot-roster owner) and
    # tests/ (which may reference the YAML for assertion fixtures).
    rows = _run_grep(
        r"personas\.yml",
        path="apps",
        include=["*.ts", "*.tsx", "*.py"],
        exclude_paths=["sim-harness", "__pycache__", ".next", "node_modules"],
    )
    rows = _filter_self(rows, Path(__file__).name)
    assert not rows, (
        f"personas.yml referenced in production paths "
        f"(should be bot-roster only under apps/sim-harness/ after E5): "
        f"{rows}"
    )


def test_N2_no_fixtures_in_production_dashboard_paths() -> None:
    """`fixtures/` references in dashboard production tab paths are forbidden.

    Production tabs read ledger projections; fixtures are sim-only or
    replay-only. The explicit ``demo-fixture.ts`` file in
    ``apps/dashboard/lib/`` is allowed (it ships test scaffolding) but
    must NOT be imported from production tab paths under ``app/(app)/``.
    """
    # Production tab paths are app/(app)/...
    rows = _run_grep(
        r"(from\s+[\"'].*fixtures?/|import.*fixtures?/|demo-fixture)",
        path="apps/dashboard/app/(app)",
        include=["*.tsx", "*.ts"],
        exclude_paths=["__tests__", "tests", "node_modules", ".next"],
    )
    rows = _filter_self(rows, Path(__file__).name)
    assert not rows, (
        f"fixtures referenced from production dashboard paths under "
        f"apps/dashboard/app/(app)/ — replace with ledger reads: {rows}"
    )


def test_N2_no_hardcoded_persona_names_in_dashboard_production() -> None:
    """Hardcoded "alice" / "bob" / "carol" / "dave" outside tests/ + demo-fixture.

    The dashboard's roster, channel members, and people search must
    resolve from the ledger Person projection — not from a static
    persona list embedded in TSX. The only allowed exceptions:

    * ``apps/dashboard/lib/demo-fixture.ts`` — central test-scaffolding
      module (still used by Block A's own tests).
    * Form-input ``placeholder="..."`` and ``placeholder='...'``
      attributes containing example values like ``carol@x.co`` /
      ``bob@x.co`` — these are user-facing hints, not hardcoded
      persona logic. The values are descriptive, not behavioural.
    """
    pattern = r"\b(alice|bob|carol|dave)\b"
    rows = _run_grep(
        pattern,
        path="apps/dashboard",
        include=["*.tsx", "*.ts"],
        exclude_paths=[
            "tests",
            "__tests__",
            "node_modules",
            ".next",
        ],
    )
    rows = _filter_self(rows, Path(__file__).name)
    # Path-level allowlist — demo-fixture.ts is sanctioned scaffold.
    allowed_path_substrings = (
        "/lib/demo-fixture.ts",
        "/lib/demo-fixture.tsx",
    )
    # Line-level allowlist — JSX `placeholder="..."` and the URL/email
    # demo strings inside them are example UI text, not persona logic.
    placeholder_re = re.compile(r"placeholder\s*=\s*['\"]")
    filtered: list[str] = []
    for row in rows:
        if any(allowed in row for allowed in allowed_path_substrings):
            continue
        try:
            content = row.split(":", 2)[2]
        except IndexError:
            content = row
        if placeholder_re.search(content):
            continue
        filtered.append(row)
    assert not filtered, (
        f"hardcoded persona names in dashboard production paths "
        f"(read from ledger via getPeople(companyId) instead): "
        f"{filtered[:20]}"
    )


def test_N2_no_demo_only_todo_comments() -> None:
    """`# TODO demo`, `# mock for demo`, `// fake for demo` comments are forbidden.

    These mark demo-only seams that should never have been written or
    that should have been cleaned up. The cleanup pass (E4 of the
    plan) removes them.
    """
    pattern = (
        r"(TODO\s+demo|mock\s+for\s+demo|fake\s+for\s+demo|"
        r"placeholder.*demo)"
    )
    rows: list[str] = []
    for cp in ("apps", "packages"):
        rows.extend(
            _run_grep(
                pattern,
                path=cp,
                include=["*.py", "*.ts", "*.tsx"],
                exclude_paths=[
                    "node_modules",
                    "__pycache__",
                    ".next",
                    "dist",
                    "build",
                    "tests",
                ],
            )
        )
    rows = _filter_self(rows, Path(__file__).name)
    # Filter out matches that are inside docstrings / module headers
    # legitimately (e.g. "the worm tracks demo-only seams" prose). We
    # use a simple heuristic: lines starting with `#` or `//` plus the
    # bad keyword are real violations; lines that have the keyword
    # mid-text (prose) survive only if they're documentation.
    violations: list[str] = []
    for row in rows:
        # Format: <path>:<lineno>:<content>
        try:
            content = row.split(":", 2)[2].lstrip()
        except IndexError:
            continue
        # Real violation: a comment line starting with a comment marker
        # AND containing the offending pattern verbatim.
        if (content.startswith("#") or content.startswith("//")) and re.search(
            pattern, content, re.IGNORECASE,
        ):
            violations.append(row)
    assert not violations, (
        f"demo-only comments found — clean up or remove: {violations[:10]}"
    )


def test_N2_no_thursday_or_hackathon_in_production_paths() -> None:
    """``for thursday`` / ``for the demo`` / ``hackathon`` comments
    forbidden in production code paths.

    These are stale time-pressure markers that should have been
    cleaned up. The audit pass that ran post-Block-F caught a
    handful and replaced them with intent-conveying prose; the gate
    enforces the rule going forward.

    Allowed exceptions:

    * Anything under ``tests/`` (test fixture prose can reference
      "the demo arc" legitimately).
    * Anything under ``apps/sim-harness/`` (sim is the staged
      production environment; "demo" prose is explicit there).
    * Documentation files (``docs/``).
    """
    pattern = r"(for\s+thursday|for\s+the\s+demo|for\s+demo\b|hackathon)"
    rows: list[str] = []
    for cp in ("apps", "packages"):
        rows.extend(
            _run_grep(
                pattern,
                path=cp,
                include=["*.py", "*.ts", "*.tsx"],
                exclude_paths=[
                    "node_modules",
                    "__pycache__",
                    ".next",
                    "dist",
                    "build",
                    "tests",
                    "sim-harness",
                    "voice-agent",  # POC scope
                ],
            )
        )
    rows = _filter_self(rows, Path(__file__).name)
    assert not rows, (
        f"stale time-pressure markers in production paths — replace with "
        f"intent-conveying prose: {rows[:10]}"
    )


def test_N2_no_synthesize_grant_or_fake_oauth_in_production_paths() -> None:
    """No "synthesize" / "fake oauth" / "self-grant placeholder" markers
    in production code paths.

    Caught by the post-Block-F audit:

    * ``oauth_grant_ref = "dev://..."`` synthesized grants — replaced by
      real OAuth or a documented "Configure SLACK_CLIENT_ID" UX.
    * ``self-grant placeholder until SSO`` in domain owner-grant
      handlers — replaced by a real ``currentPersonId`` thread.
    * ``"mock; real kernel slot"`` / ``"placeholder"`` content baked
      into autoresearch-published notebook cells — replaced by
      intent-conveying prose.

    These markers are forbidden in production paths. The exclusions
    below mirror the agent territory split (onboarding agent owns
    OAuth wiring; capability-honesty agent owns connector / adapter
    status badges).
    """
    # We grep for the literal strings "self-grant placeholder",
    # "synthesize.*oauth", and "mock; real kernel" — all are
    # specific enough to almost never produce false positives in
    # docstrings.
    pattern = (
        r"(self-grant\s+placeholder|"
        r"synthesi[sz]e[d]?\s+oauth|"
        r"mock;\s*real\s+kernel|"
        r"connector\.query\([^)]*\)\s*placeholder)"
    )
    rows: list[str] = []
    for cp in ("apps", "packages"):
        rows.extend(
            _run_grep(
                pattern,
                path=cp,
                include=["*.py", "*.ts", "*.tsx"],
                exclude_paths=[
                    "node_modules",
                    "__pycache__",
                    ".next",
                    "dist",
                    "build",
                    "tests",
                    "sim-harness",
                    "voice-agent",  # POC scope
                ],
            )
        )
    rows = _filter_self(rows, Path(__file__).name)
    # Filter out negation-prose mentions: defensive comments and error
    # messages that explicitly disallow the seam are NOT violations —
    # they're enforcing the rule, not breaking it.
    #
    # We only allow the negation filter for lines that are clearly
    # non-behavioural (comments, string literals inside throw/error
    # paths). The seam itself is a code construct (assignment, object
    # literal value, function call); negation prose surfaces in
    # docstrings + error messages.
    NEGATION_PROSE_RE = re.compile(
        r"\b(no|not|never|refus(ing|e|ed)|reject(ing|ed)?|disallow(ed)?|"
        r"forbid(s|den)?|without)\b[^\n]*?(self-grant\s+placeholder|"
        r"synthesi[sz]e[d]?\s+oauth|mock;\s*real\s+kernel)",
        re.IGNORECASE,
    )
    filtered = []
    for row in rows:
        try:
            content = row.split(":", 2)[2]
        except IndexError:
            content = row
        if NEGATION_PROSE_RE.search(content):
            continue
        filtered.append(row)
    assert not filtered, (
        f"synthesized-grant / fake-oauth / placeholder-cell markers "
        f"reappeared — replace with the real implementation or honest "
        f"empty / preview state: {filtered[:10]}"
    )


def test_N2_no_fixture_returns_in_user_facing_read_paths() -> None:
    """Tasks/Insights and similar production read accessors must not
    return demo fixtures unconditionally.

    The pre-Block-F getTasks / getInsights / getX read accessors
    returned the curated fixture even when no upstream events
    existed. This is a quiet lie at the surface — replaced by an
    empty list with an honest empty-state in the panel.

    The gate looks for ``return TASKS;`` / ``return INSIGHTS;``
    style unconditional fixture returns inside ``ledger-client.ts``
    (the dashboard's only sanctioned fixture-fallback file). Any
    new fixture import returned at the top-level of a function
    fails the gate; conditional fallbacks ``if rows.length === 0
    return FIXTURE`` are still allowed (they're the "Postgres
    empty" → "show fixture" pattern, sanctioned in the file
    docstring).
    """
    target = REPO_ROOT / "apps/dashboard/lib/ledger-client.ts"
    if not target.exists():
        pytest.skip("ledger-client.ts not present")
    text = target.read_text("utf-8")
    # Match a return statement whose RHS is one of the demo-fixture
    # exports, NOT preceded on the same logical line by a length-zero
    # check. We walk the text line by line and look for `return X;`
    # where X is a known fixture export.
    #
    # ``ONTOLOGY_SEEDS`` is intentionally allowed: ontology seeds live
    # in a static YAML pack (``packages/ontology-seed/``) and the
    # fixture mirrors that pack. There is no ledger projection for
    # ontology seeds, so the dashboard reads the YAML-equivalent
    # fixture directly. This is documented in the function's
    # docstring.
    fixture_names = (
        "TASKS",
        "INSIGHTS",
        "RAMP_GAUGES",
        "KPI_TREE",
        "TRACE_ENTRIES",
        "DOMAINS",
        "SOURCES",
        "POLICIES",
        "CHANNELS",
        "BUSINESS_DEFS",
        "PII_PATTERNS",
        "CONVERSATIONS",
    )
    violations: list[str] = []
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        for name in fixture_names:
            # Match `return NAME;` exactly (no length-zero predicate
            # in front of it on the same line, no `if ... return
            # NAME;` ternary). We allow `return NAME;` only when
            # the previous non-blank line carries a `length === 0`
            # / `rows.length === 0` predicate or `if (...)` block.
            if stripped == f"return {name};" or stripped == f"return {name}":
                # Look backward for a length-zero predicate within 12
                # lines (covers `if (length === 0) { warnOnce(); return X; }`
                # blocks where the warnOnce body spans several lines).
                guarded = False
                for back in range(1, 13):
                    if idx - back < 0:
                        break
                    prev = lines[idx - back].strip()
                    if not prev:
                        continue
                    if (
                        ".length === 0" in prev
                        or "rows.length" in prev
                        or "res.rows.length" in prev
                    ):
                        guarded = True
                        break
                if not guarded:
                    violations.append(f"line {idx + 1}: {stripped}")
    assert not violations, (
        f"unconditional `return <FIXTURE>` in ledger-client.ts — replace "
        f"with `return []` or wire a real ledger query: {violations[:10]}"
    )


# ---------------------------------------------------------------------------
# Onboarding-tail regression patterns (T3 of the onboarding tail).
#
# These four patterns mark identity / OAuth seams that the
# onboarding-reconciliation pass deleted. They are subtler than the
# generic "synthesize" / "self-grant" patterns covered above:
#
#   * `"oauth_grant_ref": "dev://"`  — the deleted synthesized grant ref.
#     Real OAuth always lands a `kms://` or `vault://` ref; the
#     `dev://` prefix is the "we made one up" signal and should never
#     reappear.
#   * `pending_email`                — the deleted synthesized identity
#     fallback used by the pre-OAuth InviteModal. Replaced by a real
#     `platform_user_id` resolution path.
#   * `Unknown · observer`           — the deleted PersonChip fallback.
#     With no Install row the dashboard now redirects to /onboarding,
#     so this string should never render.
#   * `pending-email-stub`           — any naming convention that
#     indicates a stubbed-pending-email Person. The cleanup pass
#     deleted these; the gate enforces "stays gone".
#
# The grep is anchored on production paths (apps/dashboard /
# apps/worm-core / packages); test fixtures and this file itself are
# excluded.
# ---------------------------------------------------------------------------


_ONBOARDING_TAIL_REGRESSION_PATTERNS = (
    # Match `"oauth_grant_ref": "dev://"` (and the single-quote form).
    # The grant ref must be `kms://` or `vault://`; the validator on
    # InstallCompletedPayload enforces this at write time, and the
    # grep catches anyone constructing one in code before sending it.
    # Uses POSIX [:space:] for portability and the literal ' char to
    # avoid BSD grep's lack of \x27 / \047 expansion in -E patterns.
    'oauth_grant_ref["\']' + '[[:space:]]*[:=][[:space:]]*' + '["\']dev://',
    # `pending_email` as an identifier in real code: object key,
    # property access, or string-literal value. We skip prose mentions
    # (e.g. "no synthesized `pending_email` platform shim" in
    # docstrings) by anchoring on code-shape syntax.
    '(pending_email[[:space:]]*[:=]|\\.pending_email|["\']pending_email["\'])',
    # `Unknown · observer` PersonChip fallback. Anchored to a quote on
    # either side so prose mentions in comments don't false-positive.
    # The middle-dot is the literal U+00B7 char.
    '["\']Unknown +· +observer["\']',
    # `pending-email-stub` as an import/path/id (kebab-case file or
    # module name), not a prose mention.
    '(["\'/]pending-email-stub|pending-email-stub["\'/])',
)


def test_N2_onboarding_tail_regressions_absent_from_production() -> None:
    """The four onboarding-tail seams (deleted in 2026-04-26 reconciliation)
    must not reappear in production code paths.

    See the comment block above for which seam each pattern catches.
    """
    rows: list[str] = []
    for pattern in _ONBOARDING_TAIL_REGRESSION_PATTERNS:
        for cp in ("apps", "packages"):
            rows.extend(
                _run_grep(
                    pattern,
                    path=cp,
                    include=["*.py", "*.ts", "*.tsx", "*.json"],
                    exclude_paths=[
                        "node_modules",
                        "__pycache__",
                        ".next",
                        "dist",
                        "build",
                        "tests",
                        "sim-harness",
                        "voice-agent",
                    ],
                )
            )
    rows = _filter_self(rows, Path(__file__).name)
    assert not rows, (
        f"onboarding-tail regression patterns found — these were deleted "
        f"by the OAuth/install reconciliation and must not return: "
        f"{rows[:10]}"
    )


def test_N2_onboarding_tail_gate_fires_on_synthesized_dev_grant(
    tmp_path: Path,
) -> None:
    """Positive test: the gate would catch `oauth_grant_ref": "dev://`.

    We synthesize a fake "production" file under a tmp tree and re-run
    the same grep helper against it; the helper must surface the
    violation.
    """
    fake = tmp_path / "fake_apps" / "dashboard" / "lib" / "regress.ts"
    fake.parent.mkdir(parents=True)
    fake.write_text(
        'const body = { "oauth_grant_ref": "dev://abc123", "platform": "slack" };\n',
        encoding="utf-8",
    )
    cmd = [
        "grep", "-rnIE",
        _ONBOARDING_TAIL_REGRESSION_PATTERNS[0],
        str(fake.parent),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    assert proc.returncode == 0, (
        f"grep should have matched the synthesized 'dev://' grant in "
        f"{fake} but returned rc={proc.returncode} "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "dev://" in proc.stdout


def test_N2_no_connector_grid_in_onboarding_page() -> None:
    """Block I3: ConnectorFirstGrid is retired from /onboarding.

    The connector picker stays at /sources/new (Block D4 — post-install
    progressive enhancement). Re-introducing ConnectorFirstGrid into
    apps/dashboard/app/onboarding/page.tsx (or any other onboarding
    page) would resurrect the connector-first front door that Block I
    explicitly walked back.

    Allowed: imports inside /sources/new (the canonical home for the
    picker) and inside test/spec files. The grep below excludes
    apps/dashboard/app/(app)/sources/new/ and tests/.
    """
    onboarding_dir = "apps/dashboard/app/onboarding"
    rows = _run_grep(
        r"(ConnectorFirstGrid|onboarding-tier0-connector-first)",
        path=onboarding_dir,
        include=["*.ts", "*.tsx"],
        exclude_paths=["__tests__", "tests", "node_modules", ".next"],
    )
    rows = _filter_self(rows, Path(__file__).name)
    assert not rows, (
        f"ConnectorFirstGrid (or its data-testid wrapper) referenced "
        f"in {onboarding_dir} — Block I3 retired the connector grid "
        f"from /onboarding. The picker lives at /sources/new now: "
        f"{rows[:10]}"
    )


def test_N2_no_sentinel_hashes_in_production_paths() -> None:
    """Block I8 invariant: hardcoded persona / hash sentinels are forbidden
    in production paths.

    The dashboard's people, sources, kpis, and trace tabs must resolve
    every Person + hash from the live ledger projection. Hardcoded
    "ricardo-bot" handles or "11aa22bb"-style sentinel hash prefixes
    are demo-only seams that leaked into production code; the gate
    enforces "stay gone".

    Excluded: tests/, sim-harness/, fixtures/, demo-fixture.ts, and
    docs/ — those legitimately reference example sentinels.
    """
    sentinel_patterns = (
        # ricardo-bot was an early demo persona handle that briefly
        # leaked into a hardcoded list. Stays out of production paths.
        r"ricardo-bot",
        # 11aa22bb / 22bb33cc-style sentinel hashes used in early
        # smoke tests. Production hashes are real sha256 truncations.
        r"\b(11aa22bb|22bb33cc|33cc44dd|44dd55ee|deadbeef[a-f0-9]*)\b",
    )
    rows: list[str] = []
    for pattern in sentinel_patterns:
        for cp in ("apps/dashboard/app", "apps/dashboard/components",
                   "apps/dashboard/lib", "apps/worm-core/src",
                   "apps/channel-adapter/src"):
            rows.extend(
                _run_grep(
                    pattern,
                    path=cp,
                    include=["*.ts", "*.tsx", "*.py"],
                    exclude_paths=[
                        "node_modules",
                        "__pycache__",
                        ".next",
                        "dist",
                        "build",
                        "tests",
                        "__tests__",
                    ],
                )
            )
    rows = _filter_self(rows, Path(__file__).name)
    # Allow demo-fixture.ts (the sanctioned scaffold).
    rows = [r for r in rows if "/lib/demo-fixture.ts" not in r]
    # Allow JSX placeholder="..." attributes — example UI hints
    # surfaced to the user, not behavioural code.
    placeholder_re = re.compile(r"placeholder\s*=\s*['\"]")
    filtered = []
    for row in rows:
        try:
            content = row.split(":", 2)[2]
        except IndexError:
            content = row
        if placeholder_re.search(content):
            continue
        filtered.append(row)
    assert not filtered, (
        f"sentinel persona handles or hash literals in production "
        f"paths — replace with ledger reads or remove: {filtered[:10]}"
    )


# ---------------------------------------------------------------------------
# Block J8 — MCP-specific placeholder + demo-seam patterns.
#
# The MCP catalog endpoint, audit pipeline, and demo Beat 8 share these
# regressions:
#
#   * `# TODO MCP` / `# TODO mcp` / `# TODO: MCP`  — stale in-progress
#     markers that should never ship into production paths.
#   * `"available": false` baked into a committed JSON fixture under
#     apps/ — the dashboard's empty state should be derived from a live
#     read, not from a synthesized "MCP server unavailable" fixture.
#   * `"mcp_call_id": "demo"` and similar synthesized MCP-call audit
#     entries — replay determinism breaks if a fixture forges audit ids.
#   * `"caller_person_id": "fake"` — the audit pipeline writes the real
#     caller id (or None for anonymous bearer-token mode); fake values
#     leak demo-only seams into the audited record.
# ---------------------------------------------------------------------------


_MCP_REGRESSION_PATTERNS = (
    # `# TODO MCP` (any case, with optional colon).
    r"(#|//)[[:space:]]*TODO[:[:space:]]+MCP",
    r"(#|//)[[:space:]]*TODO[:[:space:]]+mcp",
    # `"available": false` in a committed JSON file.
    r'"available"[[:space:]]*:[[:space:]]*false',
    # `"mcp_call_id": "demo"` or any non-UUID synthesized id literal.
    r'"mcp_call_id"[[:space:]]*:[[:space:]]*"demo[^"]*"',
    # `"caller_person_id": "fake"` and obvious sentinel identifiers.
    r'"caller_person_id"[[:space:]]*:[[:space:]]*"(fake|demo|mock|stub|placeholder)"',
)


def test_N2_no_mcp_demo_seams_in_production_paths() -> None:
    """MCP-specific placeholder + demo-seam patterns are forbidden.

    The patterns above are precise (kind-anchored: comment markers,
    JSON keys with quoted values) so prose mentions in docstrings or
    plan files don't false-positive.

    Excluded paths: tests/, sim-harness/, voice-agent/, build outputs,
    and (for ``available: false``) the dashboard's JSON config files
    where the key may have a non-MCP meaning. The greps target the
    same production paths the rest of N2 enforces.
    """
    rows: list[str] = []
    for pattern in _MCP_REGRESSION_PATTERNS:
        for cp in ("apps", "packages"):
            rows.extend(
                _run_grep(
                    pattern,
                    path=cp,
                    include=["*.py", "*.ts", "*.tsx", "*.json"],
                    exclude_paths=[
                        "node_modules",
                        "__pycache__",
                        ".next",
                        "dist",
                        "build",
                        "tests",
                        "__tests__",
                        "sim-harness",
                        "voice-agent",
                    ],
                )
            )
    rows = _filter_self(rows, Path(__file__).name)
    # Allow the canonical empty-state literal in the dashboard's
    # ledger-client.ts — the accessor returns ``{available: false, ...}``
    # when WORMBASE_MCP_CATALOG_URL is unset or the catalog endpoint
    # 404s. That is the honest empty-state behaviour, not a demo seam.
    rows = [
        r for r in rows
        if "/lib/ledger-client.ts" not in r
    ]
    assert not rows, (
        f"MCP-specific demo-seam patterns reappeared — replace with "
        f"the live catalog read or honest empty state: {rows[:10]}"
    )


def test_N2_mcp_gate_fires_on_synthesized_audit_id(tmp_path: Path) -> None:
    """Positive test: the MCP gate catches a synthesized `mcp_call_id`.

    Same pattern as the onboarding-tail positive tests above: drop a
    fake fixture under a tmp tree, run the gate's grep helper, assert
    it surfaces the violation.
    """
    fake = tmp_path / "fake_apps" / "dashboard" / "components" / "regress.json"
    fake.parent.mkdir(parents=True)
    fake.write_text(
        '{"mcp_call_id": "demo-123", "caller_person_id": "fake"}\n',
        encoding="utf-8",
    )
    # Pattern 3 is the mcp_call_id literal; pattern 4 is the caller stub.
    for pat_idx in (3, 4):
        cmd = ["grep", "-rnIE", _MCP_REGRESSION_PATTERNS[pat_idx], str(fake.parent)]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
        assert proc.returncode == 0, (
            f"grep for {_MCP_REGRESSION_PATTERNS[pat_idx]!r} should have "
            f"matched the synthesized violation in {fake} but returned "
            f"rc={proc.returncode} stdout={proc.stdout!r} "
            f"stderr={proc.stderr!r}"
        )


def test_N2_onboarding_tail_gate_fires_on_pending_email_and_unknown_observer(
    tmp_path: Path,
) -> None:
    """Positive test: the gate would catch `pending_email`,
    `Unknown · observer`, and `pending-email-stub` regressions.

    Same structure as the dev-grant test above, one synthesized
    violator per pattern, all greps must succeed.
    """
    fake = tmp_path / "fake_apps" / "dashboard" / "components" / "regress.tsx"
    fake.parent.mkdir(parents=True)
    fake.write_text(
        "// regression cases the gate must catch\n"
        "const a = { pending_email: 'x@y.z' };\n"
        "const label = 'Unknown · observer';\n"
        "import { stub } from './pending-email-stub';\n",
        encoding="utf-8",
    )
    for pat in (
        _ONBOARDING_TAIL_REGRESSION_PATTERNS[1],  # pending_email
        _ONBOARDING_TAIL_REGRESSION_PATTERNS[2],  # Unknown · observer
        _ONBOARDING_TAIL_REGRESSION_PATTERNS[3],  # pending-email-stub
    ):
        cmd = ["grep", "-rnIE", pat, str(fake.parent)]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
        assert proc.returncode == 0, (
            f"grep for {pat!r} should have matched the synthesized "
            f"violation in {fake} but returned rc={proc.returncode} "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )


# ---------------------------------------------------------------------------
# W3.A14 — empty/loading/error invariants across every (app)/<tab>/page.tsx.
#
# The cleanup checklist in CLAUDE.md forbids "silent panels disguised as
# design." Sister W2 agents added per-tab empty-state copy to specific tabs;
# W3.A14 is the cross-cutting pass that enforces three invariants on every
# tab page:
#
#   1. No `return null` in a (app)/<tab>/page.tsx default export — a tab
#      with empty data must still render meaningful chrome (header + empty
#      state + retry path), never a blank pane.
#   2. Every tab must reference a visible empty-state primitive (EmptyState
#      component, an explicit empty-string copy in the page, or a child
#      component whose docstring promises an empty surface). The grep is
#      coarse — it requires the tab to import EmptyState OR mention the
#      string "empty" in JSX prose. False negatives are tolerable; false
#      positives are not, since the layer-1 invariant (no `return null`)
#      already catches the worst case.
#   3. `<Suspense>` calls in the (app) tree must NOT use `fallback={null}`
#      or `fallback={undefined}` — silent loading is the "blank pane"
#      seam in another guise. Tabs route their loading state through
#      PageSuspenseBoundary or PageBoundary (which compose a non-null
#      PageSkeleton fallback) or define a sibling `loading.tsx`.
# ---------------------------------------------------------------------------


_TAB_PAGES_DIR = REPO_ROOT / "apps/dashboard/app/(app)"


def _collect_tab_pages() -> list[Path]:
    """Return every `page.tsx` under the (app) route group.

    These are the production tab pages (`/sources`, `/people`, `/kpis`,
    `/trace`, …). Not included: `app/onboarding/`, `app/login/`, the
    layout files, or test fixtures.
    """
    if not _TAB_PAGES_DIR.exists():
        return []
    return sorted(_TAB_PAGES_DIR.rglob("page.tsx"))


# Trivial pages that DO NOT render a tab body — they only call
# `redirect()` from `next/navigation` and have no JSX. They legitimately
# lack EmptyState chrome, so they are excluded from the empty-state
# invariant check below. The `return null` invariant still applies (these
# files use `redirect()`, not `return null`).
_REDIRECT_ONLY_PAGES = (
    "settings/channels/page.tsx",
)


_DEFAULT_EXPORT_FN_RE = re.compile(
    r"^export\s+default\s+(?:async\s+)?function\b[^{]*\{",
    re.MULTILINE,
)


def _default_export_body(text: str) -> str | None:
    """Return the body (between the outermost ``{`` and matching ``}``) of
    the file's top-level ``export default function`` / ``export default
    async function`` declaration, or None if no such declaration is found.

    Brace-counting is naive (does not skip strings/comments) but adequate
    for the prettier-formatted page.tsx surface. Strings containing braces
    are extremely rare in tab-page bodies and would not introduce a
    ``return null;`` false-positive in practice.
    """
    m = _DEFAULT_EXPORT_FN_RE.search(text)
    if m is None:
        return None
    # m.end() points just after the opening `{`; walk until depth returns to 0.
    depth = 1
    i = m.end()
    while i < len(text) and depth > 0:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[m.end() : i]
        i += 1
    return None


def test_N2_no_return_null_in_tab_pages() -> None:
    """Every (app)/<tab>/page.tsx must render meaningful content, never null.

    A tab page that does `return null;` from its default export is a
    silent panel — the operator hits a blank route and can't tell whether
    it's loading, empty, or broken. Cleanup-checklist forbids this; the
    gate enforces it across the whole tab tree.

    The check is parse-aware: we extract only the body of the file's
    ``export default function`` (or ``export default async function``) by
    brace-counting from its opening ``{`` to the matching ``}``. Nested
    helper functions defined elsewhere in the file (e.g. ``firstString()``
    in ``kpis/compare/page.tsx``) are excluded — those legitimately return
    null. The invariant only applies to the outermost default-export
    function's direct return statements, which we find by scanning that
    body slice for ``^  return null;`` at the function's first indent
    level (two spaces, prettier default).
    """
    pages = _collect_tab_pages()
    assert pages, "no tab pages found — gate must run against a populated tree"
    violations: list[str] = []
    for p in pages:
        text = p.read_text("utf-8")
        body = _default_export_body(text)
        if body is None:
            # Page may use ``export default redirect(...)`` or another shape;
            # fall back to whole-file scan only for those alternative forms.
            # If the page does have a default-export function but we somehow
            # miss it, the regex below would over-report — but that's better
            # than missing a real silent panel.
            if re.search(r"^export\s+default\s+function", text, re.MULTILINE):
                # Default-export function was present but body extraction
                # failed; treat as a parse failure that should be noisy.
                violations.append(str(p.relative_to(REPO_ROOT)) + " (parse)")
            continue
        # Inside the default-export body, top-level ``return null;``
        # statements are indented one level (two spaces in prettier).
        if re.search(r"^  return null;\s*$", body, re.MULTILINE):
            violations.append(str(p.relative_to(REPO_ROOT)))
    assert not violations, (
        f"`return null` at the top-level default export of a tab page is "
        f"forbidden (silent panels disguised as design — see CLAUDE.md "
        f"cleanup checklist). Render an EmptyState or PageBoundary "
        f"surface instead: {violations}"
    )


_PAGE_IMPORT_RE = re.compile(
    r"import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)


def _resolve_relative_import(
    page_path: Path, import_specifier: str,
) -> Path | None:
    """Resolve a relative import specifier (e.g. `../components/Foo`) to
    an absolute path on disk. Returns None for non-relative specifiers
    (`@wormbase/design`, `next/link`, etc.).

    We try the common file extensions in order; the first match wins.
    Used by the empty-state gate to traverse a tab page's component
    imports and look for an empty-handling signal in any of them.
    """
    if not import_specifier.startswith("."):
        return None
    base = (page_path.parent / import_specifier).resolve()
    if base.is_dir():
        for ext in (".tsx", ".ts"):
            cand = base / f"index{ext}"
            if cand.exists():
                return cand
        return None
    for ext in (".tsx", ".ts"):
        cand = base.with_suffix(ext)
        if cand.exists():
            return cand
    return None


def _has_empty_signal(text: str) -> bool:
    """Return True when a file mentions an honest empty-state signal —
    either an ``EmptyState`` import / element, an ``empty`` token, or
    one of the empty-shaped copy idioms used across the dashboard
    (``No <thing> yet``, ``no <thing>``, ``unreachable``, ``unavailable``,
    ``error banner``).

    The check is intentionally lenient. The gate enforces "render
    something honest," not a single API. A page that swaps in a red
    error banner when the upstream is unreachable carries the same
    contract as a page that swaps in an EmptyState card — both prevent
    silent panes.
    """
    if "EmptyState" in text:
        return True
    if re.search(r"\bempty\b", text, re.IGNORECASE):
        return True
    if re.search(r"\bNo\s+\w+\s+yet\b", text):
        return True
    if re.search(r"\bno\s+\w+\s+yet\b", text):
        return True
    if re.search(r"\b(unreachable|unavailable|not\s+yet\s+running)\b", text):
        return True
    # Error banners that render an honest alert ("we couldn't load X",
    # "<service> proxy error", "down") count too — they prevent the
    # silent-panel failure mode.
    if re.search(
        r"\b(ProxyErrorBanner|ErrorBanner|down|coming[\s_-]?soon|"
        r"connector takes no configuration)\b",
        text,
        re.IGNORECASE,
    ):
        return True
    return False


def test_N2_every_tab_renders_empty_state_chrome() -> None:
    """Every tab page must wire in an honest empty-state path.

    The check requires each tab `page.tsx` to either:
      * import the `EmptyState` chrome primitive directly, OR
      * mention "empty" / "no <thing> yet" in its own JSX prose, OR
      * import a child component whose source file carries one of the
        above signals (the per-component empty branch — e.g.
        `data-testid="...-empty"` or "No <thing> yet" copy).

    Pure-redirect pages (`settings/channels`, etc.) are excluded — they
    have no body to render.

    The gate is intentionally lenient: any of the three signals counts.
    The aim is to forbid silent panels, not to prescribe a single API.
    """
    pages = [
        p
        for p in _collect_tab_pages()
        if not any(
            str(p).endswith(suffix) for suffix in _REDIRECT_ONLY_PAGES
        )
    ]
    assert pages, "no candidate tab pages found"
    violations: list[str] = []
    for p in pages:
        text = p.read_text("utf-8")
        if _has_empty_signal(text):
            continue
        # Walk the page's relative imports and look for the signal in
        # any of them. We don't recurse — one hop is enough to cover the
        # "page renders a drawer that handles empty" pattern.
        signal_found = False
        for match in _PAGE_IMPORT_RE.finditer(text):
            specifier = match.group(2).strip()
            resolved = _resolve_relative_import(p, specifier)
            if resolved is None:
                continue
            try:
                child_text = resolved.read_text("utf-8", errors="ignore")
            except OSError:
                continue
            if _has_empty_signal(child_text):
                signal_found = True
                break
        if not signal_found:
            violations.append(str(p.relative_to(REPO_ROOT)))
    assert not violations, (
        f"tab pages with no honest empty-state path — wire an EmptyState "
        f"component or a `length === 0` branch with intent-conveying copy: "
        f"{violations}"
    )


def test_N2_no_silent_suspense_fallback_in_tab_pages() -> None:
    """`<Suspense fallback={null}>` and `fallback={undefined}` are forbidden
    in (app)/<tab>/page.tsx files.

    Silent loading is the same demo seam as silent empty: the operator
    sees a blank pane and can't tell whether the tab is fetching or
    broken. PageSuspenseBoundary / PageBoundary supply a non-null
    skeleton; tab authors should compose those instead of inlining
    `<Suspense fallback={null}>`.

    Scope: this gate applies to TAB PAGES (`page.tsx` under the (app)
    route group). Layouts and chrome primitives may legitimately use
    `<Suspense fallback={null}>` for utility-mount cases (voice floater,
    background telemetry) where a fallback would be visual noise. Tab
    pages render as the operator's current view and must show editorial
    chrome whenever they're loading.
    """
    pages = _collect_tab_pages()
    if not pages:
        pytest.skip("no (app) tab pages found — gate skipped")
    patterns = (
        re.compile(r"fallback=\{null\}"),
        re.compile(r"fallback=\{undefined\}"),
    )
    violations: list[str] = []
    for p in pages:
        text = p.read_text("utf-8")
        for pat in patterns:
            if pat.search(text):
                # Locate the line number for nicer reporting.
                for idx, line in enumerate(text.splitlines(), 1):
                    if pat.search(line):
                        violations.append(
                            f"{p.relative_to(REPO_ROOT)}:{idx}: "
                            f"{line.strip()}"
                        )
                        break
    assert not violations, (
        f"`<Suspense fallback={{null}}>` / `fallback={{undefined}}` is a "
        f"silent loading seam in a tab page — wrap with "
        f"PageSuspenseBoundary or supply an editorial skeleton: "
        f"{violations[:10]}"
    )


def test_N2_W3A14_gate_fires_on_return_null_in_synthetic_tab(
    tmp_path: Path,
) -> None:
    """Positive test: the W3.A14 gate catches a synthesized `return null;`
    in a tab page.

    Same shape as the other onboarding-tail / MCP positive tests above —
    drop a fake page.tsx under a tmp tree, run the same regex, assert the
    violation is surfaced.
    """
    fake = tmp_path / "fake_apps" / "dashboard" / "app" / "(app)" / "x" / "page.tsx"
    fake.parent.mkdir(parents=True)
    fake.write_text(
        "export default function XPage() {\n"
        "  return null;\n"
        "}\n",
        encoding="utf-8",
    )
    text = fake.read_text("utf-8")
    assert re.search(
        r"^  return null;\s*$", text, re.MULTILINE,
    ), "regex must match the synthesized `return null;` violation"


def test_N2_W3A14_gate_fires_on_silent_suspense_in_synthetic_tab(
    tmp_path: Path,
) -> None:
    """Positive test: the silent-suspense gate catches a synthesized
    `<Suspense fallback={null}>` in a tab page.
    """
    fake = tmp_path / "fake_apps" / "dashboard" / "app" / "(app)" / "y" / "page.tsx"
    fake.parent.mkdir(parents=True)
    fake.write_text(
        "import { Suspense } from 'react';\n"
        "export default function YPage() {\n"
        "  return (\n"
        "    <Suspense fallback={null}>\n"
        "      <div>x</div>\n"
        "    </Suspense>\n"
        "  );\n"
        "}\n",
        encoding="utf-8",
    )
    cmd = ["grep", "-rnIE", r"fallback=\{null\}", str(fake.parent)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    assert proc.returncode == 0, (
        f"silent-suspense gate must surface fallback={{null}} in {fake} "
        f"but rc={proc.returncode} stdout={proc.stdout!r}"
    )


# ---------------------------------------------------------------------------
# Layer 2: rendered DOM placeholder grep (Playwright). Stub today.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("WORMBASE_PLAYWRIGHT_AVAILABLE") != "1",
    reason=(
        "Playwright DOM grep is the second N2 layer; gated on a "
        "running dashboard + WORMBASE_PLAYWRIGHT_AVAILABLE=1. The "
        "code-level grep above already fails the gate when demo "
        "seams reappear."
    ),
)
def test_N2_no_placeholders_in_rendered_dom() -> None:
    """Playwright-rendered DOM must not surface Lorem/TBD/FIXME/TODO."""
    pytest.skip("Playwright wiring lands with the live demo-day stack.")
