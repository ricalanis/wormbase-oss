"""DEMO.1.C — pre-populated Acme demo cache + ``cache_only`` mode.

Three contracts:

1. ``populate_acme_cache`` writes one entry per :data:`ACME_DEMO_PROMPTS`
   and re-running is idempotent.
2. ``CachedRouter(cache_only=True)`` returns cache hits and raises
   :class:`CacheMissError` on misses (never touches Kimi/Gemma).
3. ``WORMBASE_INFERENCE_CACHE_ONLY=1`` env activates ``cache_only`` for
   ``build_default_router``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wormbase_inference import (
    ACME_DEMO_PROMPTS,
    CacheMissError,
    CachedRouter,
    DemoPrompt,
    InferenceError,
    NullInferenceCache,
    RouteRequest,
    SqliteInferenceCache,
    build_default_router,
    populate_acme_cache,
    populate_acme_cache_at_path,
)


# ---------------------------------------------------------------------------
# Test fakes — the existing test_router.py uses similar fake clients
# but they're test-only; redefine here so we don't depend on the
# router's test-collection layout.
# ---------------------------------------------------------------------------


class _BoomClient:
    """An :class:`InferenceClient` that raises on every call.

    ``cache_only`` must NEVER reach the client; if these blow, the
    cache-only contract has regressed.
    """

    def __init__(self, name: str, model: str) -> None:
        self.name = name
        self.model = model

    async def chat(self, *_args, **_kwargs) -> str:
        raise AssertionError(
            f"cache_only mode should not reach {self.name}.chat()"
        )

    async def aclose(self) -> None:
        return None


class _AlwaysFailClient:
    """A client that fails with a regular :class:`InferenceError`.

    Used to assert that cache_only short-circuits *before* the failure
    path, not after.
    """

    def __init__(self, name: str, model: str) -> None:
        self.name = name
        self.model = model

    async def chat(self, *_args, **_kwargs) -> str:
        raise InferenceError("simulated network failure")

    async def aclose(self) -> None:
        return None


# ---------------------------------------------------------------------------
# populate_acme_cache contract
# ---------------------------------------------------------------------------


def test_populate_acme_cache_writes_every_prompt() -> None:
    """One cache entry per :data:`ACME_DEMO_PROMPTS`, response round-trips."""

    class _MemCache:
        def __init__(self) -> None:
            self._d: dict[str, str] = {}

        def get(self, key: str) -> str | None:
            return self._d.get(key)

        def put(self, key: str, value: str, *, model: str) -> None:
            self._d[key] = value

        def invalidate_all(self) -> int:
            n = len(self._d)
            self._d.clear()
            return n

    cache = _MemCache()
    report = populate_acme_cache(cache)
    assert report.written == len(ACME_DEMO_PROMPTS)
    assert report.skipped_existing == 0
    assert len(report.keys) == len(ACME_DEMO_PROMPTS)
    # Every key resolves to its prompt's response.
    for prompt in ACME_DEMO_PROMPTS:
        hit = cache.get(prompt.cache_key())
        assert hit == prompt.response, (
            f"prompt {prompt.name!r} did not round-trip"
        )


def test_populate_acme_cache_is_idempotent() -> None:
    """Re-running over the same cache yields the same final state."""

    class _MemCache:
        def __init__(self) -> None:
            self._d: dict[str, str] = {}

        def get(self, key: str) -> str | None:
            return self._d.get(key)

        def put(self, key: str, value: str, *, model: str) -> None:
            self._d[key] = value

        def invalidate_all(self) -> int:
            return 0

    cache = _MemCache()
    populate_acme_cache(cache)
    snapshot1 = dict(cache._d)
    populate_acme_cache(cache)
    snapshot2 = dict(cache._d)
    assert snapshot1 == snapshot2, (
        "populate_acme_cache must be idempotent — overwrite=True is "
        "deterministic by construction"
    )


def test_populate_acme_cache_overwrite_false_skips_existing() -> None:
    """``overwrite=False`` preserves existing entries (skipped_existing > 0)."""

    class _MemCache:
        def __init__(self) -> None:
            self._d: dict[str, str] = {}

        def get(self, key: str) -> str | None:
            return self._d.get(key)

        def put(self, key: str, value: str, *, model: str) -> None:
            self._d[key] = value

        def invalidate_all(self) -> int:
            return 0

    cache = _MemCache()
    # First pass writes every entry.
    populate_acme_cache(cache)
    # Second pass with overwrite=False should skip every existing entry.
    report = populate_acme_cache(cache, overwrite=False)
    assert report.written == 0
    assert report.skipped_existing == len(ACME_DEMO_PROMPTS)


def test_populate_acme_cache_at_path_creates_sqlite(tmp_path: Path) -> None:
    """The convenience wrapper writes a real sqlite file."""
    cache_path = tmp_path / "demo.sqlite"
    report = populate_acme_cache_at_path(cache_path)
    assert cache_path.is_file()
    assert report.written == len(ACME_DEMO_PROMPTS)
    # Re-open + verify.
    reopened = SqliteInferenceCache(cache_path)
    try:
        for prompt in ACME_DEMO_PROMPTS:
            assert reopened.get(prompt.cache_key()) == prompt.response
    finally:
        reopened.close()


def test_demo_prompts_have_unique_names() -> None:
    """Every prompt has a unique ``name`` so the demo can refer to them."""
    names = [p.name for p in ACME_DEMO_PROMPTS]
    assert len(set(names)) == len(names), (
        f"duplicate prompt names: {names}"
    )


def test_demo_prompts_cover_every_demo_surface() -> None:
    """Pin the LLM-call surface coverage so a missing prompt fails loud.

    The Acme demo issues calls for: decision detection, topic labeling,
    recurring-question summarization, position inference, autoresearch
    experiment proposals, lesson extraction. If a future edit drops
    one of these prefixes, the demo will issue an uncached call ->
    CacheMissError on stage. Better to fail in CI.
    """
    name_prefixes = {p.name.split(".", 1)[0] for p in ACME_DEMO_PROMPTS}
    expected = {
        "decision",       # decision detection
        "topic",          # topic labeling
        "recurring",      # recurring-question summarization
        "position",       # position inference
        "research",       # experiment proposals + lesson extraction
    }
    assert expected <= name_prefixes, (
        f"missing demo surfaces: {expected - name_prefixes}"
    )


# ---------------------------------------------------------------------------
# cache_only contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_only_returns_cache_hit_without_calling_backends() -> None:
    """A cache hit is served verbatim; backends are never invoked."""

    class _MemCache:
        def __init__(self) -> None:
            self._d: dict[str, str] = {}

        def get(self, key: str) -> str | None:
            return self._d.get(key)

        def put(self, key: str, value: str, *, model: str) -> None:
            self._d[key] = value

        def invalidate_all(self) -> int:
            return 0

    cache = _MemCache()
    populate_acme_cache(cache)

    # Pick the decision-detection prompt and route through the router
    # in cache_only mode. The boom-clients would raise if reached.
    prompt = next(
        p for p in ACME_DEMO_PROMPTS if p.name.startswith("decision.")
    )
    router = CachedRouter(
        kimi=_BoomClient("kimi", prompt.model()),
        gemma=_BoomClient("gemma", prompt.model()),
        cache=cache,
        cache_only=True,
    )
    request = RouteRequest(
        call_type="reasoning" if prompt.backend == "kimi" else "summarize",
        messages=(("user", prompt.user),),
        system=prompt.system,
        temperature=prompt.temperature,
    )
    response = await router.call(request)
    assert response.served_by == "cache"
    assert response.text == prompt.response


@pytest.mark.asyncio
async def test_cache_only_raises_cache_miss_on_unknown_prompt() -> None:
    """A miss raises :class:`CacheMissError` and does NOT touch Kimi/Gemma."""
    router = CachedRouter(
        kimi=_BoomClient("kimi", "kimi-k2.6:cloud"),
        gemma=_BoomClient("gemma", "gemma4:e4b"),
        cache=NullInferenceCache(),  # always misses
        cache_only=True,
    )
    with pytest.raises(CacheMissError):
        await router.call(
            RouteRequest(
                call_type="reasoning",
                messages=(("user", "completely-uncached prompt"),),
            )
        )


@pytest.mark.asyncio
async def test_cache_only_short_circuits_before_fallback() -> None:
    """``cache_only`` must NOT trigger the Kimi→Gemma fallback path.

    Without this property, a cache-miss would silently cascade into
    the fallback client (which still does network I/O), defeating the
    point of cache_only as an offline guarantee.
    """
    router = CachedRouter(
        kimi=_AlwaysFailClient("kimi", "kimi-k2.6:cloud"),
        gemma=_AlwaysFailClient("gemma", "gemma4:e4b"),
        cache=NullInferenceCache(),
        cache_only=True,
    )
    with pytest.raises(CacheMissError):
        await router.call(
            RouteRequest(
                call_type="reasoning",
                messages=(("user", "anything"),),
            )
        )


@pytest.mark.asyncio
async def test_cache_only_default_false_preserves_legacy_behavior() -> None:
    """When ``cache_only`` is unset, calls must still fall through to backends.

    Pin this so the new flag doesn't silently change the production
    default. With cache_only=False (the default), a NullInferenceCache
    miss should continue to reach the primary backend.
    """

    class _OkClient:
        def __init__(self) -> None:
            self.name = "kimi"
            self.model = "kimi-k2.6:cloud"
            self.calls = 0

        async def chat(self, *_args, **_kwargs) -> str:
            self.calls += 1
            return "live response"

        async def aclose(self) -> None:
            return None

    primary = _OkClient()
    router = CachedRouter(
        kimi=primary,
        gemma=_BoomClient("gemma", "gemma4:e4b"),
        cache=NullInferenceCache(),
    )
    response = await router.call(
        RouteRequest(
            call_type="reasoning",
            messages=(("user", "live!"),),
        )
    )
    assert response.text == "live response"
    assert response.served_by == "kimi"
    assert primary.calls == 1


# ---------------------------------------------------------------------------
# Env-var integration
# ---------------------------------------------------------------------------


def test_build_default_router_picks_up_env_cache_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """``WORMBASE_INFERENCE_CACHE_ONLY=1`` activates cache_only.

    Drift gate: the env-var name is part of the documented demo
    interface. If a refactor renames it, this test catches the drift
    before the demo fails on stage.
    """
    monkeypatch.setenv("WORMBASE_INFERENCE_CACHE_ONLY", "1")
    monkeypatch.setenv(
        "WORMBASE_INFERENCE_CACHE_PATH",
        str(tmp_path / "cache.sqlite"),
    )
    router = build_default_router()
    try:
        assert router.cache_only is True
    finally:
        # No async loop here — the kimi/gemma httpx clients are
        # constructed but no calls were made; closing them isn't
        # required for the test, but be polite.
        pass


def test_build_default_router_default_off_when_env_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Without the env var, ``cache_only`` defaults to False."""
    monkeypatch.delenv("WORMBASE_INFERENCE_CACHE_ONLY", raising=False)
    monkeypatch.setenv(
        "WORMBASE_INFERENCE_CACHE_PATH",
        str(tmp_path / "cache.sqlite"),
    )
    router = build_default_router()
    assert router.cache_only is False


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("", False),
        ("garbage", False),
    ],
)
def test_env_truthy_parsing(
    raw: str, expected: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The env-var truthy parser is robust to common operator inputs."""
    monkeypatch.setenv("WORMBASE_INFERENCE_CACHE_ONLY", raw)
    monkeypatch.setenv(
        "WORMBASE_INFERENCE_CACHE_PATH",
        str(tmp_path / "cache.sqlite"),
    )
    router = build_default_router()
    assert router.cache_only is expected, (
        f"WORMBASE_INFERENCE_CACHE_ONLY={raw!r} should parse to "
        f"cache_only={expected}; got {router.cache_only}"
    )


def test_demo_prompt_cache_key_is_deterministic() -> None:
    """Re-computing a prompt's key returns the same value every time."""
    prompt = ACME_DEMO_PROMPTS[0]
    k1 = prompt.cache_key()
    k2 = prompt.cache_key()
    k3 = DemoPrompt(
        name=prompt.name,
        backend=prompt.backend,
        system=prompt.system,
        user=prompt.user,
        response=prompt.response,
        temperature=prompt.temperature,
    ).cache_key()
    assert k1 == k2 == k3, (
        "DemoPrompt.cache_key must be a pure function of its inputs"
    )
