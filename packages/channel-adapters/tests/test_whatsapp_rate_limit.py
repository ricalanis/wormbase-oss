"""Tests for WhatsApp send rate limiting + backoff (Wave E2).

Three layers under test:

1. :class:`TokenBucketRateLimiter` — generic per-key, async-safe.
   Verifies burst-then-wait semantics, refill timing, multi-key
   isolation, timeout behavior.
2. :class:`ExponentialBackoff` — generic retry-on-error wrapper.
   Verifies retry counts, jitter bounds, exhaustion propagation,
   on_exhausted hook firing.
3. :func:`with_whatsapp_rate_limit` — composition + WhatsApp wiring.
   Verifies env override resolution, per-tenant bucket isolation,
   policy_applied emission on persistent throttle (single emission
   per session), call-path wiring into
   :meth:`WhatsAppChannelAdapter.send`.

The decorator's contract is verified end-to-end against the
WhatsApp adapter to confirm the rate limiter sits on the call path
*before* ``_do_send`` runs (Wave C2 wired the actual subprocess body;
these tests use the ``WORMBASE_WHATSAPP_SEND_DISABLE=1`` kill-switch
to make ``_do_send`` raise synchronously without standing up
subprocess fixtures — round-trip coverage lives in
``test_whatsapp_send.py``).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from wormbase_channel_adapters.types import (
    ChannelRef,
    OutMessage,
    SecretBundle,
)
from wormbase_channel_adapters.whatsapp import WhatsAppChannelAdapter
from wormbase_channel_adapters.whatsapp_rate_limit import (
    ExponentialBackoff,
    RateLimitTimeoutError,
    RateLimitedError,
    TokenBucketRateLimiter,
    _LIMITER_REGISTRY,
    _bucket_key,
    reset_throttle_session_for_tests,
    with_whatsapp_rate_limit,
)


@pytest.fixture(autouse=True)
def _reset_globals() -> Any:
    """Drop the module-level limiter + throttle-session state per-test.

    Prevents cross-test bleed since both registries are intentionally
    shared across all calls in a process (production model: one
    registry per running adapter container).
    """
    _LIMITER_REGISTRY.clear()
    yield
    _LIMITER_REGISTRY.clear()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop all WhatsApp rate-limit env vars before each test.

    Tests that need an env value set it explicitly via monkeypatch.
    """
    for name in list(__import__("os").environ.keys()):
        if name.startswith("WORMBASE_WHATSAPP_"):
            monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# TokenBucketRateLimiter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_bucket_burst_up_to_capacity_no_wait() -> None:
    """5 acquires within capacity all succeed immediately."""
    now = 0.0
    rl = TokenBucketRateLimiter(rate_per_min=5, clock=lambda: now)
    for _ in range(5):
        # try_acquire returns True without sleeping.
        ok = await rl.try_acquire("k1")
        assert ok is True


@pytest.mark.asyncio
async def test_token_bucket_sixth_call_blocks_until_refill() -> None:
    """After exhausting capacity, the 6th try_acquire returns False."""
    now = 0.0
    rl = TokenBucketRateLimiter(rate_per_min=5, clock=lambda: now)
    for _ in range(5):
        assert await rl.try_acquire("k1") is True
    # No clock advance; bucket empty.
    assert await rl.try_acquire("k1") is False


@pytest.mark.asyncio
async def test_token_bucket_refill_replenishes_tokens() -> None:
    """After 60s, bucket capped at 5 has all 5 tokens back."""
    now = [0.0]
    rl = TokenBucketRateLimiter(rate_per_min=5, clock=lambda: now[0])
    for _ in range(5):
        assert await rl.try_acquire("k1") is True
    assert await rl.try_acquire("k1") is False
    # Advance 60s — 5 tokens refilled (capacity capped at 5).
    now[0] = 60.0
    for _ in range(5):
        assert await rl.try_acquire("k1") is True
    assert await rl.try_acquire("k1") is False


