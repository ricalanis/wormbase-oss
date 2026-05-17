"""Block E (router half) — :class:`CachedRouter` end-to-end behavior.

Uses fake :class:`InferenceClient` implementations (no httpx) so the
tests run without any network and without real Kimi/Gemma backends.
The integration test (Block H) wires a real Ledger and asserts an
``inference_served`` row lands.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

from wormbase_inference.cache import (
    NullInferenceCache,
    SqliteInferenceCache,
)
from wormbase_inference.clients import InferenceError
from wormbase_inference.protocol import RouteRequest
from wormbase_inference.router import CachedRouter


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeClient:
    """In-memory :class:`InferenceClient` with scriptable behaviour."""

    name: str
    model: str
    reply: str = "ok"
    fail_with: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        self.calls.append(
            {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        )
        if self.fail_with is not None:
            exc = self.fail_with
            self.fail_with = None  # only fail once unless re-set
            raise exc
        return self.reply

    async def aclose(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Routing — backend selection by call_type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reasoning_routes_to_kimi() -> None:
    kimi = FakeClient(name="kimi", model="kimi-k2.6:cloud", reply="K")
    gemma = FakeClient(name="gemma", model="gemma4:e4b", reply="G")
    router = CachedRouter(kimi=kimi, gemma=gemma)
    resp = await router.call(
        RouteRequest(call_type="reasoning", messages=(("user", "x"),))
    )
    assert resp.text == "K"
    assert resp.served_by == "kimi"
    assert kimi.calls and not gemma.calls


@pytest.mark.asyncio
async def test_classify_routes_to_gemma() -> None:
    kimi = FakeClient(name="kimi", model="k", reply="K")
    gemma = FakeClient(name="gemma", model="g", reply="G")
    router = CachedRouter(kimi=kimi, gemma=gemma)
    resp = await router.call(
        RouteRequest(call_type="classify", messages=(("user", "y"),))
    )
    assert resp.text == "G"
    assert resp.served_by == "gemma"


@pytest.mark.asyncio
async def test_explicit_backend_hint_overrides_default() -> None:
    kimi = FakeClient(name="kimi", model="k", reply="K")
    gemma = FakeClient(name="gemma", model="g", reply="G")
    router = CachedRouter(kimi=kimi, gemma=gemma)
    # reasoning normally → kimi; force gemma.
    resp = await router.call(
        RouteRequest(
            call_type="reasoning",
            messages=(("user", "z"),),
            backend_hint="gemma",
        )
    )
    assert resp.served_by == "gemma"
    assert resp.text == "G"


@pytest.mark.asyncio
async def test_generic_call_type_requires_backend_hint() -> None:
    kimi = FakeClient(name="kimi", model="k")
    gemma = FakeClient(name="gemma", model="g")
    router = CachedRouter(kimi=kimi, gemma=gemma)
    with pytest.raises(ValueError, match="no default backend"):
        await router.call(
            RouteRequest(call_type="generic", messages=(("user", "g"),))
        )


# ---------------------------------------------------------------------------
# Fallback — primary fails, secondary serves; is_fallback=True.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_kimi_to_gemma_on_inference_error() -> None:
    kimi = FakeClient(
        name="kimi", model="k", fail_with=InferenceError("kimi down")
    )
    gemma = FakeClient(name="gemma", model="g", reply="from gemma")
    router = CachedRouter(kimi=kimi, gemma=gemma)
    resp = await router.call(
        RouteRequest(call_type="reasoning", messages=(("user", "x"),))
    )
    assert resp.text == "from gemma"
    assert resp.served_by == "gemma"
    assert resp.is_fallback is True


@pytest.mark.asyncio
async def test_fallback_gemma_to_kimi_on_inference_error() -> None:
    kimi = FakeClient(name="kimi", model="k", reply="from kimi")
    gemma = FakeClient(
        name="gemma", model="g", fail_with=InferenceError("vlan down")
    )
    router = CachedRouter(kimi=kimi, gemma=gemma)
    resp = await router.call(
        RouteRequest(call_type="classify", messages=(("user", "x"),))
    )
    assert resp.text == "from kimi"
    assert resp.served_by == "kimi"
    assert resp.is_fallback is True


# ---------------------------------------------------------------------------
# Cache — second call with identical inputs returns served_by="cache".
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_returns_served_by_cache(tmp_path: Any) -> None:
    cache = SqliteInferenceCache(tmp_path / "c.sqlite")
    kimi = FakeClient(name="kimi", model="k", reply="answer-1")
    gemma = FakeClient(name="gemma", model="g")
    router = CachedRouter(kimi=kimi, gemma=gemma, cache=cache)
    request = RouteRequest(call_type="reasoning", messages=(("user", "q"),))

    r1 = await router.call(request)
    assert r1.served_by == "kimi"
    assert r1.text == "answer-1"
    assert len(kimi.calls) == 1

    r2 = await router.call(request)
    assert r2.served_by == "cache"
    assert r2.text == "answer-1"
    assert r2.cache_key == r1.cache_key
    # The backend was NOT called the second time.
    assert len(kimi.calls) == 1
    cache.close()


@pytest.mark.asyncio
async def test_cache_miss_when_inputs_differ(tmp_path: Any) -> None:
    cache = SqliteInferenceCache(tmp_path / "c.sqlite")
    kimi = FakeClient(name="kimi", model="k", reply="answer-1")
    gemma = FakeClient(name="gemma", model="g")
    router = CachedRouter(kimi=kimi, gemma=gemma, cache=cache)

    await router.call(RouteRequest(call_type="reasoning", messages=(("user", "a"),)))
    kimi.reply = "answer-2"
    r2 = await router.call(RouteRequest(call_type="reasoning", messages=(("user", "b"),)))
    assert r2.served_by == "kimi"
    assert r2.text == "answer-2"
    cache.close()


@pytest.mark.asyncio
async def test_null_cache_never_caches() -> None:
    kimi = FakeClient(name="kimi", model="k", reply="x")
    gemma = FakeClient(name="gemma", model="g")
    router = CachedRouter(kimi=kimi, gemma=gemma, cache=NullInferenceCache())
    req = RouteRequest(call_type="reasoning", messages=(("user", "x"),))
    await router.call(req)
    await router.call(req)
    assert len(kimi.calls) == 2  # no cache, every call hits the backend


# ---------------------------------------------------------------------------
# Ledger emission — when ledger is wired, every call writes one PEVR cycle.
# ---------------------------------------------------------------------------


@dataclass
class FakeLedger:
    writes: list[dict[str, Any]] = field(default_factory=list)

    async def write(self, **kwargs: Any) -> Any:
        self.writes.append(kwargs)
        return None


@pytest.mark.asyncio
async def test_ledger_write_on_fresh_call() -> None:
    ledger = FakeLedger()
    kimi = FakeClient(name="kimi", model="k", reply="ok")
    gemma = FakeClient(name="gemma", model="g")
    router = CachedRouter(
        kimi=kimi, gemma=gemma, ledger=ledger, company_id=uuid4()
    )
    await router.call(
        RouteRequest(
            call_type="reasoning",
            messages=(("user", "hi"),),
            requested_by="test",
        )
    )
    assert len(ledger.writes) == 1
    w = ledger.writes[0]
    assert w["propose"]["target_kind"] == "inference_served"
    exec_payload = w["execute_fn"]()
    assert exec_payload["tool"] == "inference_served"
    assert exec_payload["args"]["served_by"] == "kimi"
    assert exec_payload["args"]["is_fallback"] is False


@pytest.mark.asyncio
async def test_ledger_write_on_cache_hit_tags_served_by_cache(
    tmp_path: Any,
) -> None:
    ledger = FakeLedger()
    cache = SqliteInferenceCache(tmp_path / "c.sqlite")
    kimi = FakeClient(name="kimi", model="k", reply="ok")
    gemma = FakeClient(name="gemma", model="g")
    router = CachedRouter(
        kimi=kimi, gemma=gemma, cache=cache, ledger=ledger, company_id=uuid4()
    )
    req = RouteRequest(call_type="reasoning", messages=(("user", "hi"),))
    await router.call(req)
    await router.call(req)  # cache hit
    assert len(ledger.writes) == 2
    second = ledger.writes[1]["execute_fn"]()
    assert second["args"]["served_by"] == "cache"
    cache.close()


@pytest.mark.asyncio
async def test_ledger_requires_company_id() -> None:
    ledger = FakeLedger()
    kimi = FakeClient(name="kimi", model="k", reply="ok")
    gemma = FakeClient(name="gemma", model="g")
    router = CachedRouter(kimi=kimi, gemma=gemma, ledger=ledger)
    with pytest.raises(ValueError, match="company_id"):
        await router.call(
            RouteRequest(call_type="reasoning", messages=(("user", "hi"),))
        )


@pytest.mark.asyncio
async def test_no_ledger_means_no_writes() -> None:
    kimi = FakeClient(name="kimi", model="k", reply="ok")
    gemma = FakeClient(name="gemma", model="g")
    router = CachedRouter(kimi=kimi, gemma=gemma)
    # Doesn't raise even without company_id.
    await router.call(
        RouteRequest(call_type="reasoning", messages=(("user", "hi"),))
    )
