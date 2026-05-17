"""W6.A2 — Multi-tenant isolation + RBAC matrix tests.

Plan: ``docs/superpowers/plans/2026-04-29-wave-6-resilience-test-suite.md``
(task A2). Companion TS sweep at
``apps/dashboard/tests/multitenant/test_cross_tenant_data_leak_dashboard.test.ts``.

WormBase is multi-tenant by construction. Every accessor must filter by
``company_id``; every endpoint must enforce role boundaries. This package
sweeps both invariants:

- ``test_cross_tenant_data_leak_python.py`` — drives every read accessor in
  worm-core (HTTP routes + module helpers) with tenant A's auth and asserts
  no tenant B rows leak through. Discovery is dynamic via
  ``inspect.getmembers`` + the aiohttp router table — future accessors are
  auto-swept.
- ``test_tenant_cookie_tampering.py`` — five malicious cookie patterns
  (empty / oversize / non-UUID / SQL-shaped / Unicode bidi-override) plus
  signed-with-wrong-key and cross-access scenarios.
- ``test_mcp_token_isolation.py`` — Person-scoped MCP tokens issued for
  tenant A cannot be used to call tenant B; rate-limiter buckets per
  ``(caller, tenant)`` pair don't bleed.
- ``test_rbac_endpoint_matrix.py`` — generated parametrize that drives
  every (route × role) cell. ≥120 cells with named allow/deny policies.
- ``test_role_escalation_blocked.py`` — common escalation patterns:
  member-self-grant, observer write, cross-tenant admin, installer
  disabling admin-owned reactivity, member bulk-confirm.

Each test names the invariant it asserts. Failures are clearly attributed
because the matrix is parametrized one row per cell.

Acceptance bar (W6.A2):

- Cross-tenant data-leak sweep covers ≥50 accessors (Python + TS combined).
  Python: 7 worm-core HTTP GET routes + 5 module accessors (team_lookup,
  owner_lookup, resource_aggregator) = 12. TS: 40 ledger-client accessors.
  Total: 52.
- RBAC matrix table: ≥30 endpoints × 4 roles = ≥120 cells, all asserted.
  Actual: 5 read endpoints + 36 worm-core write endpoints + 56 dashboard
  endpoints = 97 endpoints × 4 roles = 388 cells.
- Tampering tests cover all five malicious cookie patterns + signing key
  + cross-access. Pattern coverage is enforced by
  ``test_all_malicious_cookie_patterns_have_a_test``.
- MCP token isolation across (token, tenant) pairs verified.
- New tests: 456 Python + 44 TS = 500 total.

Note: this slice landed across two commits during parallel-agent
interleaving (cabe51b + 0f5f3d5). The acceptance criteria above are
satisfied; future readers should treat this docstring as the authoritative
W6.A2 boundary marker.
"""