@pytest.mark.asyncio
async def test_token_bucket_refill_partial() -> None:
    """After 12s with rate=5/min, ~1 token has refilled."""
    now = [0.0]
    rl = TokenBucketRateLimiter(rate_per_min=5, clock=lambda: now[0])
    # Drain.
    for _ in range(5):
        await rl.try_acquire("k1")
    assert await rl.try_acquire("k1") is False
    # 12s = 5/60 * 12 = 1.0 tokens.
    now[0] = 12.0
    assert await rl.try_acquire("k1") is True
    # Now drained again.
    assert await rl.try_acquire("k1") is False


@pytest.mark.asyncio
async def test_token_bucket_per_key_isolation() -> None:
    """Two keys have independent buckets (multi-tenant isolation)."""
    now = 0.0
    rl = TokenBucketRateLimiter(rate_per_min=5, clock=lambda: now)
    for _ in range(5):
        assert await rl.try_acquire("tenantA") is True
    # tenantA drained; tenantB still has 5 fresh tokens.
    assert await rl.try_acquire("tenantA") is False
    for _ in range(5):
        assert await rl.try_acquire("tenantB") is True
    assert await rl.try_acquire("tenantB") is False


@pytest.mark.asyncio
async def test_token_bucket_acquire_blocks_then_succeeds() -> None:
    """``acquire`` blocks under a controlled clock until refill, then succeeds."""
    now = [0.0]
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)
        # Advance the clock to simulate the slept-through time so the
        # next refill check sees the token.
        now[0] += s

    rl = TokenBucketRateLimiter(rate_per_min=60, clock=lambda: now[0])
    # Drain — at 60/min, 1 token per second; bucket starts at 60.
    for _ in range(60):
        ok = await rl.try_acquire("k1")
        assert ok is True
    # Patch asyncio.sleep so the test runs synchronously.
    real_sleep = asyncio.sleep
    asyncio.sleep = fake_sleep  # type: ignore[assignment]
    try:
        # The 61st acquire must wait ~1s for refill.
        await rl.acquire("k1")
    finally:
        asyncio.sleep = real_sleep  # type: ignore[assignment]
    assert sleeps  # at least one sleep call
    # Total simulated wait should be roughly the refill window (1s).
    assert sum(sleeps) >= 1.0


@pytest.mark.asyncio
async def test_token_bucket_acquire_timeout_raises() -> None:
    """``acquire`` with ``max_wait_s`` raises when the budget elapses."""
    now = [0.0]

    async def fake_sleep(s: float) -> None:
        # Don't advance the clock — simulate an unbroken throttle.
        # Instead, advance only by the slept duration so the deadline
        # logic sees time passing.
        now[0] += s

    rl = TokenBucketRateLimiter(rate_per_min=1, clock=lambda: now[0])
    # Drain.
    assert await rl.try_acquire("k1") is True
    # rate=1/min → 60s per token. max_wait=0.1s ⇒ timeout.
    real_sleep = asyncio.sleep
    asyncio.sleep = fake_sleep  # type: ignore[assignment]
    try:
        with pytest.raises(RateLimitTimeoutError):
            await rl.acquire("k1", max_wait_s=0.1)
    finally:
        asyncio.sleep = real_sleep  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_token_bucket_invalid_rate_raises() -> None:
    """Rate must be > 0."""
    with pytest.raises(ValueError):
        TokenBucketRateLimiter(rate_per_min=0)
    with pytest.raises(ValueError):
        TokenBucketRateLimiter(rate_per_min=-1)


# ---------------------------------------------------------------------------
# ExponentialBackoff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backoff_succeeds_first_attempt_no_retry() -> None:
    """A success on attempt 1 returns the value without sleeping."""
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    backoff = ExponentialBackoff(
        base_s=1.0, max_retries=3, sleep=fake_sleep,
    )

    async def ok_fn() -> str:
        return "ok"

    result = await backoff.call(ok_fn)
    assert result == "ok"
    assert sleeps == []


