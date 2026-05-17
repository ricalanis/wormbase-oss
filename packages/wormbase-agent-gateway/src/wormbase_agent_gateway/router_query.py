"""Broker vs federate dispatch for ``CompiledQuery`` execution.

Per Wave 2 Task 7 Step 3. Two execution modes:

- **Broker**  — agent-gateway holds the upstream account handle and
  runs the SQL on the agent's behalf. Returns rows + governed result
  metadata. Used by default.
- **Federate** — agent-gateway issues a ``ScopedDataToken`` and
  returns ``(governed_sql, scoped_jwt, callback_url)``; the agent
  executes upstream-direct and callbacks WormBase with the result
  hash. Used only when a per-domain policy explicitly opts in.

The dispatch decision is centralized in :func:`choose_route_mode` so
the policy lives in one place and can be made data-driven (per-domain
policy table) in a future Wave.

Driver
------
v1 supports Snowflake only. Multi-upstream dispatch is v1.1 — the
``BrokerExecutor`` raises ``NotImplementedError`` for non-Snowflake
upstreams so the call-site fails loudly rather than silently
fabricating rows. The Snowflake driver imports lazily so the test
suite does not pay the import cost when running against the env
broker only.
"""
from __future__ import annotations

import importlib
import time
from dataclasses import dataclass
from typing import Any, Literal

from wormbase_inference import AgentID

from .credential_broker import CredentialBroker, DataScope, ScopedToken
from .query_spec import CompiledQuery


# ---------------------------------------------------------------------------
# Route policy
# ---------------------------------------------------------------------------


def choose_route_mode(
    spec: Any,
    *,
    classification: str | None = None,
) -> Literal["broker", "federate"]:
    """v1 default policy — broker for everything classified at or above
    ``confidential``; federate is opt-in per resource and never picked
    by default in v1.

    The :class:`QuerySpec` is passed for forward-compatibility (so a
    Wave-3 per-spec policy table can dispatch on dimensions / measures
    / metric name) but is not consulted in v1.
    """
    if classification in ("confidential", "pii", "regulated"):
        return "broker"
    return "broker"


# ---------------------------------------------------------------------------
# BrokerExecutor — runs a CompiledQuery via hold_data_account
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BrokerExecutionResult:
    """Structured result from a broker-mode query.

    ``row_count`` is always populated. ``sample_rows`` carries up to
    ``sample_limit`` rows (default 5) as a list of dicts; ``rows_hash``
    is a stable sha256 of the canonical-encoded full result for the
    audit trail.
    """

    row_count: int
    sample_rows: tuple[dict[str, Any], ...]
    rows_hash: str
    latency_ms: int
    masking_policies_applied: tuple[str, ...]


@dataclass
class BrokerExecutor:
    """Runs CompiledQuery via ``CredentialBroker.hold_data_account`` + driver.

    Per-call lifecycle:
        1. broker.hold_data_account(install_id, upstream_kind)
        2. driver.connect(handle.payload).cursor.execute(sql, params)
        3. fetch rows, compute rows_hash, return BrokerExecutionResult.

    v1 supports ``upstream_kind == "snowflake"`` only. The driver
    import is lazy so test code can run against EnvCredentialBroker +
    a SnowflakeDriverStub injected via the ``driver`` keyword.
    """

    broker: CredentialBroker
    install_id: str
    sample_limit: int = 5
    # Optional driver injection — tests pass a stub; production passes
    # None and the executor imports snowflake.connector lazily.
    driver: Any | None = None

    async def execute(self, compiled: CompiledQuery) -> BrokerExecutionResult:
        if compiled.upstream_kind != "snowflake":
            raise NotImplementedError(
                f"BrokerExecutor v1 supports snowflake only; got "
                f"{compiled.upstream_kind!r}. Multi-upstream dispatch is v1.1."
            )
        handle = await self.broker.hold_data_account(
            self.install_id, upstream_kind=compiled.upstream_kind,
        )
        t0 = time.perf_counter()
        rows = await self._run_query(handle.payload, compiled)
        latency_ms = int((time.perf_counter() - t0) * 1000)

        # Hash the full row set BEFORE sampling so the audit row records a
        # stable fingerprint of every row that was returned.
        import hashlib
        import json
        canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode()
        rows_hash = hashlib.sha256(canonical).hexdigest()

        sample = tuple(rows[: self.sample_limit])
        return BrokerExecutionResult(
            row_count=len(rows),
            sample_rows=sample,
            rows_hash=rows_hash,
            latency_ms=latency_ms,
            masking_policies_applied=compiled.masking_policies_applied,
        )

    async def _run_query(
        self, account_payload: dict[str, Any], compiled: CompiledQuery,
    ) -> list[dict[str, Any]]:
        """Run the SQL via the injected driver, else the real Snowflake
        connector. Returns a list of dict rows (column-name keyed).

        The injected driver must expose a single coroutine
        ``query(account, sql, params) -> list[dict]``; this keeps the
        injection surface tiny and async-uniform with the rest of the
        agent-gateway.
        """
        if self.driver is not None:
            return await self.driver.query(
                account=account_payload,
                sql=compiled.sql,
                params=list(compiled.parameter_values),
            )
        # Production path — lazy-load snowflake-connector-python.
        try:
            sf = importlib.import_module("snowflake.connector")
        except ImportError as exc:  # pragma: no cover — env-dependent
            raise RuntimeError(
                "snowflake-connector-python is required for BrokerExecutor in "
                "production; install it or inject a `driver` for tests."
            ) from exc
        # Production-side connect is synchronous; we keep this branch
        # narrow because tests always inject. The call shape mirrors
        # what catalog-mirror uses for its Snowflake adapter.
        conn = sf.connect(**account_payload)  # pragma: no cover
        try:
            cur = conn.cursor(sf.DictCursor)
            cur.execute(compiled.sql, list(compiled.parameter_values))
            return cur.fetchall()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# FederateIssuer — emits a (sql, token, callback_url) tuple
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FederateIssuance:
    """Output of a federate-mode dispatch.

    The agent uses ``sql`` against the upstream directly with the
    ``token`` as its credential. After the upstream returns, the agent
    POSTs the result hash to ``callback_url`` so the gateway can
    record the actual ``row_count`` / ``rows_hash`` on the audit row.
    """

    sql: str
    token: ScopedToken
    callback_url: str


@dataclass
class FederateIssuer:
    """Issues a ScopedDataToken for federate-mode query execution.

    The broker mints a time-bounded data token scoped to the resource
    + masking the query implies; the issuer wraps it with the
    governed SQL + a callback URL the agent can hit to land its
    result hash.
    """

    broker: CredentialBroker
    callback_base_url: str = "https://gateway.example.invalid/federate/callback"

    async def issue(
        self,
        compiled: CompiledQuery,
        *,
        agent_id: AgentID,
        ttl_s: int = 900,
    ) -> FederateIssuance:
        scope = DataScope(
            resource_id=compiled.upstream_resource_id,
            row_filter=None,
            column_mask=compiled.masking_policies_applied,
        )
        token = await self.broker.issue_data_token(
            agent_id=agent_id.value,
            scope=scope,
            ttl_s=ttl_s,
        )
        return FederateIssuance(
            sql=compiled.sql,
            token=token,
            callback_url=f"{self.callback_base_url}/{token.token_id}",
        )


__all__ = [
    "BrokerExecutionResult",
    "BrokerExecutor",
    "FederateIssuance",
    "FederateIssuer",
    "choose_route_mode",
]
