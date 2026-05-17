"""Block H — end-to-end integration: route → response → ledger entry.

Wires a real :class:`InMemoryLedger`, fake Kimi/Gemma backends, and a
real :class:`SqliteInferenceCache`. Drives one fresh call + one cached
call and asserts the substrate carries the full PEVR cycle for each.

Real Kimi/Gemma requires network + ``OLLAMA_API_KEY``; the
``test_clients_live`` module handles that env-skipped case. This
integration test does not call the real backends; the contract being
verified is the **router/ledger contract**, not the LLM behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from wormbase_inference.cache import SqliteInferenceCache
from wormbase_inference.protocol import RouteRequest
from wormbase_inference.router import CachedRouter
from wormbase_ledger import InMemoryLedger


@dataclass
class FakeBackend:
    name: str
    model: str
    reply: str = "answer"
    fail_with: Exception | None = None
    calls: list[Any] = field(default_factory=list)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        self.calls.append(messages)
        if self.fail_with is not None:
            exc = self.fail_with
            self.fail_with = None
            raise exc
        return self.reply

    async def aclose(self) -> None:
        return None


COMPANY_ID = UUID("0190a0a0-0000-7000-8000-0000000000ff")


@pytest.mark.asyncio
async def test_e2e_fresh_call_lands_inference_served_pevr_cycle(
    tmp_path: Path,
) -> None:
    ledger = InMemoryLedger()
    cache = SqliteInferenceCache(tmp_path / "i.sqlite")
    kimi = FakeBackend(name="kimi", model="kimi-k2.6:cloud", reply="K-answer")
    gemma = FakeBackend(name="gemma", model="gemma4:e4b")
    router = CachedRouter(
        kimi=kimi,
        gemma=gemma,
        cache=cache,
        ledger=ledger,
        company_id=COMPANY_ID,
    )

    resp = await router.call(
        RouteRequest(
            call_type="reasoning",
            messages=(("user", "what is the q3 revenue?"),),
            requested_by="integration-test",
        )
    )

    assert resp.served_by == "kimi"
    assert resp.text == "K-answer"

    # Ledger should now carry one full PEVR cycle (4 rows).
    rows = await ledger.fetch(COMPANY_ID)
    assert len(rows) == 4
    kinds = [r["kind"] for r in rows]
    assert kinds == ["propose", "execute", "verify", "resolve"]
    # propose payload references the inference_served target_kind.
    assert rows[0]["payload"]["target_kind"] == "inference_served"
    # execute payload carries the full inference_served args.
    exec_args = rows[1]["payload"]["args"]
    assert exec_args["served_by"] == "kimi"
    assert exec_args["is_fallback"] is False
    assert exec_args["cache_key"] == resp.cache_key
    # verify passed.
    assert rows[2]["payload"]["passed"] is True
    # resolve kept.
    assert rows[3]["payload"]["outcome"] == "keep"

    # Verify hash chain is intact.
    report = await ledger.verify(COMPANY_ID)
    assert report.ok

    cache.close()


@pytest.mark.asyncio
async def test_e2e_cached_call_lands_second_pevr_cycle_tagged_cache(
    tmp_path: Path,
) -> None:
    ledger = InMemoryLedger()
    cache = SqliteInferenceCache(tmp_path / "i.sqlite")
    kimi = FakeBackend(name="kimi", model="kimi-k2.6:cloud", reply="K-answer")
    gemma = FakeBackend(name="gemma", model="gemma4:e4b")
    router = CachedRouter(
        kimi=kimi, gemma=gemma, cache=cache, ledger=ledger, company_id=COMPANY_ID,
    )

    req = RouteRequest(
        call_type="reasoning",
        messages=(("user", "what is the q3 revenue?"),),
    )
    r1 = await router.call(req)
    r2 = await router.call(req)

    # Two PEVR cycles → 8 rows.
    rows = await ledger.fetch(COMPANY_ID)
    assert len(rows) == 8

    # First cycle: served_by=kimi.
    first_args = rows[1]["payload"]["args"]
    assert first_args["served_by"] == "kimi"
    # Second cycle: served_by=cache, same cache_key.
    second_args = rows[5]["payload"]["args"]
    assert second_args["served_by"] == "cache"
    assert second_args["cache_key"] == r1.cache_key == r2.cache_key
    assert second_args["is_fallback"] is False
    # Latency on the cached row is 0 (no backend call).
    assert second_args["latency_ms"] == 0

    # Hash chain still intact.
    report = await ledger.verify(COMPANY_ID)
    assert report.ok

    cache.close()


@pytest.mark.asyncio
async def test_e2e_fallback_lands_is_fallback_true(tmp_path: Path) -> None:
    ledger = InMemoryLedger()
    cache = SqliteInferenceCache(tmp_path / "i.sqlite")

    from wormbase_inference.clients import InferenceError

    kimi = FakeBackend(
        name="kimi",
        model="kimi-k2.6:cloud",
        fail_with=InferenceError("kimi down"),
    )
    gemma = FakeBackend(name="gemma", model="gemma4:e4b", reply="from-gemma")
    router = CachedRouter(
        kimi=kimi, gemma=gemma, cache=cache, ledger=ledger, company_id=COMPANY_ID,
    )

    resp = await router.call(
        RouteRequest(
            call_type="reasoning",
            messages=(("user", "ping"),),
        )
    )
    assert resp.served_by == "gemma"
    assert resp.is_fallback is True

    rows = await ledger.fetch(COMPANY_ID)
    assert [r["kind"] for r in rows] == ["propose", "execute", "verify", "resolve"]
    args = rows[1]["payload"]["args"]
    assert args["served_by"] == "gemma"
    assert args["is_fallback"] is True

    cache.close()