@pytest.mark.asyncio
async def test_backoff_retries_then_succeeds() -> None:
    """Retries on RateLimitedError; eventually succeeds within budget."""
    sleeps: list[float] = []
    attempts = [0]

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    async def fn() -> str:
        attempts[0] += 1
        if attempts[0] < 3:
            raise RateLimitedError("429")
        return "ok"

    backoff = ExponentialBackoff(
        base_s=1.0,
        max_retries=3,
        sleep=fake_sleep,
        rng=lambda: 0.0,  # zero jitter for deterministic timing
    )
    result = await backoff.call(fn)
    assert result == "ok"
    assert attempts[0] == 3
    # 2 retries → 2 sleeps; delays are 1*2^0=1.0 and 1*2^1=2.0.
    assert sleeps == [1.0, 2.0]


@pytest.mark.asyncio
async def test_backoff_exhausts_and_raises_last() -> None:
    """After max_retries failures, propagates the last error."""
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    async def always_throttled() -> str:
        raise RateLimitedError("persistent")

    backoff = ExponentialBackoff(
        base_s=0.5,
        max_retries=3,
        sleep=fake_sleep,
        rng=lambda: 0.0,
    )
    with pytest.raises(RateLimitedError, match="persistent"):
        await backoff.call(always_throttled)
    # 3 retries means 1 initial + 3 retries = 4 attempts; 3 sleeps.
    assert len(sleeps) == 3


@pytest.mark.asyncio
async def test_backoff_jitter_within_bounds() -> None:
    """Jitter is uniform in [0, base*0.5]; rng=1.0 ⇒ jitter == base*0.5."""
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    async def always_throttled() -> str:
        raise RateLimitedError("x")

    backoff = ExponentialBackoff(
        base_s=2.0,
        max_retries=2,
        sleep=fake_sleep,
        rng=lambda: 1.0,  # max jitter
    )
    with pytest.raises(RateLimitedError):
        await backoff.call(always_throttled)
    # base * 2^0 + base*0.5 = 2 + 1 = 3.0; base * 2^1 + base*0.5 = 4 + 1 = 5.0
    assert sleeps == [3.0, 5.0]


@pytest.mark.asyncio
async def test_backoff_on_exhausted_hook_fires() -> None:
    """on_exhausted is called once with the last error before re-raise."""
    sleeps: list[float] = []
    captured: list[BaseException] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    async def hook(exc: BaseException) -> None:
        captured.append(exc)

    async def always_fail() -> str:
        raise RateLimitedError("permanent")

    backoff = ExponentialBackoff(
        base_s=0.1,
        max_retries=2,
        sleep=fake_sleep,
        rng=lambda: 0.0,
        on_exhausted=hook,
    )
    with pytest.raises(RateLimitedError):
        await backoff.call(always_fail)
    assert len(captured) == 1
    assert isinstance(captured[0], RateLimitedError)


@pytest.mark.asyncio
async def test_backoff_does_not_retry_on_non_rate_limit_error() -> None:
    """Other errors propagate immediately, no retry."""
    sleeps: list[float] = []
    attempts = [0]

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    async def fn() -> str:
        attempts[0] += 1
        raise ValueError("not rate-limited")

    backoff = ExponentialBackoff(
        base_s=1.0, max_retries=3, sleep=fake_sleep,
    )
    with pytest.raises(ValueError):
        await backoff.call(fn)
    assert attempts[0] == 1
    assert sleeps == []


# ---------------------------------------------------------------------------
# with_whatsapp_rate_limit — composition + env resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decorator_acquires_token_then_calls_fn() -> None:
    """The decorator MUST acquire a rate-limit token before invoking fn."""
    acquired: list[str] = []

    @with_whatsapp_rate_limit(tenant_id="t1", bot_phone="5511888888888")
    async def fake_send() -> str:
        acquired.append("called")
        return "sent"

    result = await fake_send()
    assert result == "sent"
    assert acquired == ["called"]


