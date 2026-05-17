"""WhatsApp send rate limiting + exponential backoff (Wave E2).

Two generic, reusable async-safe components plus a WhatsApp-specific
wiring helper:

* :class:`TokenBucketRateLimiter` — per-key token bucket with
  configurable refill rate. Async-safe via per-bucket :class:`asyncio.Lock`.
  ``acquire`` blocks until a token is available (with optional max-wait
  timeout), so callers don't need to implement their own retry loop for
  the throttle case.
* :class:`ExponentialBackoff` — generic retry-with-backoff wrapper. Calls
  the wrapped callable; on a designated rate-limit error (the
  :class:`RateLimitedError` raised by the platform layer, or anything
  matched by a custom ``retry_on`` predicate), sleeps
  ``base * 2**attempt + jitter`` and retries up to ``max_retries`` times.
  After exhaustion, propagates the last error.
* :func:`with_whatsapp_rate_limit` — composition helper that builds a
  decorator wiring both components for the WhatsApp send path. Resolves
  per-tenant rate (``WORMBASE_WHATSAPP_RATE_PER_MIN_<TENANT>``), per-bot
  bucket, persistent-throttle ledger emission, and shared backoff
  configuration. Also reusable for non-WhatsApp adapters via the lower-
  level pieces.

**Why land this BEFORE Wave C2 wires the actual HTTP send.** WhatsApp
aggressively rate-limits unknown numbers; the moment Wave C2 ships,
burst sends would melt down. Wiring the limiter into the call path
*now* — even while ``send`` still raises ``NotImplementedError`` — means
C2 only has to write the HTTP call inside the existing decorator stack;
rate limiting is automatic from minute one.

**Persistent throttle audit.** When backoff exhausts (``max_retries``
attempts, all 429), the helper emits a ``policy_applied`` ledger entry
with ``policy_name="policy:whatsapp_rate_limit"``,
``rule="rate_limit_persistent_throttle"``, ``applies_to.scope="adapter"``,
``bot_phone=<phone>``. Single emission per ``(bot_phone, throttle_session)``
to avoid spamming the ledger when a throttle persists for hours; the
session resets on the first non-throttled call (bucket refilled and
limiter served a normal acquire).

**Schema-evolution doctrine compliance.** Reuses the existing
``policy_applied`` entry kind — no new entry kinds added. The emitter
is a callable injected at construction time (matches the
``ConversationSyncEmitter`` pattern in :mod:`whatsapp`); the
channel-adapters package still holds zero direct dependency on
``wormbase_ledger``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from collections import OrderedDict
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Defaults — configurable via env. Reads are at decorator-build time, not
# import time, so tests can synthesize WORMBASE_WHATSAPP_RATE_PER_MIN_<T>
# per-test via monkeypatch.
# ---------------------------------------------------------------------------

_DEFAULT_RATE_PER_MIN = 5
_DEFAULT_BACKOFF_BASE_S = 1.0
_DEFAULT_BACKOFF_MAX_RETRIES = 3
# Cap on the number of distinct (tenant, bot) buckets retained in the
# global registry. WhatsApp deployments today have <= a handful of bots
# per tenant; cap is generous against pathological churn.
_BUCKET_REGISTRY_MAX = 4096


class RateLimitedError(Exception):
    """Raised by a wrapped callable to signal a 429-equivalent response.

    The :class:`ExponentialBackoff` wrapper retries on this error.
    Callers (e.g. the WhatsApp HTTP send in Wave C2) translate platform-
    specific 429 / "Too Many Requests" / Baileys-rate-limit responses
    into this exception before raising; this keeps the backoff layer
    transport-agnostic.
    """


class RateLimitTimeoutError(Exception):
    """Raised when ``TokenBucketRateLimiter.acquire`` times out.

    Distinct from :class:`RateLimitedError` (which signals a server-side
    429) — this is local: the bucket didn't refill within the caller's
    ``max_wait_s`` budget.
    """


# ---------------------------------------------------------------------------
# TokenBucketRateLimiter — generic per-key, async-safe.
# ---------------------------------------------------------------------------


@dataclass
class _Bucket:
    """One bucket's worth of state.

    Tokens are tracked as a float for sub-second-resolution refill
    (a bucket capped at 5/min refills at 5/60 = 0.0833 tokens/sec).
    """

    capacity: float
    refill_rate_per_s: float
    tokens: float
    last_refill_at: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class TokenBucketRateLimiter:
    """Generic per-key token-bucket rate limiter.

    Each key (e.g. ``"<bot_phone>:<tenant>"`` for WhatsApp) maps to its
    own bucket. Buckets refill continuously at ``rate_per_min / 60``
    tokens per second, capped at ``rate_per_min``.

    ``acquire(key)`` blocks until a token is available (or until
    ``max_wait_s`` elapses, raising :class:`RateLimitTimeoutError`).
    The acquire is async-safe: the per-bucket lock serializes parallel
    callers on the same key, so two concurrent ``acquire(k)`` calls on
    the same key with one token left will see one token consumed and
    one wait.

    The implementation does NOT call ``asyncio.sleep`` while holding
    the bucket lock — the lock is released between refill checks so
    the cancellation surface stays clean.
    """

    def __init__(
        self,
        *,
        rate_per_min: int,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if rate_per_min <= 0:
            raise ValueError("rate_per_min must be > 0")
        self._rate_per_min = float(rate_per_min)
        self._refill_per_s = float(rate_per_min) / 60.0
        self._clock = clock or time.monotonic
        # OrderedDict for LRU eviction once the registry exceeds cap.
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()
        # Lock guarding bucket creation (registry mutation only — per-
        # bucket operations use the bucket's own lock).
        self._registry_lock = asyncio.Lock()

    @property
    def rate_per_min(self) -> int:
        return int(self._rate_per_min)

    async def _get_or_create_bucket(self, key: str) -> _Bucket:
        # Fast path: bucket exists.
        bucket = self._buckets.get(key)
        if bucket is not None:
            # Touch for LRU.
            self._buckets.move_to_end(key)
            return bucket
        # Slow path: create under the registry lock.
        async with self._registry_lock:
            bucket = self._buckets.get(key)
            if bucket is not None:
                self._buckets.move_to_end(key)
                return bucket
            now = self._clock()
            bucket = _Bucket(
                capacity=self._rate_per_min,
                refill_rate_per_s=self._refill_per_s,
                # Start full so a fresh key burst-allows up to capacity.
                tokens=self._rate_per_min,
                last_refill_at=now,
            )
            self._buckets[key] = bucket
            # Evict oldest if over cap.
            while len(self._buckets) > _BUCKET_REGISTRY_MAX:
                self._buckets.popitem(last=False)
            return bucket

    def _refill(self, bucket: _Bucket) -> None:
        """Refill the bucket based on elapsed time. Lock must be held."""
        now = self._clock()
        elapsed = now - bucket.last_refill_at
        if elapsed > 0:
            bucket.tokens = min(
                bucket.capacity,
                bucket.tokens + elapsed * bucket.refill_rate_per_s,
            )
            bucket.last_refill_at = now

    async def try_acquire(self, key: str) -> bool:
        """Non-blocking acquire. Returns True iff a token was consumed."""
        bucket = await self._get_or_create_bucket(key)
        async with bucket.lock:
            self._refill(bucket)
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True
            return False

    async def acquire(
        self,
        key: str,
        *,
        max_wait_s: float | None = None,
    ) -> None:
        """Acquire one token, blocking until available.

        If ``max_wait_s`` is set and the bucket doesn't refill within
        that wall-clock budget, raises :class:`RateLimitTimeoutError`.
        ``max_wait_s=None`` (default) waits indefinitely.

        The wait is implemented as a refill-aware sleep: the caller
        sleeps for (1.0 - tokens) / refill_rate_per_s seconds at most,
        then retries. This is precise (the next iteration succeeds
        immediately) and cancellation-safe (no busy-waiting).
        """
        bucket = await self._get_or_create_bucket(key)
        deadline: float | None = None
        if max_wait_s is not None:
            deadline = self._clock() + max_wait_s

        while True:
            async with bucket.lock:
                self._refill(bucket)
                if bucket.tokens >= 1.0:
                    bucket.tokens -= 1.0
                    return
                # Compute precise sleep duration: time until 1 token
                # accumulates from the current fractional balance.
                deficit = 1.0 - bucket.tokens
                wait_s = deficit / bucket.refill_rate_per_s
            # Lock released — apply deadline + sleep.
            if deadline is not None:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    raise RateLimitTimeoutError(
                        f"rate limit timed out for key={key} after "
                        f"max_wait_s={max_wait_s}"
                    )
                wait_s = min(wait_s, remaining)
            # Add a tiny epsilon so floating-point underflow doesn't
            # spin: the next iteration's refill must see a token.
            await asyncio.sleep(wait_s + 1e-3)

    def reset(self, key: str | None = None) -> None:
        """Test-only hook: drop a key's bucket (or all buckets)."""
        if key is None:
            self._buckets.clear()
        else:
            self._buckets.pop(key, None)


