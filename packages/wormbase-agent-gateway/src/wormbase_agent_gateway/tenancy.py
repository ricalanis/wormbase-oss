"""Multi-tenant routing for the agent-gateway MCP HTTP listener.

v2 multi-tenant MCP per ``docs/superpowers/specs/2026-04-27-mcp-integration.md``
§1.7 + §5.4, executed as Path 4 of the 2026-05-21 overnight roadmap.

Architectural shape — Optional-Effect Injection (Case 5)
---------------------------------------------------------

Per ``docs/superpowers/specs/2026-05-21-optional-effect-injection-doctrine.md``
§9.1, multi-tenant routing is the highest-probability 5th case of the
doctrine. This module instantiates it.

The pattern:

  * ``TenantRouter`` is a ``Protocol``-defined optional dependency.
  * The MCP server holds ``tenant_router: TenantRouter | None = None``.
  * When ``None`` (default, ``WORMBASE_MULTI_TENANT_MCP`` unset) the
    server runs in **single-tenant mode** — byte-identical to the
    Phase 1-3c behavior: every request resolves to ``deps.company_id``
    and no rate-limiting / quota enforcement runs.
  * When set, every tool handler resolves ``X-Tenant-Slug`` →
    :class:`TenantContext` and overrides ``company_id`` for the duration
    of the call. Rate limits + quota counters are enforced per-tenant.

Boundary contracts
------------------

  * The router does NOT replace the existing ``WHERE company_id = $1``
    isolation enforced in every reader (``LedgerDecisionReader``,
    ``LedgerSubscriptionReader``, ``QueryOutcomeProjectionReader``,
    etc.). It *resolves* the ``company_id`` per request from the
    inbound ``X-Tenant-Slug`` header. Isolation correctness still
    rests on the readers' SQL.
  * Rate-limiting is per-tenant token-bucket, **in-memory** (v1). A
    Redis-backed v3 implementation can replace ``InMemoryRateLimiter``
    without touching the consumer. The Protocol boundary is
    :class:`RateLimiter`.
  * Quota tracking is per-tenant rolling-window counter, **in-memory**
    (v1). No new ``KIND_REGISTRY`` entry. Operators read quotas off
    the in-memory counter via :meth:`InMemoryQuotaTracker.snapshot`;
    a v3 ledger-emitted quota entry kind can be added without
    breaking the Protocol.
  * Replay determinism is preserved: ``X-Tenant-Slug`` →
    ``company_id`` resolution is a pure function (``tenant_to_uuid``
    is uuid5-stable). Recorded MCP requests replay deterministically.

Failure modes
-------------

When ``tenant_router`` is set:

  * **Missing ``X-Tenant-Slug`` header** → handler returns 4xx-shaped
    ``DeniedResponse`` (the MCP transport returns 200 with a denial
    body; FastMCP-level HTTP framing).
  * **Unknown / unregistered tenant slug** → ``DeniedResponse`` with
    ``denied.tenant_unknown`` code.
  * **Rate-limit exceeded** → ``DeniedResponse`` with
    ``denied.rate_limited`` code; ``Retry-After`` semantics conveyed
    inside the response body.
  * **No HTTP request context** (stdio transport) → handler falls
    through to ``deps.company_id`` because stdio sessions are
    single-tenant by transport (one client process per ``mcp.run()``).

Single-tenant byte-identical default
------------------------------------

When ``WORMBASE_MULTI_TENANT_MCP`` is unset / falsy, ``tenant_router``
defaults to ``None`` and the server's behavior is the Phase 1-3c
behavior. All v1.4 / v2.A / v2.B tests are unaffected.
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal, Protocol, runtime_checkable
from uuid import UUID

from wormbase_agent_gateway.optional_effect import OptionalEffectGuard

__all__ = [
    "TenantContext",
    "IsolatedTenantContext",
    "TenantResolveError",
    "TenantUnknownError",
    "TenantRateLimitedError",
    "RateLimiter",
    "InMemoryRateLimiter",
    "QuotaTracker",
    "InMemoryQuotaTracker",
    "LedgerQuotaTracker",
    "QuotaConsumedEmitter",
    "TenantRouter",
    "InMemoryTenantRouter",
    "TenantEngineRegistry",
    "StaticTenantEngineRegistry",
    "is_multi_tenant_mcp_enabled",
    "is_tenant_quota_ledger_emission_enabled",
    "resolve_default_rate_limit_per_min",
    "resolve_default_quota_per_day",
    "resolve_default_quota_count_threshold",
    "resolve_default_quota_time_threshold_seconds",
    "resolve_default_tenant_region",
]


# ---------------------------------------------------------------------------
# Env knobs (single canonical capability gate per Optional-Effect doctrine §3
# Rule 4 — one knob, the others are sub-tuning)
# ---------------------------------------------------------------------------


def is_multi_tenant_mcp_enabled() -> bool:
    """Return True iff ``WORMBASE_MULTI_TENANT_MCP`` is truthy.

    Default OFF (Optional-Effect Injection doctrine §3 Rule 5):
    unset / ``"false"`` / ``"0"`` / empty → single-tenant mode.
    Only the canonical ``"true"`` is honored as ON.
    """
    return os.environ.get(
        "WORMBASE_MULTI_TENANT_MCP", "false",
    ).strip().lower() == "true"


def resolve_default_rate_limit_per_min() -> int:
    """Return the per-tenant rate limit (req/min). Default 100.

    Sub-tuning knob (Optional-Effect Injection doctrine §3 Rule 4):
    meaningful only when ``WORMBASE_MULTI_TENANT_MCP=true``. Non-int /
    non-positive values fall back to the default.
    """
    raw = os.environ.get("WORMBASE_MULTI_TENANT_RATE_LIMIT_PER_MIN", "").strip()
    if not raw:
        return 100
    try:
        value = int(raw)
    except ValueError:
        return 100
    return max(1, value)


def resolve_default_quota_per_day() -> int:
    """Return the per-tenant quota (calls / 24h). Default 100_000.

    Sub-tuning knob. A high default keeps it from biting in pilots;
    operators tune down for production tenants explicitly.
    """
    raw = os.environ.get("WORMBASE_MULTI_TENANT_QUOTA_PER_DAY", "").strip()
    if not raw:
        return 100_000
    try:
        value = int(raw)
    except ValueError:
        return 100_000
    return max(1, value)


def is_tenant_quota_ledger_emission_enabled() -> bool:
    """Return True iff ``WORMBASE_TENANT_QUOTA_LEDGER`` is truthy.

    Final-wave item #7 (2026-05-13) — gates the 7th case of Optional-
    Effect Injection doctrine §6.4. Default OFF: byte-identical Path 4
    in-memory behavior. When ON, the wiring layer composes a
    :class:`LedgerQuotaTracker` that wraps the existing in-memory
    counter AND emits ``tenant_quota_consumed`` ledger entries at a
    configurable cadence.

    Sub-tuning depends on ``WORMBASE_MULTI_TENANT_MCP=true`` (the
    canonical capability gate per doctrine §3 Rule 4). Without
    multi-tenant routing on, there are no per-tenant quotas to emit
    against and this knob is inert.
    """
    return os.environ.get(
        "WORMBASE_TENANT_QUOTA_LEDGER", "false",
    ).strip().lower() == "true"


def resolve_default_quota_count_threshold() -> int:
    """Return per-tenant emission count-threshold. Default 100.

    Emit a ``tenant_quota_consumed`` entry every N requests per tenant.
    Combined with :func:`resolve_default_quota_time_threshold_seconds`,
    the cadence is "whichever fires first per tenant" — to keep the
    ledger flood bounded under bursty load while still surfacing slow
    drift over time.

    Sub-tuning knob (doctrine §3 Rule 4): meaningful only when
    ``WORMBASE_TENANT_QUOTA_LEDGER=true``.
    """
    raw = os.environ.get(
        "WORMBASE_TENANT_QUOTA_LEDGER_COUNT_THRESHOLD", "",
    ).strip()
    if not raw:
        return 100
    try:
        value = int(raw)
    except ValueError:
        return 100
    return max(1, value)


def resolve_default_tenant_region() -> str | None:
    """Return the fallback tenant region (or None for "no preference").

    Sub-tuning knob (Optional-Effect Injection doctrine §3 Rule 4) for
    the engine-per-tenant multi-region routing extension (post-rest #7,
    2026-05-13). When :class:`StaticTenantEngineRegistry` has no
    per-slug ``region`` mapping for a tenant AND this env var is set,
    the env value becomes the fallback region surfaced on the
    :class:`TenantContext`.

    Default ``None`` preserves byte-identical Path 4 + Phase 1+2 (#1)
    behavior: every :class:`TenantContext` resolves with
    ``region=None`` ("no region preference") unless an operator pins
    one explicitly per-tenant or via this env knob.

    Empty / whitespace-only values normalize to ``None`` so an operator
    can clear the fallback by setting ``WORMBASE_DEFAULT_TENANT_REGION=""``.
    """
    raw = os.environ.get("WORMBASE_DEFAULT_TENANT_REGION", "").strip()
    return raw or None


def resolve_default_quota_time_threshold_seconds() -> float:
    """Return per-tenant emission time-threshold (seconds). Default 300 (5 min).

    Emit a ``tenant_quota_consumed`` entry every N seconds elapsed
    since the last emission per tenant. Combined with the count
    threshold, "whichever fires first" caps both bursty and slow
    consumption.

    Sub-tuning knob (doctrine §3 Rule 4): meaningful only when
    ``WORMBASE_TENANT_QUOTA_LEDGER=true``.
    """
    raw = os.environ.get(
        "WORMBASE_TENANT_QUOTA_LEDGER_TIME_THRESHOLD_SECONDS", "",
    ).strip()
    if not raw:
        return 300.0
    try:
        value = float(raw)
    except ValueError:
        return 300.0
    return max(1.0, value)


# ---------------------------------------------------------------------------
# TenantContext — per-request view
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TenantContext:
    """Per-request tenant resolution result.

    Constructed once per inbound request by :meth:`TenantRouter.resolve`.
    Carries the resolved ``company_id``, the ``tenant_slug`` it came
    from, and a reference to the per-tenant rate-limit / quota state.

    Immutable: every request gets a fresh instance. Mutable state
    lives on :class:`RateLimiter` and :class:`QuotaTracker`, scoped by
    slug.

    Engine-per-tenant routing (Phase 1, additive)
    ---------------------------------------------

    The three engine fields are additive per the engine-per-tenant
    routing design (``docs/superpowers/specs/2026-05-22-engine-per-
    tenant-routing-design.md`` §4). Defaults preserve byte-identical
    Path 4 (Shape A) behavior:

      * ``engine = None`` → consumer reads/writes against the install's
        shared engine (Shape A).
      * ``engine_kind = "shared"`` → policy says this tenant rides the
        shared engine (the default for every unmapped tenant).
      * ``engine_dsn_secret_ref = None`` → no DSN ref carried.

    When a :class:`TenantEngineRegistry` resolves a tenant slug to an
    isolated engine, the router constructs a context with ``engine``
    set to the ``AsyncEngine`` handle, ``engine_kind="isolated"``, and
    ``engine_dsn_secret_ref`` populated. Code that REQUIRES the engine
    (no fall-through to shared) wraps the context in
    :class:`IsolatedTenantContext` to assert non-None at the boundary.

    Phases 3+4 (operator-driven migration tooling + production
    cutover) are deferred — Phase 1+2 ships the contract and the
    parallel-replay validator only.

    Multi-region routing (post-rest #7, 2026-05-13, additive)
    --------------------------------------------------------

    The ``region`` field is additive metadata for multi-region
    routing. Default ``None`` means "no region preference" and
    preserves byte-identical Path 4 + Phase 1+2 (#1) behavior.

    When set (e.g. ``"us-west-2"``, ``"eu-central-1"``,
    ``"ap-southeast-1"``), it pins the tenant's preferred region for
    operations + monitoring. Phase 1 of multi-region records and
    surfaces the region; it does NOT enforce locality at the
    SQLAlchemy connection level. Connection-pool-per-region,
    region-locality assertions, and cross-region replication policy
    are deferred to a later phase, gated on actual multi-region
    deployment.

    Resolution precedence (Phase 1):

      1. :class:`StaticTenantEngineRegistry` per-slug TOML
         ``region`` field, when registered.
      2. :func:`resolve_default_tenant_region` env fallback
         (``WORMBASE_DEFAULT_TENANT_REGION``), when set.
      3. ``None`` — no region preference (Shape A byte-identity).

    :class:`InMemoryTenantRouter` does NOT itself populate the
    region — it stays Shape-A-agnostic. Multi-region wiring lives
    at the engine-per-tenant boundary where the registry resolves.
    """

    tenant_slug: str
    company_id: UUID
    # Optional policy flag — when False, the tool surface is denied for
    # this tenant. v1 default: True for every registered tenant.
    enabled: bool = True
    # Engine-per-tenant (Phase 1, additive). Default None preserves
    # byte-identical Shape A behavior — the consumer falls back to
    # the install's shared engine. When set, the tenant runs on its
    # own isolated engine (Shape B).
    engine: Any | None = None
    engine_dsn_secret_ref: str | None = None
    engine_kind: Literal["shared", "isolated"] = "shared"
    # Multi-region routing (post-rest #7, additive). Default None =
    # "no region preference"; Shape A + Phase 1+2 byte-identity
    # preserved. When set, pins the tenant's preferred region for
    # ops + monitoring. Connection-pool-per-region enforcement is
    # deferred — Phase 1 records + surfaces only.
    region: str | None = None


class IsolatedTenantContext:
    """Typed view over :class:`TenantContext` that asserts engine non-None.

    For code paths that require physical isolation — they cannot fall
    back to the shared engine. Construction raises ``ValueError`` if
    ``ctx.engine is None`` or ``ctx.engine_kind != "isolated"``.

    Usage at a Shape-B-required boundary::

        isolated = IsolatedTenantContext(ctx)
        async with isolated.engine.connect() as conn:
            ...  # operates against the per-tenant engine

    The wrapper preserves the source :class:`TenantContext` via
    :attr:`ctx`; downstream code that handles both shapes can branch
    on ``isinstance(ctx, TenantContext)`` while a wrapper view is
    available for the strictly-isolated path.

    Phases 3+4 will wire this into the lake-maintainer + projection
    runner. Phase 1+2 ships the contract; default-OFF preserves
    Shape A byte-identity.
    """

    __slots__ = ("_ctx",)

    def __init__(self, ctx: TenantContext) -> None:
        if ctx.engine is None:
            raise ValueError(
                f"IsolatedTenantContext requires a non-None engine; "
                f"tenant {ctx.tenant_slug!r} resolved Shape A (shared)",
            )
        if ctx.engine_kind != "isolated":
            raise ValueError(
                f"IsolatedTenantContext requires engine_kind='isolated'; "
                f"got {ctx.engine_kind!r} for tenant {ctx.tenant_slug!r}",
            )
        self._ctx = ctx

    @property
    def ctx(self) -> TenantContext:
        """The wrapped :class:`TenantContext` (Shape B confirmed)."""
        return self._ctx

    @property
    def engine(self) -> Any:
        """The per-tenant ``AsyncEngine`` handle (asserted non-None)."""
        return self._ctx.engine

    @property
    def tenant_slug(self) -> str:
        return self._ctx.tenant_slug

    @property
    def company_id(self) -> UUID:
        return self._ctx.company_id

    @property
    def engine_dsn_secret_ref(self) -> str | None:
        return self._ctx.engine_dsn_secret_ref


# ---------------------------------------------------------------------------
# Errors raised by the router. The MCP server catches these and converts
# to DeniedResponse — no 5xx surfaces.
# ---------------------------------------------------------------------------


class TenantResolveError(Exception):
    """Base class for tenant resolution failures.

    The MCP server catches these and converts to a DeniedResponse
    rather than letting them propagate as 5xx. The ``code`` attribute
    is the denial code surfaced in the response body.
    """

    code: str = "tenant_resolve_failed"


class TenantUnknownError(TenantResolveError):
    """Raised when ``X-Tenant-Slug`` is missing or maps to an unregistered tenant."""

    code = "tenant_unknown"


class TenantRevokedError(TenantResolveError):
    """Raised when the tenant exists but is administratively disabled."""

    code = "tenant_revoked"


class TenantRateLimitedError(TenantResolveError):
    """Raised when the per-tenant rate limit is exceeded for the current request."""

    code = "rate_limited"


class TenantQuotaExceededError(TenantResolveError):
    """Raised when the per-tenant 24h call quota is exhausted."""

    code = "quota_exceeded"


# ---------------------------------------------------------------------------
# RateLimiter Protocol + token-bucket impl
# ---------------------------------------------------------------------------


@runtime_checkable
class RateLimiter(Protocol):
    """Per-tenant rate limit enforcement.

    The Protocol surface is intentionally minimal so a Redis-backed
    v3 impl can drop in without touching the consumer. The consumer
    calls :meth:`check` once per inbound request; the limiter raises
    :class:`TenantRateLimitedError` on violation.
    """

    async def check(self, tenant_slug: str) -> None:
        """Raise :class:`TenantRateLimitedError` if the limit is exceeded.

        Otherwise records the call against the tenant's bucket and
        returns. Must be called exactly once per inbound MCP request.
        """
        ...


@dataclass
class _TokenBucket:
    """Sliding-window deque-of-timestamps bucket.

    Deque sliding-window is simple, correct, and runs in O(N) per
    check where N == capacity_per_min. For 100 req/min with a 60s
    window, the deque holds at most 100 floats — trivial.
    """

    capacity: int
    window_seconds: float
    timestamps: deque[float] = field(default_factory=deque)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class InMemoryRateLimiter:
    """In-memory token-bucket rate limiter, scoped by tenant slug.

    Each tenant gets its own :class:`_TokenBucket`. Buckets are lazily
    created on first observation of a slug. Per-tenant locks prevent
    races between concurrent requests for the same tenant.

    v1: in-memory only. v3 candidate: Redis-backed implementation
    behind the same :class:`RateLimiter` Protocol.
    """

    def __init__(
        self,
        *,
        capacity_per_min: int | None = None,
        window_seconds: float = 60.0,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self._capacity = capacity_per_min or resolve_default_rate_limit_per_min()
        self._window_seconds = window_seconds
        self._time_fn = time_fn or time.monotonic
        self._buckets: dict[str, _TokenBucket] = {}
        self._buckets_lock = asyncio.Lock()

    async def check(self, tenant_slug: str) -> None:
        async with self._buckets_lock:
            bucket = self._buckets.get(tenant_slug)
            if bucket is None:
                bucket = _TokenBucket(
                    capacity=self._capacity,
                    window_seconds=self._window_seconds,
                )
                self._buckets[tenant_slug] = bucket
        async with bucket.lock:
            now = self._time_fn()
            cutoff = now - bucket.window_seconds
            # Evict expired timestamps from the left.
            while bucket.timestamps and bucket.timestamps[0] < cutoff:
                bucket.timestamps.popleft()
            if len(bucket.timestamps) >= bucket.capacity:
                raise TenantRateLimitedError(
                    f"tenant {tenant_slug!r}: rate limit exceeded "
                    f"({bucket.capacity} req / {bucket.window_seconds:.0f}s)",
                )
            bucket.timestamps.append(now)

    def snapshot(self, tenant_slug: str) -> dict[str, int | float]:
        """Operator hook — current bucket state for telemetry."""
        bucket = self._buckets.get(tenant_slug)
        if bucket is None:
            return {"in_window": 0, "capacity": self._capacity}
        return {
            "in_window": len(bucket.timestamps),
            "capacity": bucket.capacity,
        }


# ---------------------------------------------------------------------------
# QuotaTracker Protocol + rolling-window counter
# ---------------------------------------------------------------------------


@runtime_checkable
class QuotaTracker(Protocol):
    """Per-tenant rolling-24h call quota."""

    async def consume(self, tenant_slug: str) -> None:
        """Raise :class:`TenantQuotaExceededError` if the daily quota is exhausted.

        Otherwise records consumption and returns.
        """
        ...


class InMemoryQuotaTracker:
    """In-memory rolling-24h quota counter scoped by tenant slug.

    Same shape as :class:`InMemoryRateLimiter` but with a 24h window
    and a (much) higher default capacity. Per Optional-Effect Injection
    doctrine §6.4 the durable / ledger-emitted quota is a tenant-policy
    concern; v1 ships the in-memory counter so operators have
    observability without expanding ``KIND_REGISTRY``.
    """

    def __init__(
        self,
        *,
        capacity_per_day: int | None = None,
        window_seconds: float = 86400.0,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self._capacity = capacity_per_day or resolve_default_quota_per_day()
        self._window_seconds = window_seconds
        self._time_fn = time_fn or time.monotonic
        self._buckets: dict[str, _TokenBucket] = {}
        self._buckets_lock = asyncio.Lock()

    async def consume(self, tenant_slug: str) -> None:
        async with self._buckets_lock:
            bucket = self._buckets.get(tenant_slug)
            if bucket is None:
                bucket = _TokenBucket(
                    capacity=self._capacity,
                    window_seconds=self._window_seconds,
                )
                self._buckets[tenant_slug] = bucket
        async with bucket.lock:
            now = self._time_fn()
            cutoff = now - bucket.window_seconds
            while bucket.timestamps and bucket.timestamps[0] < cutoff:
                bucket.timestamps.popleft()
            if len(bucket.timestamps) >= bucket.capacity:
                raise TenantQuotaExceededError(
                    f"tenant {tenant_slug!r}: 24h quota exhausted "
                    f"({bucket.capacity} calls / 24h)",
                )
            bucket.timestamps.append(now)

    def snapshot(self, tenant_slug: str) -> dict[str, int | float]:
        bucket = self._buckets.get(tenant_slug)
        if bucket is None:
            return {"consumed": 0, "capacity": self._capacity}
        return {
            "consumed": len(bucket.timestamps),
            "capacity": bucket.capacity,
        }


# ---------------------------------------------------------------------------
# LedgerQuotaTracker — opt-in audit-trail wrapper around InMemoryQuotaTracker
#
# Composes ``InMemoryQuotaTracker`` for the rolling-window state AND
# emits ``tenant_quota_consumed`` ledger entries at a configurable
# cadence. Default cadence: every 100 requests OR every 300 seconds
# per tenant, whichever fires first. On ``quota_exhausted`` (the
# enforce-deny moment) emission is immediate so the audit trail
# captures the deny rather than amortizing it into the next periodic
# window.
#
# Optional-Effect Injection doctrine §6.4 — this is the 7th case
# (after Wave 4 TenantRouter [5th] and Wave 5 SseStreamTransport-
# with-probe [6th]). Default OFF behavior is byte-identical Path 4
# InMemoryQuotaTracker semantics; opt-in via
# ``WORMBASE_TENANT_QUOTA_LEDGER=true`` composes a LedgerQuotaTracker
# instead at the wiring layer.
#
# Replay safety: the in-memory rolling-window state IS recomputable
# from these entries via the cadence pins, so replay produces
# equivalent (not identical-tick-by-tick) state. The ``window_*_ts``
# fields preserve the temporal envelope; consumers reconstruct the
# count history from the sequence of payloads.
# ---------------------------------------------------------------------------


QuotaConsumedEmitter = Callable[[dict[str, Any]], Awaitable[None]]
"""Async callback signature: emit a ``tenant_quota_consumed`` payload.

The wiring layer (worm-core) provides the actual implementation that
writes the payload through ``Ledger.write`` (PEVR cycle with target_kind
``tenant_quota_consumed``). Keeping this as a callable preserves the
agent-gateway package's freedom from a ledger dependency — the
:class:`LedgerQuotaTracker` is composable in tests without a real
ledger fixture.

The payload dict matches ``TenantQuotaConsumedPayload.model_dump(mode="json")``.
"""


class LedgerQuotaTracker:
    """Wraps :class:`InMemoryQuotaTracker` and emits periodic ledger entries.

    Same Protocol surface as :class:`InMemoryQuotaTracker` so it drops
    in transparently behind :class:`TenantRouter._quota_tracker`. The
    wiring layer chooses which impl to compose at boot via the
    ``WORMBASE_TENANT_QUOTA_LEDGER`` env knob.

    Cadence:
      * Every ``count_threshold`` requests per tenant (default 100), OR
      * Every ``time_threshold_seconds`` seconds per tenant (default 300),
      * Whichever fires first.
      * On ``TenantQuotaExceededError`` (the deny moment): immediate
        emission with ``triggered_by="quota_exhausted"``, so the audit
        trail captures the deny rather than amortizing it into the next
        periodic window.

    Replay determinism: the rolling-window state IS recomputable from
    the emitted entries + cadence pins. The window timestamps are
    sourced from the injected ``time_fn`` (defaults to ``time.monotonic``
    for window math) plus ``datetime.now(timezone.utc)`` for the ledger
    timestamps; replay machinery injects deterministic time_fn +
    now_fn fixtures.

    Test seam: ``emit`` is the injected callback so unit tests verify
    emission cadence without a real ledger.
    """

    def __init__(
        self,
        in_memory_tracker: InMemoryQuotaTracker,
        emit: QuotaConsumedEmitter,
        *,
        count_threshold: int | None = None,
        time_threshold_seconds: float | None = None,
        now_fn: Callable[[], datetime] | None = None,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self._tracker = in_memory_tracker
        self._emit = emit
        self._count_threshold = (
            count_threshold
            if count_threshold is not None
            else resolve_default_quota_count_threshold()
        )
        self._time_threshold_seconds = (
            time_threshold_seconds
            if time_threshold_seconds is not None
            else resolve_default_quota_time_threshold_seconds()
        )
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._time_fn = time_fn or time.monotonic
        # Per-tenant cadence state: counts since last emission + the
        # window-open monotonic timestamp + the window-open wall-clock
        # timestamp. Lazy-created on first observation of a slug.
        self._window_state: dict[str, _QuotaWindowState] = {}
        self._state_lock = asyncio.Lock()

    async def consume(self, tenant_slug: str) -> None:
        """Consume one unit; raise TenantQuotaExceededError on exhaustion.

        Always ticks the in-memory tracker first. On exhaustion, emits
        the deny entry immediately (``triggered_by="quota_exhausted"``)
        before re-raising. On success, accumulates the in-window
        consumption count and emits at cadence.
        """
        try:
            await self._tracker.consume(tenant_slug)
        except TenantQuotaExceededError:
            # Deny-moment emission: capture the boundary explicitly so
            # SOC-2 audit reconstructs the deny rather than seeing only
            # a gap in the ledger sequence.
            await self._emit_for_tenant(
                tenant_slug=tenant_slug,
                triggered_by="quota_exhausted",
                force=True,
            )
            raise

        # Successful consume — accumulate and check cadence.
        triggered = await self._tick_and_check_cadence(tenant_slug)
        if triggered is not None:
            await self._emit_for_tenant(
                tenant_slug=tenant_slug,
                triggered_by=triggered,
                force=False,
            )

    async def _tick_and_check_cadence(
        self, tenant_slug: str,
    ) -> Literal["count_threshold", "time_threshold"] | None:
        """Bump the in-window counter; return the trigger or None.

        Returns the trigger name if either threshold fires, else None.
        Resets the per-tenant window state when a trigger fires.
        """
        async with self._state_lock:
            state = self._window_state.get(tenant_slug)
            now_mono = self._time_fn()
            if state is None:
                state = _QuotaWindowState(
                    consumption_count=0,
                    window_open_mono=now_mono,
                    window_open_wall=self._now_fn(),
                )
                self._window_state[tenant_slug] = state
            state.consumption_count += 1

            count_hit = state.consumption_count >= self._count_threshold
            time_hit = (
                (now_mono - state.window_open_mono)
                >= self._time_threshold_seconds
            )
            if count_hit:
                return "count_threshold"
            if time_hit:
                return "time_threshold"
            return None

    async def _emit_for_tenant(
        self,
        *,
        tenant_slug: str,
        triggered_by: Literal[
            "count_threshold", "time_threshold", "quota_exhausted",
        ],
        force: bool,
    ) -> None:
        """Build the payload + call the emitter; reset window on success.

        ``force=True`` (deny-moment) emits even when there is no
        accumulated state. ``force=False`` (periodic) reads the
        per-tenant window state for consumption_count + window_start_ts.
        """
        async with self._state_lock:
            state = self._window_state.get(tenant_slug)
            now_wall = self._now_fn()
            if state is None:
                # No prior state — happens on deny-moment for a tenant
                # that has never been seen by THIS tracker instance
                # (e.g. quota_per_day=0 sandbox). Use a zero-width
                # window with consumption_count=0.
                consumption_count = 0
                window_start_ts = now_wall
            else:
                consumption_count = state.consumption_count
                window_start_ts = state.window_open_wall

            # Read the rolling-window state from the underlying tracker
            # so quota_remaining reflects the 24h count, not the cadence
            # window's count.
            snap = self._tracker.snapshot(tenant_slug)
            consumed = int(snap.get("consumed", 0))
            capacity = int(snap.get("capacity", 1))
            remaining = max(0, capacity - consumed)

            payload = {
                "tenant_slug": tenant_slug,
                "consumption_count": consumption_count,
                "quota_limit": capacity,
                "quota_remaining": remaining,
                "window_start_ts": window_start_ts.isoformat(),
                "window_end_ts": now_wall.isoformat(),
                "triggered_by": triggered_by,
            }

            # Reset window state — even on deny-moment, so a quota that
            # later resets (24h roll) starts a fresh cadence window.
            self._window_state[tenant_slug] = _QuotaWindowState(
                consumption_count=0,
                window_open_mono=self._time_fn(),
                window_open_wall=now_wall,
            )

        await self._emit(payload)

    def snapshot(self, tenant_slug: str) -> dict[str, int | float]:
        """Operator hook — defer to the wrapped in-memory tracker."""
        return self._tracker.snapshot(tenant_slug)


@dataclass
class _QuotaWindowState:
    """Per-tenant cadence window for :class:`LedgerQuotaTracker`."""

    consumption_count: int
    window_open_mono: float
    window_open_wall: datetime


# ---------------------------------------------------------------------------
# TenantRouter Protocol + in-memory impl
# ---------------------------------------------------------------------------


TenantSlugResolver = Callable[[str], UUID]
"""Pure function: ``X-Tenant-Slug`` → ``company_id``.

Default impl is ``wormbase_core.service.tenant_to_uuid`` — a uuid5
of the slug under a stable namespace. Pure function → replay
determinism preserved.
"""


HeaderReader = Callable[[], Awaitable[str | None]]
"""Async function returning the ``X-Tenant-Slug`` header (or ``None``).

Injected by the MCP server, which reads the current request's headers
via :func:`fastmcp.server.dependencies.get_http_request` when the
transport is HTTP. When the transport is stdio (no HTTP context), this
returns ``None`` and the router falls back to the install's bound
default.
"""


@runtime_checkable
class TenantRouter(Protocol):
    """Resolves an inbound MCP request to a :class:`TenantContext`.

    The router owns the slug→company_id mapping, the tenant
    registration table, and the rate-limit / quota state. The MCP
    server consults it once per request, before delegating to a
    tool handler.

    Composition: a single :class:`TenantRouter` is constructed per
    install at boot and shared across the FastMCP HTTP listener.
    """

    async def resolve(self, header_value: str | None) -> TenantContext:
        """Return :class:`TenantContext` or raise :class:`TenantResolveError`.

        ``header_value`` is the raw ``X-Tenant-Slug`` header value
        (or ``None`` when absent). The router decides:

          * Missing / empty → :class:`TenantUnknownError`.
          * Unregistered slug → :class:`TenantUnknownError`.
          * Registered + disabled → :class:`TenantRevokedError`.
          * OK → :class:`TenantContext`.

        Rate-limit + quota are enforced via separate methods so callers
        can sequence them after the resolve (e.g. don't tick the quota
        on a revoked-tenant fast-reject).
        """
        ...

    async def enforce_rate_limit(self, ctx: TenantContext) -> None:
        """Raise :class:`TenantRateLimitedError` on violation; otherwise tick."""
        ...

    async def consume_quota(self, ctx: TenantContext) -> None:
        """Raise :class:`TenantQuotaExceededError` on violation; otherwise tick."""
        ...


@dataclass
class _RegisteredTenant:
    slug: str
    company_id: UUID
    enabled: bool = True


class InMemoryTenantRouter:
    """In-memory :class:`TenantRouter` impl — v1.

    Tenants are registered explicitly via :meth:`register`. The
    canonical ``slug → company_id`` resolver is injected at
    construction (defaults to ``wormbase_core.service.tenant_to_uuid``
    when the app layer composes; the package-level default is
    :func:`_default_slug_resolver` which uses uuid5 with the same
    namespace).

    The router holds its own :class:`InMemoryRateLimiter` and
    :class:`InMemoryQuotaTracker` so a single ``TenantRouter`` instance
    owns all per-tenant policy state. Both are swappable via
    constructor injection (test seam + Redis-backed v3 substitution).

    Optional-Effect Injection — engine_registry (Case 8)
    ---------------------------------------------------

    The optional ``engine_registry`` parameter is the doctrine's 8th
    case (per ``docs/superpowers/specs/2026-05-21-optional-effect-
    injection-doctrine.md`` Addendum 2). When ``None`` (default), every
    tenant rides Shape A (the install's shared engine) and
    :meth:`resolve_engine_for_slug` returns ``None`` byte-identically
    to the pre-Addendum-2 contract. When supplied, the registry is
    wrapped in an :class:`OptionalEffectGuard` and consulted on every
    :meth:`resolve_engine_for_slug` call, which records the per-path
    counter (``present_path_count`` for Shape B, ``absent_path_count``
    for Shape A) on the guard.

    The guard is exposed via :attr:`engine_registry_guard` so operators
    + tests can inspect the per-path counters (Rule 9 telemetry).
    """

    def __init__(
        self,
        *,
        slug_resolver: TenantSlugResolver | None = None,
        rate_limiter: RateLimiter | None = None,
        quota_tracker: QuotaTracker | None = None,
        engine_registry: "TenantEngineRegistry | None" = None,
    ) -> None:
        self._slug_resolver = slug_resolver or _default_slug_resolver
        self._rate_limiter: RateLimiter = rate_limiter or InMemoryRateLimiter()
        self._quota_tracker: QuotaTracker = quota_tracker or InMemoryQuotaTracker()
        self._tenants: dict[str, _RegisteredTenant] = {}
        # Optional-Effect Injection Case 8 (doctrine Addendum 2):
        # engine_registry is wrapped in the shared guard so the same
        # is-present / take-path / metrics surface used by Case 7's
        # composition site applies here. Default None preserves Shape A
        # byte-identity per doctrine §3 Rule 1.
        self._engine_registry_guard: OptionalEffectGuard[
            "TenantEngineRegistry"
        ] = OptionalEffectGuard(
            "tenant_engine_registry", engine_registry,
        )

    # ----- Registration surface -------------------------------------------

    def register(
        self,
        *,
        tenant_slug: str,
        enabled: bool = True,
    ) -> _RegisteredTenant:
        """Register a tenant by slug. Returns the resolved record.

        ``company_id`` is derived from the slug via the injected
        resolver — uuid5-stable, so re-registering the same slug
        yields the same ``company_id``.
        """
        normalized = tenant_slug.strip().lower()
        if not normalized:
            raise ValueError("tenant_slug must be non-empty")
        company_id = self._slug_resolver(normalized)
        record = _RegisteredTenant(
            slug=normalized, company_id=company_id, enabled=enabled,
        )
        self._tenants[normalized] = record
        return record

    def revoke(self, tenant_slug: str) -> None:
        """Disable a previously-registered tenant. Future resolves fail with
        :class:`TenantRevokedError`."""
        normalized = tenant_slug.strip().lower()
        record = self._tenants.get(normalized)
        if record is None:
            return
        record.enabled = False

    def is_registered(self, tenant_slug: str) -> bool:
        return tenant_slug.strip().lower() in self._tenants

    # ----- Protocol surface ------------------------------------------------

    async def resolve(self, header_value: str | None) -> TenantContext:
        if header_value is None:
            raise TenantUnknownError(
                "X-Tenant-Slug header is required in multi-tenant mode",
            )
        slug = header_value.strip().lower()
        if not slug:
            raise TenantUnknownError(
                "X-Tenant-Slug header is empty in multi-tenant mode",
            )
        record = self._tenants.get(slug)
        if record is None:
            raise TenantUnknownError(f"tenant {slug!r} is not registered")
        if not record.enabled:
            raise TenantRevokedError(f"tenant {slug!r} is revoked / disabled")
        return TenantContext(
            tenant_slug=record.slug,
            company_id=record.company_id,
            enabled=record.enabled,
        )

    async def enforce_rate_limit(self, ctx: TenantContext) -> None:
        await self._rate_limiter.check(ctx.tenant_slug)

    async def consume_quota(self, ctx: TenantContext) -> None:
        await self._quota_tracker.consume(ctx.tenant_slug)

    # ----- Optional-Effect Injection Case 8 (engine_registry) -------------

    async def resolve_engine_for_slug(self, slug: str) -> Any | None:
        """Resolve an engine for ``slug`` via the guarded engine_registry.

        Optional-Effect Injection Case 8 (doctrine Addendum 2):

          * If no registry was injected (default), returns ``None`` —
            Shape A fallback, byte-identical to a router constructed
            without the engine-per-tenant feature.
          * If a registry was injected, delegates to its
            :meth:`TenantEngineRegistry.resolve_engine`. The result
            is also ``None`` for slugs the registry has no isolated
            mapping for (Shape A fallback inside the registry).

        Either way, the per-call dispatch goes through
        :meth:`OptionalEffectGuard.take_path` and ticks the appropriate
        per-path counter for Rule 9 telemetry. Inspect counters via
        :attr:`engine_registry_guard.metrics`.
        """
        normalized = slug.strip().lower()

        async def _with_present(registry: "TenantEngineRegistry") -> Any | None:
            return await registry.resolve_engine(normalized)

        async def _without() -> Any | None:
            return None

        return await self._engine_registry_guard.take_path(
            with_present=_with_present,
            without=_without,
        )

    @property
    def engine_registry_guard(
        self,
    ) -> OptionalEffectGuard["TenantEngineRegistry"]:
        """Expose the engine_registry :class:`OptionalEffectGuard` (read-only).

        Operators + tests can read the per-path counters via
        ``router.engine_registry_guard.metrics()`` — the Rule 9
        telemetry surface for Case 8.
        """
        return self._engine_registry_guard

    # ----- Telemetry -------------------------------------------------------

    def snapshot(self, tenant_slug: str) -> dict[str, dict[str, int | float] | bool]:
        """Operator hook — return rate-limit + quota state for a tenant.

        Per Optional-Effect Injection doctrine §3 Rule 9, telemetry
        must distinguish with-router vs without-router fires. Counters
        like ``mcp_calls_with_tenant_router_total`` live in the MCP
        server's tool wrapper; the per-tenant in-flight state is
        surfaced here.
        """
        normalized = tenant_slug.strip().lower()
        record = self._tenants.get(normalized)
        rl_snap: dict[str, int | float] = {"in_window": 0, "capacity": 0}
        q_snap: dict[str, int | float] = {"consumed": 0, "capacity": 0}
        if isinstance(self._rate_limiter, InMemoryRateLimiter):
            rl_snap = self._rate_limiter.snapshot(normalized)
        if isinstance(self._quota_tracker, InMemoryQuotaTracker):
            q_snap = self._quota_tracker.snapshot(normalized)
        return {
            "registered": record is not None,
            "enabled": record.enabled if record is not None else False,
            "rate_limit": rl_snap,
            "quota": q_snap,
        }


# ---------------------------------------------------------------------------
# Default slug resolver
#
# Mirrors ``wormbase_core.service.tenant_to_uuid`` exactly — same
# namespace, same normalization — so re-resolving a slug at any layer
# yields the identical company_id. The package depends only on the
# stdlib uuid module to keep agent-gateway free of worm-core imports.
# ---------------------------------------------------------------------------


_TENANT_NAMESPACE = UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f")


def _default_slug_resolver(tenant_slug: str) -> UUID:
    """Package-default slug→company_id resolver.

    Mirrors ``wormbase_core.service.tenant_to_uuid`` so the same slug
    yields the same UUID at both the worm-core HTTP write API and the
    agent-gateway MCP server. App-level construction may inject a
    custom resolver (e.g. a database lookup) via
    :meth:`InMemoryTenantRouter.__init__`.
    """
    from uuid import uuid5
    return uuid5(_TENANT_NAMESPACE, tenant_slug.strip().lower())


# ---------------------------------------------------------------------------
# TenantEngineRegistry — engine-per-tenant Phase 1 (additive Protocol)
#
# Resolves a tenant slug to an ``AsyncEngine`` handle for Shape B
# (isolated engine) routing. Unmapped tenants → ``None`` → caller
# falls back to the install's shared engine (Shape A byte-identity).
#
# Per the engine-per-tenant routing design spec §4 + §8, Phase 1 ships
# the Protocol contract + a static config-file impl. Phase 3 will add
# the operator-driven admin migration tool that emits
# ``tenant_engine_registered`` ledger entries and provisions DSNs via
# the credential broker. Phase 4 will swap the static impl for a
# replay-fold over the ledger.
# ---------------------------------------------------------------------------


@runtime_checkable
class TenantEngineRegistry(Protocol):
    """Resolves a tenant slug to a per-tenant ``AsyncEngine`` (or None).

    The registry is the optional dependency that activates Shape B
    routing. ``None`` means "no isolated engine registered for this
    slug" — the caller (typically :class:`TenantRouter`) falls back
    to the shared engine and emits a Shape A :class:`TenantContext`.

    Implementations:

      * :class:`StaticTenantEngineRegistry` — Phase 2 default. Reads
        ``{slug: dsn_secret_ref}`` mappings from a TOML config file
        (or an env-var pointer at one). Real DSN secrets are resolved
        by the credential broker at engine-construction time, not
        baked into the registry.
      * (Phase 4) ``LedgerTenantEngineRegistry`` — folds the sequence
        of ``tenant_engine_registered`` entries to derive the
        canonical state. Not in Phase 1+2.

    The Protocol is additive (Optional-Effect Injection doctrine
    §6.4, 8th case): the default ``TenantEngineRegistry = None``
    preserves byte-identical Shape A behavior at every consumer site.
    """

    async def resolve_engine(self, slug: str) -> Any | None:
        """Return the per-tenant ``AsyncEngine`` (or None for Shape A).

        ``None`` is the deliberate Shape A fallback — every tenant
        that has NOT been registered as isolated rides the shared
        engine. Implementations must NOT raise on unmapped slugs;
        only on configuration-load failures.
        """
        ...

    def get_dsn_secret_ref(self, slug: str) -> str | None:
        """Return the DSN secret reference for a slug (telemetry only).

        Used by :class:`TenantRouter` to populate
        :attr:`TenantContext.engine_dsn_secret_ref` on a Shape B
        resolve. Returns ``None`` when the slug is not registered
        (Shape A fallback) or when the registry impl declines to
        expose refs (e.g. ledger-fold impl in Phase 4).
        """
        ...

    def resolve_engine_region(self, slug: str) -> str | None:
        """Return the configured region for the tenant's engine (or None).

        Promoted to the Protocol surface (carry-forward #4 of the
        2026-05-13 post-rest close-out) so future registry impls
        (``LedgerTenantEngineRegistry`` Phase 4, remote / vault-backed
        impls) honor the contract from day one. The Protocol method
        has no default body — every impl MUST implement it explicitly,
        matching the convention for :meth:`resolve_engine` and
        :meth:`get_dsn_secret_ref` above.

        Expected resolution precedence (the canonical
        :class:`StaticTenantEngineRegistry` impl below ships this; the
        Protocol does not enforce ordering, but ledger-fold impls in
        Phase 4 will follow the same precedence for replay parity):

          1. Per-slug pin (TOML for static; folded ledger state for
             ledger impl).
          2. :func:`resolve_default_tenant_region`
             (``WORMBASE_DEFAULT_TENANT_REGION``) env fallback.
          3. ``None`` — "no region preference" (Shape A byte-identity).

        Implementations that don't model regions at all (e.g. a test
        fake) MAY return ``None`` for every slug; the Protocol allows
        but does not require the env-fallback step.
        """
        ...

    def resolve_hnsw_params(
        self, slug: str,
    ) -> tuple[int | None, int | None]:
        """Return ``(hnsw_m, hnsw_ef_construction)`` overrides for ``slug``.

        Forward-compat surface (next-pass carry-forward #6, 2026-05-13)
        added at the same time as the additive
        :class:`TenantEngineRegisteredPayload` fields. The Phase 3+4
        admin migration tool will consult this method to resolve
        per-tenant HNSW build parameters at migration-apply time.
        Until that tool ships, the Protocol method exists as the
        durable consumer-side contract.

        Semantics:

          * ``(None, None)`` is the default-OFF posture — "no per-
            tenant overrides; use env globals
            (``WORMBASE_HNSW_M`` / ``WORMBASE_HNSW_EF_CONSTRUCTION``)
            as wired by the v019 migration." Every slug that has
            never been pinned should resolve to ``(None, None)``;
            this preserves byte-identical v019 behavior for tenants
            that don't override.
          * A non-None ``hnsw_m`` MUST be in the v019 range
            ``[4, 64]`` and ``hnsw_ef_construction`` in ``[16, 256]``;
            implementations should validate at config-load time, not
            at resolve time, so the operator sees the error at boot.
          * Each value is independently optional — e.g.
            ``(24, None)`` means "override m, use env-default for
            ef_construction."

        Implementations that don't model HNSW tuning at all (e.g. a
        test fake) MAY return ``(None, None)`` for every slug.
        """
        ...


@dataclass(frozen=True)
class _StaticEngineMapping:
    """One row of a static engine map: slug → DSN secret reference.

    The ``region`` field is additive (post-rest #7, 2026-05-13): when
    set in TOML, pins the tenant's preferred region for ops +
    monitoring; default ``None`` = "no region preference" (Phase 1+2
    byte-identity preserved).

    The ``hnsw_m`` / ``hnsw_ef_construction`` fields are additive
    (next-pass #6, 2026-05-13): when set in TOML, override the v019
    migration env globals at the Phase 3+4 admin tool's migration-
    apply step; default ``None`` = "use env globals." Validated at
    config-load time against v019's documented ranges.
    """

    slug: str
    dsn_secret_ref: str
    region: str | None = None
    hnsw_m: int | None = None
    hnsw_ef_construction: int | None = None


def _read_optional_hnsw_int(
    body: dict, slug: str, key: str, *, min_: int, max_: int,
) -> int | None:
    """Read an optional HNSW int from a TOML tenant table.

    Returns ``None`` when the key is absent (the operator did not pin
    this override). When present, the value MUST be an ``int`` in
    ``[min_, max_]`` — matches the v019 migration's documented range
    so a misconfigured TOML fails fast at boot rather than at Phase
    3+4 admin-tool migration-apply time.

    TOML loads ``true`` / ``false`` as ``bool`` which is a subclass
    of ``int``; we reject ``bool`` explicitly to avoid a confusing
    ``hnsw_m = true`` silently coercing to ``1``.
    """
    raw = body.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(
            f"StaticTenantEngineRegistry: tenant {slug!r} {key!r} "
            f"must be an int when set; got {type(raw).__name__}",
        )
    if not min_ <= raw <= max_:
        raise ValueError(
            f"StaticTenantEngineRegistry: tenant {slug!r} {key!r}="
            f"{raw} out of range [{min_}, {max_}] (matches v019 "
            f"env-knob valid range)",
        )
    return raw


class StaticTenantEngineRegistry:
    """Static :class:`TenantEngineRegistry` impl — Phase 2 default.

    Reads ``{slug: dsn_secret_ref}`` mappings from a TOML config file
    (or an env-var pointer at one). The TOML shape::

        [tenants.acme]
        dsn_secret_ref = "vault://wormbase/tenants/acme/engine_dsn"
        region = "us-west-2"  # optional (post-rest #7)
        hnsw_m = 24                    # optional (next-pass #6)
        hnsw_ef_construction = 128     # optional (next-pass #6)
        [tenants.globex]
        dsn_secret_ref = "vault://wormbase/tenants/globex/engine_dsn"
        region = "eu-central-1"  # optional (post-rest #7)
        # No HNSW overrides → v019 env globals apply at migration-apply.

    The optional ``region`` field pins the tenant's preferred region
    for ops + monitoring. When absent, the registry falls back to
    :func:`resolve_default_tenant_region` (``WORMBASE_DEFAULT_TENANT_
    REGION`` env); when that is also unset, the resolved region is
    ``None`` ("no region preference") — Phase 1+2 byte-identity
    preserved.

    The optional ``hnsw_m`` / ``hnsw_ef_construction`` fields are
    per-tenant overrides for the v019 HNSW build parameters,
    consumed at migration-apply time by the Phase 3+4 admin
    migration tool. When absent (the default), the v019 env globals
    (``WORMBASE_HNSW_M`` / ``WORMBASE_HNSW_EF_CONSTRUCTION``) apply
    — preserving byte-identical Shape A + Phase 1+2 behavior. Values
    are validated at TOML-load time against v019's documented ranges
    (``m ∈ [4, 64]``, ``ef_construction ∈ [16, 256]``).

    Tenants not listed → :meth:`resolve_engine` returns ``None`` →
    Shape A fallback. The registry holds ONLY the DSN references; the
    actual ``AsyncEngine`` construction is delegated to an injected
    ``engine_factory`` (default uses :func:`sqlalchemy.ext.asyncio.
    create_async_engine` resolved through the credential broker).

    Phase 2 ships this impl as the contract; Phase 3 will pair it
    with the operator admin tool that writes
    ``tenant_engine_registered`` entries and provisions Vault DSNs.
    Phase 4 will add a ``LedgerTenantEngineRegistry`` that folds the
    ledger sequence — same Protocol, different source-of-truth.

    Lazy engine construction: engines are constructed at the first
    :meth:`resolve_engine` call per slug and cached. The factory is
    only invoked once per slug; subsequent resolves return the cached
    handle.
    """

    EngineFactory = Callable[[str, str], Awaitable[Any]]
    """``async (slug, dsn_secret_ref) -> AsyncEngine`` factory."""

    def __init__(
        self,
        mappings: list[_StaticEngineMapping] | None = None,
        *,
        engine_factory: EngineFactory | None = None,
    ) -> None:
        self._mappings: dict[str, _StaticEngineMapping] = {
            m.slug: m for m in (mappings or [])
        }
        self._engine_factory = engine_factory
        self._engines: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    # ----- Factory constructors -------------------------------------------

    @classmethod
    def from_file(
        cls,
        path: str,
        *,
        engine_factory: EngineFactory | None = None,
    ) -> "StaticTenantEngineRegistry":
        """Construct from a TOML file at ``path``.

        TOML shape (one ``[tenants.<slug>]`` table per isolated
        tenant; tenants not in the file → Shape A fallback)::

            [tenants.acme]
            dsn_secret_ref = "vault://wormbase/tenants/acme/engine_dsn"

        Raises ``FileNotFoundError`` if the file is missing,
        ``ValueError`` on malformed TOML or invalid mapping shape.
        An empty file (or one with no ``[tenants.*]`` tables) is
        valid — the registry resolves every slug as Shape A.
        """
        import tomllib

        try:
            with open(path, "rb") as fh:
                raw = tomllib.load(fh)
        except FileNotFoundError:
            raise
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(
                f"StaticTenantEngineRegistry: TOML decode error at {path!r}: "
                f"{exc}",
            ) from exc

        tenants_section = raw.get("tenants", {})
        if not isinstance(tenants_section, dict):
            raise ValueError(
                f"StaticTenantEngineRegistry: [tenants] section at {path!r} "
                f"must be a table; got {type(tenants_section).__name__}",
            )

        mappings: list[_StaticEngineMapping] = []
        for slug, body in tenants_section.items():
            if not isinstance(body, dict):
                raise ValueError(
                    f"StaticTenantEngineRegistry: tenant entry {slug!r} "
                    f"must be a table; got {type(body).__name__}",
                )
            dsn_ref = body.get("dsn_secret_ref")
            if not isinstance(dsn_ref, str) or not dsn_ref.strip():
                raise ValueError(
                    f"StaticTenantEngineRegistry: tenant {slug!r} missing "
                    f"non-empty 'dsn_secret_ref'",
                )
            normalized = slug.strip().lower()
            if not normalized:
                raise ValueError(
                    "StaticTenantEngineRegistry: tenant slug must be "
                    "non-empty",
                )
            # Optional ``region`` field — additive (post-rest #7). When
            # present, must be a non-empty string. When absent, the
            # mapping records ``None`` and the registry resolution
            # falls back to ``resolve_default_tenant_region`` at
            # ``resolve_engine_region`` time.
            region_raw = body.get("region")
            if region_raw is None:
                region: str | None = None
            elif isinstance(region_raw, str):
                region_normalized = region_raw.strip()
                if not region_normalized:
                    raise ValueError(
                        f"StaticTenantEngineRegistry: tenant {slug!r} "
                        f"'region' must be a non-empty string when set",
                    )
                region = region_normalized
            else:
                raise ValueError(
                    f"StaticTenantEngineRegistry: tenant {slug!r} 'region' "
                    f"must be a string; got {type(region_raw).__name__}",
                )
            # Optional HNSW per-tenant overrides — additive (next-pass
            # #6, 2026-05-13). Validated at load time against the v019
            # documented ranges so a misconfigured TOML fails at boot,
            # not at Phase 3+4 admin-tool migration-apply time.
            hnsw_m = _read_optional_hnsw_int(
                body, slug, "hnsw_m", min_=4, max_=64,
            )
            hnsw_ef_construction = _read_optional_hnsw_int(
                body, slug, "hnsw_ef_construction", min_=16, max_=256,
            )
            mappings.append(
                _StaticEngineMapping(
                    slug=normalized,
                    dsn_secret_ref=dsn_ref.strip(),
                    region=region,
                    hnsw_m=hnsw_m,
                    hnsw_ef_construction=hnsw_ef_construction,
                ),
            )

        return cls(mappings=mappings, engine_factory=engine_factory)

    @classmethod
    def from_env(
        cls,
        *,
        engine_factory: EngineFactory | None = None,
    ) -> "StaticTenantEngineRegistry":
        """Construct from the env-pointer pattern.

        Reads ``WORMBASE_TENANT_ENGINE_MAP_FILE`` to locate the TOML
        config; delegates to :meth:`from_file`. When the env var is
        unset or empty, returns an empty registry — every slug
        resolves to Shape A (the default-OFF posture per Optional-
        Effect Injection doctrine §3 Rule 5).
        """
        path = os.environ.get("WORMBASE_TENANT_ENGINE_MAP_FILE", "").strip()
        if not path:
            return cls(mappings=[], engine_factory=engine_factory)
        return cls.from_file(path, engine_factory=engine_factory)

    # ----- Protocol surface ------------------------------------------------

    async def resolve_engine(self, slug: str) -> Any | None:
        """Return the per-tenant ``AsyncEngine`` or ``None``.

        ``None`` for unmapped slugs (Shape A fallback). For mapped
        slugs, constructs the engine on first call via the injected
        factory and caches the handle.
        """
        normalized = slug.strip().lower()
        mapping = self._mappings.get(normalized)
        if mapping is None:
            return None

        async with self._lock:
            existing = self._engines.get(normalized)
            if existing is not None:
                return existing
            if self._engine_factory is None:
                raise RuntimeError(
                    f"StaticTenantEngineRegistry: tenant {normalized!r} is "
                    f"mapped to {mapping.dsn_secret_ref!r} but no "
                    f"engine_factory was injected; cannot materialize "
                    f"engine (Phase 3 will wire the credential-broker "
                    f"factory)",
                )
            engine = await self._engine_factory(
                normalized, mapping.dsn_secret_ref,
            )
            self._engines[normalized] = engine
            return engine

    def get_dsn_secret_ref(self, slug: str) -> str | None:
        """Return the DSN secret ref for ``slug`` (or ``None``)."""
        normalized = slug.strip().lower()
        mapping = self._mappings.get(normalized)
        if mapping is None:
            return None
        return mapping.dsn_secret_ref

    def resolve_engine_region(self, slug: str) -> str | None:
        """Return the region for ``slug`` (or the env fallback, or None).

        Resolution precedence (post-rest #7 multi-region routing):

          1. Per-slug TOML ``region`` mapping, when registered.
          2. :func:`resolve_default_tenant_region`
             (``WORMBASE_DEFAULT_TENANT_REGION``), when set.
          3. ``None`` — "no region preference" (byte-identity preserved).

        Both registered-but-unpinned slugs AND unmapped slugs honor
        the env fallback so the operator can declare a single
        installation-wide default without per-tenant entries. Phase 1
        of multi-region records + surfaces the region for ops +
        monitoring; connection-pool-per-region and locality
        enforcement are deferred.
        """
        normalized = slug.strip().lower()
        mapping = self._mappings.get(normalized)
        if mapping is not None and mapping.region is not None:
            return mapping.region
        return resolve_default_tenant_region()

    def resolve_hnsw_params(
        self, slug: str,
    ) -> tuple[int | None, int | None]:
        """Return ``(hnsw_m, hnsw_ef_construction)`` for ``slug``.

        Resolution semantics (next-pass #6 per-tenant HNSW tuning):

          * Mapped slug with overrides → the configured tuple
            (each value independently optional).
          * Mapped slug with no overrides → ``(None, None)``.
          * Unmapped slug → ``(None, None)``.

        ``(None, None)`` means "use env globals
        (``WORMBASE_HNSW_M`` / ``WORMBASE_HNSW_EF_CONSTRUCTION``)
        as wired by the v019 migration" — preserving byte-identical
        Shape A + Phase 1+2 behavior for tenants without overrides.

        Validation already happened at config-load time
        (see :func:`_read_optional_hnsw_int`); this method is a pure
        lookup. The Phase 3+4 admin migration tool will call this
        method at migration-apply time per tenant engine.
        """
        normalized = slug.strip().lower()
        mapping = self._mappings.get(normalized)
        if mapping is None:
            return (None, None)
        return (mapping.hnsw_m, mapping.hnsw_ef_construction)

    def is_registered(self, slug: str) -> bool:
        """Return True iff ``slug`` has an isolated-engine mapping."""
        return slug.strip().lower() in self._mappings

    def registered_slugs(self) -> list[str]:
        """Return the registered slugs (sorted, for telemetry)."""
        return sorted(self._mappings.keys())