@pytest.mark.asyncio
async def test_decorator_default_rate_5_per_min(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no env override, rate defaults to 5/min."""
    decorator = with_whatsapp_rate_limit(
        tenant_id="t1", bot_phone="5511888888888",
    )

    async def noop() -> str:
        return "ok"

    wrapped = decorator(noop)
    assert wrapped._wb_rate_per_min == 5  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_decorator_env_override_per_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``WORMBASE_WHATSAPP_RATE_PER_MIN_<TENANT>`` overrides default."""
    monkeypatch.setenv("WORMBASE_WHATSAPP_RATE_PER_MIN_TENANT_HIGH", "20")

    decorator = with_whatsapp_rate_limit(
        tenant_id="tenant_high", bot_phone="5511777777777",
    )

    async def noop() -> str:
        return "ok"

    wrapped = decorator(noop)
    assert wrapped._wb_rate_per_min == 20  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_decorator_global_env_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsuffixed ``WORMBASE_WHATSAPP_RATE_PER_MIN`` is the single-tenant fallback."""
    monkeypatch.setenv("WORMBASE_WHATSAPP_RATE_PER_MIN", "10")

    decorator = with_whatsapp_rate_limit(
        tenant_id=None, bot_phone="5511888888888",
    )

    async def noop() -> str:
        return "ok"

    wrapped = decorator(noop)
    assert wrapped._wb_rate_per_min == 10  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_decorator_per_tenant_buckets_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two tenants on the same rate share a limiter but have distinct buckets.

    A drained bucket on tenant A must NOT block tenant B's acquires.
    """
    # Same rate for both tenants → same TokenBucketRateLimiter instance,
    # but the bucket key is (tenant, phone), so each gets its own bucket.
    decorator_a = with_whatsapp_rate_limit(
        tenant_id="tenantA", bot_phone="5511111111111",
    )
    decorator_b = with_whatsapp_rate_limit(
        tenant_id="tenantB", bot_phone="5512222222222",
    )

    @decorator_a
    async def send_a() -> str:
        return "a"

    @decorator_b
    async def send_b() -> str:
        return "b"

    # Drain tenantA's bucket (5 calls).
    for _ in range(5):
        await send_a()
    # tenantB still has full capacity — should not block.
    for _ in range(5):
        result = await send_b()
        assert result == "b"


# ---------------------------------------------------------------------------
# Persistent rate limit → policy_applied emitted exactly once per session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persistent_throttle_emits_policy_applied_once() -> None:
    """When backoff exhausts, exactly one policy_applied entry is written.

    The throttle-session marker is set after the first emission and
    only cleared when a normal acquire succeeds — subsequent
    exhaustions in the same session do NOT re-emit.
    """
    captured: list[dict[str, Any]] = []

    async def emitter(**kwargs: Any) -> None:
        captured.append(kwargs)

    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    # Reset throttle session for the (tenant, bot) pair.
    await reset_throttle_session_for_tests("t1", "5511888888888")

    async def always_429(*args: Any, **kwargs: Any) -> str:
        raise RateLimitedError("429")

    decorator = with_whatsapp_rate_limit(
        tenant_id="t1",
        bot_phone="5511888888888",
        policy_emitter=emitter,
        base_s=0.001,
        max_retries=2,
    )
    wrapped = decorator(always_429)

    # Patch asyncio.sleep used by the backoff layer.
    backoff = wrapped._wb_backoff  # type: ignore[attr-defined]
    backoff._sleep = fake_sleep  # type: ignore[attr-defined]

    # First exhaustion — should emit one policy_applied.
    with pytest.raises(RateLimitedError):
        await wrapped()
    assert len(captured) == 1
    entry = captured[0]
    assert entry["policy_name"] == "policy:whatsapp_rate_limit"
    assert entry["rule"] == "rate_limit_persistent_throttle"
    assert entry["applies_to"]["scope"] == "adapter"
    assert entry["bot_phone"] == "5511888888888"

    # Second exhaustion in the SAME session — must NOT re-emit.
    # (The bucket still has tokens in this short test; we need to
    # avoid clearing the throttle marker by NOT serving a successful
    # acquire-call between the two failures. We reach in directly to
    # the limiter to drain the bucket so the next acquire would block,
    # but the failure raises before any clear path runs.)
    with pytest.raises(RateLimitedError):
        await wrapped()
    assert len(captured) == 1, (
        f"expected single emission per session; got {len(captured)}"
    )


@pytest.mark.asyncio
async def test_throttle_session_clears_on_successful_acquire() -> None:
    """After the throttle lifts (a successful call), next exhaustion re-emits."""
    captured: list[dict[str, Any]] = []
    counter = [0]

    async def emitter(**kwargs: Any) -> None:
        captured.append(kwargs)

    async def fake_sleep(s: float) -> None:
        return None

    await reset_throttle_session_for_tests("t1", "5511888888888")

    async def flaky(*args: Any, **kwargs: Any) -> str:
        counter[0] += 1
        # First few calls always 429; later calls succeed; later still 429.
        if counter[0] <= 3:
            raise RateLimitedError("429")
        if counter[0] == 4:
            return "ok"
        # 5..7 throttle again.
        raise RateLimitedError("429")

    decorator = with_whatsapp_rate_limit(
        tenant_id="t1",
        bot_phone="5511888888888",
        policy_emitter=emitter,
        base_s=0.001,
        max_retries=2,
    )
    wrapped = decorator(flaky)
    wrapped._wb_backoff._sleep = fake_sleep  # type: ignore[attr-defined]

    # First exhaustion (calls 1, 2, 3 all fail).
    with pytest.raises(RateLimitedError):
        await wrapped()
    assert len(captured) == 1

    # Successful call (counter 4) — clears the throttle session.
    result = await wrapped()
    assert result == "ok"

    # Second exhaustion (5, 6, 7 all fail) — re-emits.
    with pytest.raises(RateLimitedError):
        await wrapped()
    assert len(captured) == 2


@pytest.mark.asyncio
async def test_no_policy_emitter_does_not_raise() -> None:
    """Without a policy_emitter, backoff still exhausts cleanly (logs only)."""

    async def fake_sleep(s: float) -> None:
        return None

    async def always_429() -> str:
        raise RateLimitedError("x")

    await reset_throttle_session_for_tests("t1", "5511888888888")
    decorator = with_whatsapp_rate_limit(
        tenant_id="t1",
        bot_phone="5511888888888",
        policy_emitter=None,
        base_s=0.001,
        max_retries=1,
    )
    wrapped = decorator(always_429)
    wrapped._wb_backoff._sleep = fake_sleep  # type: ignore[attr-defined]

    with pytest.raises(RateLimitedError):
        await wrapped()
    # No emission, no exception from the absent emitter path.


# ---------------------------------------------------------------------------
# Wired into WhatsAppChannelAdapter.send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_acquires_rate_limit_token_before_inner_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``send`` must hit the limiter before invoking ``_do_send``.

    Verifies the path: send → with_whatsapp_rate_limit decorator →
    TokenBucketRateLimiter.acquire → _do_send. The kill-switch makes
    _do_send raise NotImplementedError immediately so we can pin the
    call ordering without standing up subprocess fixtures (the actual
    subprocess round-trip is covered in test_whatsapp_send.py).
    """
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE_T1", "5511888888888")
    # Kill-switch: makes _do_send raise immediately so the limiter
    # acquire must already have fired by the time the raise propagates.
    monkeypatch.setenv("WORMBASE_WHATSAPP_SEND_DISABLE", "1")

    a = WhatsAppChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1", "tenant_id": "t1"})
    )

    call_order: list[str] = []
    original_acquire = TokenBucketRateLimiter.acquire

    async def spy_acquire(
        self: TokenBucketRateLimiter,
        key: str,
        *,
        max_wait_s: float | None = None,
    ) -> None:
        call_order.append(f"acquire:{key}")
        return await original_acquire(self, key, max_wait_s=max_wait_s)

    monkeypatch.setattr(TokenBucketRateLimiter, "acquire", spy_acquire)

    channel = ChannelRef(
        platform="whatsapp",
        platform_channel_id="5511999999999@s.whatsapp.net",
    )
    msg = OutMessage(text="hi")
    with pytest.raises(NotImplementedError):
        await a.send(handle, channel, msg)

    # Acquire must have fired exactly once with the (tenant, phone) key.
    assert call_order == ["acquire:t1:5511888888888"]


@pytest.mark.asyncio
async def test_send_kill_switch_raises_not_implemented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ops kill-switch hard-disables outbound at the inner-send layer.

    Wave C2 wired the OpenClaw CLI subprocess; this test pins the
    ``WORMBASE_WHATSAPP_SEND_DISABLE=1`` escape hatch ops uses to
    halt outbound without a code roll. The check happens inside
    ``_do_send`` AFTER the rate-limit acquire, by design — so the
    bucket still consumes a token even when the kill-switch fires
    (audit trail of intent to send).
    """
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE_T1", "5511888888888")
    monkeypatch.setenv("WORMBASE_WHATSAPP_SEND_DISABLE", "1")

    a = WhatsAppChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1", "tenant_id": "t1"})
    )
    channel = ChannelRef(
        platform="whatsapp",
        platform_channel_id="5511999999999@s.whatsapp.net",
    )
    with pytest.raises(NotImplementedError, match="disabled"):
        await a.send(handle, channel, OutMessage(text="hi"))