# ---------------------------------------------------------------------------
# ExponentialBackoff — generic.
# ---------------------------------------------------------------------------


class ExponentialBackoff:
    """Generic exponential-backoff wrapper for an async callable.

    On a designated retryable error (default: :class:`RateLimitedError`,
    overridable via ``retry_on``), sleeps
    ``base * 2**attempt + jitter`` seconds and retries.
    ``jitter`` is uniform in ``[0, base * 0.5]`` to avoid thundering
    herd. After ``max_retries`` attempts, propagates the last error.

    The wrapper is stateless across calls — a single instance can be
    used to wrap many callables. The retry-attempt count is per call,
    not per instance.
    """

    def __init__(
        self,
        *,
        base_s: float = _DEFAULT_BACKOFF_BASE_S,
        max_retries: int = _DEFAULT_BACKOFF_MAX_RETRIES,
        retry_on: type[BaseException] | tuple[type[BaseException], ...] = RateLimitedError,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        rng: Callable[[], float] | None = None,
        on_exhausted: Callable[[BaseException], Awaitable[None]] | None = None,
    ) -> None:
        if base_s < 0:
            raise ValueError("base_s must be >= 0")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self._base_s = base_s
        self._max_retries = max_retries
        self._retry_on = retry_on
        self._sleep = sleep or asyncio.sleep
        self._rng = rng or random.random
        self._on_exhausted = on_exhausted

    @property
    def max_retries(self) -> int:
        return self._max_retries

    async def call(
        self,
        fn: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Invoke ``fn(*args, **kwargs)`` with backoff on retryable errors."""
        last_exc: BaseException | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return await fn(*args, **kwargs)
            except self._retry_on as exc:
                last_exc = exc
                if attempt >= self._max_retries:
                    break
                # delay = base * 2^attempt + jitter ∈ [0, base*0.5]
                jitter = self._rng() * (self._base_s * 0.5)
                delay = self._base_s * (2 ** attempt) + jitter
                log.info(
                    "exponential_backoff: attempt=%d/%d sleeping=%.3fs "
                    "exc=%s",
                    attempt + 1, self._max_retries, delay, exc,
                )
                await self._sleep(delay)
        # Exhausted.
        assert last_exc is not None
        if self._on_exhausted is not None:
            try:
                await self._on_exhausted(last_exc)
            except Exception:  # noqa: BLE001
                log.exception(
                    "exponential_backoff: on_exhausted hook raised",
                )
        raise last_exc


# ---------------------------------------------------------------------------
# WhatsApp wiring — bucket registry + decorator builder.
# ---------------------------------------------------------------------------


# Module-level limiter registry, keyed by rate-per-min (so two tenants
# with different rate envs get distinct limiters AND distinct buckets).
# Single TokenBucketRateLimiter can host many keys; each key is one bot.
# Registry is keyed by rate so we don't conflate buckets across tenants
# that intentionally configured different rates.
_LIMITER_REGISTRY: dict[int, TokenBucketRateLimiter] = {}
_REGISTRY_LOCK = asyncio.Lock()

# Persistent-throttle session tracking: once the policy_applied entry
# fires for a (bot_phone, tenant), don't refire until the bucket has
# served at least one normal acquire (i.e. the throttle has lifted).
# Keyed by ``f"{tenant}:{bot_phone}"``.
_THROTTLE_SESSIONS: set[str] = set()
_THROTTLE_SESSIONS_LOCK = asyncio.Lock()


def _resolve_rate_per_min(tenant_id: str | None) -> int:
    """Resolve the rate from env, falling back to the default.

    Reads ``WORMBASE_WHATSAPP_RATE_PER_MIN_<TENANT>`` first (tenant key
    upper-cased to match B1/B4 convention), then the unsuffixed
    ``WORMBASE_WHATSAPP_RATE_PER_MIN``, then the default.
    """
    if tenant_id:
        key = f"WORMBASE_WHATSAPP_RATE_PER_MIN_{str(tenant_id).upper()}"
        raw = os.environ.get(key)
        if raw:
            try:
                val = int(raw)
                if val > 0:
                    return val
            except ValueError:
                log.warning(
                    "invalid %s=%r; falling back to default", key, raw,
                )
    raw = os.environ.get("WORMBASE_WHATSAPP_RATE_PER_MIN")
    if raw:
        try:
            val = int(raw)
            if val > 0:
                return val
        except ValueError:
            log.warning(
                "invalid WORMBASE_WHATSAPP_RATE_PER_MIN=%r; "
                "falling back to default", raw,
            )
    return _DEFAULT_RATE_PER_MIN


def _resolve_backoff_base() -> float:
    raw = os.environ.get("WORMBASE_WHATSAPP_BACKOFF_BASE_S")
    if raw:
        try:
            val = float(raw)
            if val >= 0:
                return val
        except ValueError:
            pass
    return _DEFAULT_BACKOFF_BASE_S


def _resolve_backoff_max_retries() -> int:
    raw = os.environ.get("WORMBASE_WHATSAPP_BACKOFF_MAX_RETRIES")
    if raw:
        try:
            val = int(raw)
            if val >= 0:
                return val
        except ValueError:
            pass
    return _DEFAULT_BACKOFF_MAX_RETRIES


async def _get_limiter_for_rate(rate_per_min: int) -> TokenBucketRateLimiter:
    limiter = _LIMITER_REGISTRY.get(rate_per_min)
    if limiter is not None:
        return limiter
    async with _REGISTRY_LOCK:
        limiter = _LIMITER_REGISTRY.get(rate_per_min)
        if limiter is not None:
            return limiter
        limiter = TokenBucketRateLimiter(rate_per_min=rate_per_min)
        _LIMITER_REGISTRY[rate_per_min] = limiter
        return limiter


def _bucket_key(tenant_id: str | None, bot_phone: str) -> str:
    """Compose the per-(tenant, bot) bucket key.

    Multi-tenant deployments distinguish by tenant; single-tenant
    fallback uses just the phone.
    """
    tenant_part = str(tenant_id) if tenant_id else "_"
    return f"{tenant_part}:{bot_phone}"


# Type alias for the policy_applied emitter — async callable matching
# LedgerWriter.emit_policy_applied's signature.
PolicyAppliedEmitter = Callable[..., Awaitable[Any]]


async def reset_throttle_session_for_tests(
    tenant_id: str | None,
    bot_phone: str,
) -> None:
    """Test-only: drop the throttle-session marker for a (tenant, bot).

    Production code never calls this — sessions reset organically when
    the bucket serves a normal acquire (see ``_clear_throttle_session``).
    """
    key = _bucket_key(tenant_id, bot_phone)
    async with _THROTTLE_SESSIONS_LOCK:
        _THROTTLE_SESSIONS.discard(key)


async def _is_throttle_session_active(key: str) -> bool:
    async with _THROTTLE_SESSIONS_LOCK:
        return key in _THROTTLE_SESSIONS


async def _mark_throttle_session(key: str) -> bool:
    """Insert the key into the active-throttle set.

    Returns True iff this is the first marker (i.e. caller should emit
    the policy_applied entry). Returns False if a session is already
    active for this key.
    """
    async with _THROTTLE_SESSIONS_LOCK:
        if key in _THROTTLE_SESSIONS:
            return False
        _THROTTLE_SESSIONS.add(key)
        return True


async def _clear_throttle_session(key: str) -> None:
    async with _THROTTLE_SESSIONS_LOCK:
        _THROTTLE_SESSIONS.discard(key)


def with_whatsapp_rate_limit(
    *,
    tenant_id: str | None,
    bot_phone: str,
    policy_emitter: PolicyAppliedEmitter | None = None,
    base_s: float | None = None,
    max_retries: int | None = None,
    max_wait_s: float | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Build a decorator that wraps an async send-style function with rate limit + backoff.

    Resolution order:

    * Rate per minute: ``WORMBASE_WHATSAPP_RATE_PER_MIN_<TENANT>`` env,
      then ``WORMBASE_WHATSAPP_RATE_PER_MIN`` (unsuffixed), then the
      default of 5.
    * Backoff base: ``base_s`` arg, then
      ``WORMBASE_WHATSAPP_BACKOFF_BASE_S``, then 1.0s.
    * Max retries: ``max_retries`` arg, then
      ``WORMBASE_WHATSAPP_BACKOFF_MAX_RETRIES``, then 3.

    The returned decorator wraps an async callable. When called:

    1. Acquires one token from the bucket keyed by
       ``(tenant_id, bot_phone)``. Blocks until available; honors
       ``max_wait_s`` if set.
    2. Invokes the wrapped callable inside an
       :class:`ExponentialBackoff` retry loop that re-tries on
       :class:`RateLimitedError`.
    3. On exhaustion, emits a single ``policy_applied`` entry per
       active throttle session (via ``policy_emitter`` if injected),
       then re-raises the last :class:`RateLimitedError`.

    The decorator can be applied to functions taking arbitrary
    arguments — the rate-limit acquire happens *before* the wrapped
    callable runs, so wrapped-callable args are not used for keying.

    ``policy_emitter`` is optional; when None, the persistent-throttle
    audit is logged but not written to the ledger. Production wiring
    passes ``LedgerWriter.emit_policy_applied`` (or any matching
    coroutine).
    """
    rate_per_min = _resolve_rate_per_min(tenant_id)
    base = base_s if base_s is not None else _resolve_backoff_base()
    retries = (
        max_retries if max_retries is not None
        else _resolve_backoff_max_retries()
    )
    bucket_key = _bucket_key(tenant_id, bot_phone)

    def decorator(
        fn: Callable[..., Awaitable[T]],
    ) -> Callable[..., Awaitable[T]]:
        async def _on_exhausted(exc: BaseException) -> None:
            """Emit a single policy_applied per throttle session."""
            should_emit = await _mark_throttle_session(bucket_key)
            if not should_emit:
                log.info(
                    "whatsapp rate-limit throttle persists "
                    "(session active) bot_phone=%s tenant=%s",
                    bot_phone, tenant_id,
                )
                return
            log.warning(
                "whatsapp rate-limit backoff exhausted: bot_phone=%s "
                "tenant=%s retries=%d last_exc=%s",
                bot_phone, tenant_id, retries, exc,
            )
            if policy_emitter is None:
                return
            try:
                await policy_emitter(
                    policy_name="policy:whatsapp_rate_limit",
                    rule="rate_limit_persistent_throttle",
                    applies_to={
                        "scope": "adapter",
                        "platform": "whatsapp",
                        "bot_phone": bot_phone,
                        "tenant_id": tenant_id,
                    },
                    bot_phone=bot_phone,
                    tenant_id=tenant_id,
                    outcome="applied",
                    rationale=(
                        "WhatsApp send: persistent 429 throttle after "
                        f"{retries} backoff retries"
                    ),
                )
            except Exception:  # noqa: BLE001
                log.exception(
                    "whatsapp policy_applied emit failed for throttle "
                    "audit (bot_phone=%s)", bot_phone,
                )

        backoff = ExponentialBackoff(
            base_s=base,
            max_retries=retries,
            on_exhausted=_on_exhausted,
        )

        async def wrapper(*args: Any, **kwargs: Any) -> T:
            limiter = await _get_limiter_for_rate(rate_per_min)
            await limiter.acquire(bucket_key, max_wait_s=max_wait_s)
            try:
                result = await backoff.call(fn, *args, **kwargs)
            except RateLimitedError:
                # Backoff exhausted; the on_exhausted hook ran and the
                # error propagates. The throttle session marker stays
                # set so subsequent calls in this session don't re-fire
                # the audit. The session clears only when a wrapped
                # call returns successfully (the throttle has lifted).
                raise
            # Successful round-trip — clear any prior throttle-session
            # marker so the next exhaustion (a NEW persistent-throttle
            # episode) emits its own audit. This is the semantic anchor
            # for "session": an unbroken run of 429s, demarcated by a
            # successful response on either side.
            await _clear_throttle_session(bucket_key)
            return result

        # Expose a couple of internals for tests + observability without
        # leaking the implementation detail of the limiter registry.
        wrapper._wb_rate_per_min = rate_per_min  # type: ignore[attr-defined]
        wrapper._wb_bucket_key = bucket_key  # type: ignore[attr-defined]
        wrapper._wb_backoff = backoff  # type: ignore[attr-defined]
        return wrapper

    return decorator


__all__ = [
    "ExponentialBackoff",
    "PolicyAppliedEmitter",
    "RateLimitTimeoutError",
    "RateLimitedError",
    "TokenBucketRateLimiter",
    "reset_throttle_session_for_tests",
    "with_whatsapp_rate_limit",
]