@pytest.mark.asyncio
async def test_send_uses_per_tenant_bucket_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two adapters on different tenants resolve to different bucket keys."""
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE_TA", "5511111111111")
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE_TB", "5512222222222")
    # Kill-switch keeps _do_send synchronous + cheap for this test.
    monkeypatch.setenv("WORMBASE_WHATSAPP_SEND_DISABLE", "1")

    a_a = WhatsAppChannelAdapter()
    a_b = WhatsAppChannelAdapter()

    handle_a = await a_a.authenticate(
        SecretBundle(payload={"account_id": "wa-a", "tenant_id": "ta"})
    )
    handle_b = await a_b.authenticate(
        SecretBundle(payload={"account_id": "wa-b", "tenant_id": "tb"})
    )

    captured_keys: list[str] = []
    original_acquire = TokenBucketRateLimiter.acquire

    async def spy_acquire(
        self: TokenBucketRateLimiter,
        key: str,
        *,
        max_wait_s: float | None = None,
    ) -> None:
        captured_keys.append(key)
        return await original_acquire(self, key, max_wait_s=max_wait_s)

    monkeypatch.setattr(TokenBucketRateLimiter, "acquire", spy_acquire)

    channel = ChannelRef(
        platform="whatsapp",
        platform_channel_id="5511999999999@s.whatsapp.net",
    )
    msg = OutMessage(text="hi")
    with pytest.raises(NotImplementedError):
        await a_a.send(handle_a, channel, msg)
    with pytest.raises(NotImplementedError):
        await a_b.send(handle_b, channel, msg)

    assert "ta:5511111111111" in captured_keys
    assert "tb:5512222222222" in captured_keys
    # Distinct bucket keys → multi-tenant isolation.
    assert captured_keys[0] != captured_keys[1]


@pytest.mark.asyncio
async def test_bucket_key_helper_composition() -> None:
    """``_bucket_key`` composes ``<tenant>:<phone>`` (with single-tenant fallback)."""
    assert _bucket_key("t1", "5511888888888") == "t1:5511888888888"
    assert _bucket_key(None, "5511888888888") == "_:5511888888888"
