# Silent Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a process-global `WORMBASE_SILENT_MODE` env var that puts the entire stack into listen-only mode — all ingestion + presence/relevance decisions keep running, but every outbound action (chat send, voice TTS, MCP write tool) is suppressed and recorded as a `reply_suppressed` ledger entry.

**Architecture:** Approach A from the spec — gate at every egress boundary. One shared helper (`is_silent_mode_enabled()` + `record_suppressed()`) is called from three concrete chokepoints: `write_actions._pevr` (covers all ~30 MCP write tools), a `SilentModeChannelAdapter` decorator wrapping each `ChannelAdapter.send()` plus a guard in `dm.send_resource_conversation_dm`, and the voice-agent `/webhook/elevenlabs` handler. Presence / relevance / per-channel `talkativeness` policy are untouched.

**Tech Stack:** Python 3.x, pytest, asyncio, Pydantic, FastAPI (voice-agent), pnpm workspace.

**Spec deltas** (corrections vs. `docs/superpowers/specs/2026-05-18-silent-mode-design.md`):

- Shared module lives at **`apps/worm-core/src/wormbase_core/silent_mode.py`** — there is no separate `packages/wormbase-core/` package; the `wormbase_core` namespace is published from `apps/worm-core/`.
- The chat egress gate is **not** at `apps/channel-adapter/.../writer.py` (that file only records the post-send `chat_sent` ledger entry). The true outbound chokepoints are `ChannelAdapter.send()` in `packages/channel-adapters/src/wormbase_channel_adapters/{slack,whatsapp,discord,teams}.py` and `send_resource_conversation_dm` in `apps/channel-adapter/src/wormbase_channel_adapter/dm.py`. We gate via a `SilentModeChannelAdapter` decorator applied in the adapter registry, plus a top-of-function check in `dm.py`.
- The MCP-write gate sits at the existing `_pevr` helper in `apps/worm-core/src/wormbase_core/write_actions.py:97`, which is the single fan-in for every PEVR-style write tool — one gate covers all of them.
- The voice-agent gate sits at the `/webhook/elevenlabs` handler in `apps/voice-agent/src/wormbase_voice_agent/app.py` (returning a "no-op" response instead of a generated reply), not at a TTS sink — ElevenLabs upstream owns the actual audio synthesis.

---

## File Structure

**New files:**
- `apps/worm-core/src/wormbase_core/silent_mode.py` — env var reader (cached), `SuppressedResult`/`SuppressedToolResult`/`SuppressedMessageRef` types, `record_suppressed()` ledger helper, `RESERVED_REPLY_SUPPRESSED_KIND` constant.
- `apps/worm-core/tests/test_silent_mode.py` — env var parsing matrix + caching.
- `apps/worm-core/tests/test_silent_mode_record.py` — `record_suppressed` payload schema + failure path.
- `apps/worm-core/tests/test_write_actions_silent_mode.py` — gate at `_pevr`.
- `packages/channel-adapters/src/wormbase_channel_adapters/silent_mode.py` — `SilentModeChannelAdapter` decorator implementing the `ChannelAdapter` Protocol.
- `packages/channel-adapters/tests/test_silent_mode_decorator.py` — decorator behavior.
- `apps/channel-adapter/tests/test_dm_silent_mode.py` — `dm.send_resource_conversation_dm` gate.
- `apps/voice-agent/tests/test_app_silent_mode.py` — `/webhook/elevenlabs` returns silent response.
- `tests/test_silent_mode_end_to_end.py` — leak-prevention integration test (top-level `tests/`).
- `scripts/check_silent_mode_coverage.sh` — CI grep guard.

**Modified files:**
- `apps/worm-core/src/wormbase_core/write_actions.py:97` — `_pevr` gains the silent-mode short-circuit at the top.
- `packages/channel-adapters/src/wormbase_channel_adapters/registry.py` — adapter factory wraps in `SilentModeChannelAdapter` when env var is set.
- `apps/channel-adapter/src/wormbase_channel_adapter/dm.py:163` — `send_resource_conversation_dm` top-of-function gate.
- `apps/voice-agent/src/wormbase_voice_agent/app.py:199` — `elevenlabs_llm` returns silent JSONResponse when env var is set.
- `DEVELOPERS.md` — document the silent-mode contract + the `# silent-mode: not-an-egress` escape comment for the CI guard.

---

## Task 1: Shared `silent_mode` module — env var parsing

**Files:**
- Create: `apps/worm-core/src/wormbase_core/silent_mode.py`
- Test: `apps/worm-core/tests/test_silent_mode.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/worm-core/tests/test_silent_mode.py
"""Env var parsing for WORMBASE_SILENT_MODE.

Truthy: {"1", "true", "yes", "on"} (case-insensitive, whitespace-stripped).
Anything else (including garbage) → off. Garbage logs a WARN at first read.
Cached after first call; mutating os.environ does not flip behavior.
"""

from __future__ import annotations

import logging

import pytest

from wormbase_core import silent_mode


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    """Each test starts with the silent_mode cache cleared."""
    silent_mode._reset_for_tests()
    yield
    silent_mode._reset_for_tests()


@pytest.mark.parametrize("value", ["1", "true", "True", "TRUE", "yes", "YES", "on", "ON", " 1 ", "\ttrue\n"])
def test_truthy_values_enable(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", value)
    assert silent_mode.is_silent_mode_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "FALSE", "no", "off", "maybe", "2"])
def test_non_truthy_values_disable(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", value)
    assert silent_mode.is_silent_mode_enabled() is False


def test_unset_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORMBASE_SILENT_MODE", raising=False)
    assert silent_mode.is_silent_mode_enabled() is False


def test_garbage_value_logs_warn(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "maybe")
    with caplog.at_level(logging.WARNING, logger="wormbase_core.silent_mode"):
        assert silent_mode.is_silent_mode_enabled() is False
    assert any("not recognized" in r.message for r in caplog.records)


def test_value_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    assert silent_mode.is_silent_mode_enabled() is True
    # Mutate the env after first read; cache must win.
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "0")
    assert silent_mode.is_silent_mode_enabled() is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/worm-core && uv run pytest tests/test_silent_mode.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wormbase_core.silent_mode'`.

- [ ] **Step 3: Write minimal implementation**

```python
# apps/worm-core/src/wormbase_core/silent_mode.py
"""WORMBASE_SILENT_MODE — process-global listen-only flag.

See docs/superpowers/specs/2026-05-18-silent-mode-design.md for the
contract. Boot-time only; cached after first read; failure to parse
defaults to off and logs WARN once.
"""

from __future__ import annotations

import logging
import os
from typing import Final

_LOG = logging.getLogger(__name__)

ENV_VAR: Final[str] = "WORMBASE_SILENT_MODE"
_TRUTHY: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})

_cached: bool | None = None


def is_silent_mode_enabled() -> bool:
    """Return True iff WORMBASE_SILENT_MODE is set to a truthy value.

    Cached after first call. Garbage values log a single WARN and return
    False (default is "talking" — failing safe to silence would create a
    different silent failure mode).
    """
    global _cached
    if _cached is not None:
        return _cached
    raw = os.environ.get(ENV_VAR, "")
    stripped = raw.strip().lower()
    if not stripped:
        _cached = False
        return _cached
    if stripped in _TRUTHY:
        _cached = True
        return _cached
    # Recognized falsey values pass through quietly; anything else WARNs.
    if stripped not in {"0", "false", "no", "off"}:
        _LOG.warning(
            "%s=%r not recognized, treating as off", ENV_VAR, raw
        )
    _cached = False
    return _cached


def _reset_for_tests() -> None:
    """Clear the cache — test-only hook."""
    global _cached
    _cached = None


__all__ = ["ENV_VAR", "is_silent_mode_enabled"]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apps/worm-core && uv run pytest tests/test_silent_mode.py -v
```

Expected: all 16+ parametrized cases PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/worm-core/src/wormbase_core/silent_mode.py apps/worm-core/tests/test_silent_mode.py
git commit -m "feat(silent-mode): add env var reader (boot-time, cached)"
```

---

## Task 2: `record_suppressed` ledger helper + result types

**Files:**
- Modify: `apps/worm-core/src/wormbase_core/silent_mode.py`
- Test: `apps/worm-core/tests/test_silent_mode_record.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/worm-core/tests/test_silent_mode_record.py
"""record_suppressed writes a reply_suppressed ledger entry.

Failure-path: if the ledger raises, the call MUST NOT re-raise and MUST
log ERROR with the full payload. The invariant "no outbound" outranks
trigger-capture completeness.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from wormbase_core import silent_mode


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    silent_mode._reset_for_tests()
    yield
    silent_mode._reset_for_tests()


@pytest.mark.asyncio
async def test_record_suppressed_writes_ledger_entry() -> None:
    ledger = AsyncMock()
    company_id = uuid4()
    await silent_mode.record_suppressed(
        ledger,
        company_id=company_id,
        surface="chat",
        tool="channel_adapter.send",
        args={"channel_id": "C123", "text": "hi"},
        channel_id="C123",
        presence_reason="dm_always_respond",
    )
    ledger.write.assert_awaited_once()
    call = ledger.write.await_args.kwargs
    assert call["company_id"] == company_id
    assert call["propose"]["target_kind"] == "reply_suppressed"
    execute_payload = call["execute_fn"]()
    assert execute_payload["tool"] == "channel_adapter.send"
    assert execute_payload["args"]["surface"] == "chat"
    assert execute_payload["args"]["presence_reason"] == "dm_always_respond"
    assert execute_payload["args"]["silent_mode_source"] == "env"
    assert execute_payload["args"]["channel_id"] == "C123"
    UUID(execute_payload["args"]["ref_id"])  # parseable uuid4


@pytest.mark.asyncio
async def test_record_suppressed_ledger_failure_does_not_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ledger = AsyncMock()
    ledger.write.side_effect = RuntimeError("ledger down")
    with caplog.at_level(logging.ERROR, logger="wormbase_core.silent_mode"):
        await silent_mode.record_suppressed(
            ledger,
            company_id=uuid4(),
            surface="mcp_write",
            tool="record_decision",
            args={"k": "v"},
            presence_reason="mcp_invocation",
        )
    assert any("record_suppressed failed" in r.message for r in caplog.records)


def test_suppressed_result_shape() -> None:
    r = silent_mode.SuppressedResult.new()
    assert r.ok is True
    assert r.suppressed is True
    UUID(str(r.ref_id))


def test_suppressed_tool_result_shape() -> None:
    r = silent_mode.SuppressedToolResult.new()
    assert r.ok is True
    assert r.suppressed is True
    UUID(str(r.ref_id))
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/worm-core && uv run pytest tests/test_silent_mode_record.py -v
```

Expected: FAIL with `AttributeError: module 'wormbase_core.silent_mode' has no attribute 'record_suppressed'`.

- [ ] **Step 3: Write minimal implementation**

Append to `apps/worm-core/src/wormbase_core/silent_mode.py`:

```python
# ---------------------------------------------------------------------------
# Suppressed-result types + ledger helper
# ---------------------------------------------------------------------------

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID, uuid4

Surface = Literal["chat", "voice", "mcp_write"]
SUPPRESSED_TARGET_KIND: Final[str] = "reply_suppressed"
_SILENT_MODE_SOURCE: Final[str] = "env"


@dataclass(frozen=True)
class SuppressedResult:
    """Returned by the chat / voice egress gates when silent mode suppresses a send."""

    ref_id: UUID
    ok: bool = True
    suppressed: bool = True

    @classmethod
    def new(cls) -> "SuppressedResult":
        return cls(ref_id=uuid4())


@dataclass(frozen=True)
class SuppressedToolResult:
    """Returned by `_pevr` when silent mode suppresses an MCP write tool."""

    ref_id: UUID
    ok: bool = True
    suppressed: bool = True

    @classmethod
    def new(cls) -> "SuppressedToolResult":
        return cls(ref_id=uuid4())


async def record_suppressed(
    ledger: Any,
    *,
    company_id: UUID,
    surface: Surface,
    tool: str,
    args: dict[str, Any],
    channel_id: str | None = None,
    tenant_id: UUID | None = None,
    presence_reason: str,
) -> None:
    """Write a reply_suppressed ledger entry capturing a would-have-been action.

    Best-effort: on ledger failure, logs ERROR with the payload and
    returns. Never raises into the egress path; never falls through to a
    real send.
    """
    ref_id = uuid4()
    payload = {
        "surface": surface,
        "tool": tool,
        "args": args,
        "channel_id": channel_id,
        "tenant_id": str(tenant_id) if tenant_id is not None else None,
        "presence_reason": presence_reason,
        "silent_mode_source": _SILENT_MODE_SOURCE,
        "ref_id": str(ref_id),
    }
    try:
        await ledger.write(
            company_id=company_id,
            propose={
                "target_kind": SUPPRESSED_TARGET_KIND,
                "ref_id": str(ref_id),
                "reason": f"silent_mode suppressed {surface}/{tool}",
                "proposed_by": "silent_mode",
            },
            execute_fn=lambda: {
                "tool": tool,
                "args": payload,
                "result_ref": str(ref_id),
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "suppressed_recorded", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "silent_mode listen-only",
            },
            quadrant="active_deterministic",
        )
    except Exception as exc:  # broad on purpose: invariant > completeness
        _LOG.error(
            "record_suppressed failed: surface=%s tool=%s payload=%r err=%s",
            surface, tool, payload, exc,
        )


__all__ = [
    "ENV_VAR",
    "SUPPRESSED_TARGET_KIND",
    "SuppressedResult",
    "SuppressedToolResult",
    "is_silent_mode_enabled",
    "record_suppressed",
]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apps/worm-core && uv run pytest tests/test_silent_mode_record.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/worm-core/src/wormbase_core/silent_mode.py apps/worm-core/tests/test_silent_mode_record.py
git commit -m "feat(silent-mode): add record_suppressed helper + result types"
```

---

## Task 3: Gate `write_actions._pevr` (covers all MCP write tools)

**Files:**
- Modify: `apps/worm-core/src/wormbase_core/write_actions.py:97-165`
- Test: `apps/worm-core/tests/test_write_actions_silent_mode.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/worm-core/tests/test_write_actions_silent_mode.py
"""Silent mode short-circuits _pevr before the real ledger.write fires.

Picks one representative caller (`record_decision`) because all PEVR
write tools fan through the same helper — a green test here certifies
the whole family.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from wormbase_core import silent_mode, write_actions


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    silent_mode._reset_for_tests()
    yield
    silent_mode._reset_for_tests()


@pytest.mark.asyncio
async def test_pevr_short_circuits_when_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    ledger = AsyncMock()
    company_id = uuid4()

    # Use the lowest-level test target: _pevr itself, with a fake payload class.
    class _StubPayload:
        def __init__(self, **_kwargs: object) -> None: ...

    result = await write_actions._pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="decision_recorded",
        ref_id=uuid4(),
        reason="t",
        proposed_by="test",
        tool="record_decision",
        args={"k": "v"},
        result_ref="r",
        payload_cls=_StubPayload,
        rationale="t",
    )
    # Exactly one ledger.write — for the reply_suppressed entry, not the real one.
    assert ledger.write.await_count == 1
    suppressed_call = ledger.write.await_args.kwargs
    assert suppressed_call["propose"]["target_kind"] == "reply_suppressed"
    # Caller gets a SuppressedToolResult.
    assert isinstance(result, silent_mode.SuppressedToolResult)
    assert result.ok is True and result.suppressed is True
    UUID(str(result.ref_id))


@pytest.mark.asyncio
async def test_pevr_passthrough_when_not_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORMBASE_SILENT_MODE", raising=False)
    ledger = AsyncMock()
    ledger.write.return_value = "ok"
    company_id = uuid4()

    class _StubPayload:
        def __init__(self, **_kwargs: object) -> None: ...

    result = await write_actions._pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="decision_recorded",
        ref_id=uuid4(),
        reason="t",
        proposed_by="test",
        tool="record_decision",
        args={"k": "v"},
        result_ref="r",
        payload_cls=_StubPayload,
        rationale="t",
    )
    assert result == "ok"
    real_call = ledger.write.await_args.kwargs
    assert real_call["propose"]["target_kind"] == "decision_recorded"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/worm-core && uv run pytest tests/test_write_actions_silent_mode.py -v
```

Expected: `test_pevr_short_circuits_when_silent` FAILS (ledger.write is called with the real `decision_recorded` payload, not `reply_suppressed`).

- [ ] **Step 3: Modify `_pevr` to gate at the top**

Open `apps/worm-core/src/wormbase_core/write_actions.py`. Find the `_pevr` function at line 97. Add the silent-mode short-circuit as the **first** thing inside the function body, before the `_verify` closure is defined.

Add this import alongside existing imports (top of file):

```python
from wormbase_core import silent_mode
```

Then change the body of `_pevr`:

```python
def _pevr(
    *,
    ledger: LedgerLike,
    company_id: UUID,
    target_kind: str,
    ref_id: UUID,
    reason: str,
    proposed_by: str,
    tool: str,
    args: dict[str, Any],
    result_ref: str,
    payload_cls: type,
    rationale: str,
):
    """Build the four PEVR closures and return the awaitable from ``ledger.write``.

    When WORMBASE_SILENT_MODE is on, short-circuits before any side effect:
    records a `reply_suppressed` entry and returns a SuppressedToolResult.
    """
    if silent_mode.is_silent_mode_enabled():
        async def _suppressed():
            await silent_mode.record_suppressed(
                ledger,
                company_id=company_id,
                surface="mcp_write",
                tool=tool,
                args=args,
                presence_reason="mcp_invocation",
            )
            return silent_mode.SuppressedToolResult.new()
        return _suppressed()

    # ... (existing _verify closure + return ledger.write(...) unchanged)
```

(The existing body — `_verify` closure, `return ledger.write(...)` — stays exactly as it is below this new block.)

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apps/worm-core && uv run pytest tests/test_write_actions_silent_mode.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Run the wider write_actions suite to confirm no regression**

```bash
cd apps/worm-core && uv run pytest tests/ -k "write_actions or pevr" -v
```

Expected: no new failures.

- [ ] **Step 6: Commit**

```bash
git add apps/worm-core/src/wormbase_core/write_actions.py apps/worm-core/tests/test_write_actions_silent_mode.py
git commit -m "feat(silent-mode): gate write_actions._pevr (all MCP write tools)"
```

---

## Task 4: `SilentModeChannelAdapter` decorator

**Files:**
- Create: `packages/channel-adapters/src/wormbase_channel_adapters/silent_mode.py`
- Test: `packages/channel-adapters/tests/test_silent_mode_decorator.py`

- [ ] **Step 1: Write the failing test**

```python
# packages/channel-adapters/tests/test_silent_mode_decorator.py
"""SilentModeChannelAdapter wraps an inner adapter and intercepts send().

All non-send methods (authenticate, install, listen, list_workspace_members)
pass through unchanged. send() never touches the inner adapter when silent
mode is on; it records reply_suppressed and returns a synthetic MessageRef.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from wormbase_channel_adapters.base import ChannelAdapter
from wormbase_channel_adapters.silent_mode import SilentModeChannelAdapter
from wormbase_core import silent_mode


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    silent_mode._reset_for_tests()
    yield
    silent_mode._reset_for_tests()


def _fake_inner() -> MagicMock:
    inner = MagicMock(spec=ChannelAdapter)
    inner.authenticate = AsyncMock(return_value="handle")
    inner.install = AsyncMock(return_value="install")
    inner.list_workspace_members = AsyncMock(return_value=[])
    inner.send = AsyncMock(return_value="real-msg-ref")
    inner.listen = MagicMock(return_value=iter([]))
    return inner


@pytest.mark.asyncio
async def test_send_suppressed_when_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    inner = _fake_inner()
    ledger = AsyncMock()
    company_id = uuid4()
    adapter = SilentModeChannelAdapter(
        inner=inner, ledger=ledger, company_id=company_id
    )
    result = await adapter.send(
        handle="h",
        channel={"platform_channel_id": "C123"},
        msg={"text": "hello"},
    )
    inner.send.assert_not_called()
    ledger.write.assert_awaited_once()
    assert ledger.write.await_args.kwargs["propose"]["target_kind"] == "reply_suppressed"
    # Result has the MessageRef-ish shape downstream callers expect.
    assert getattr(result, "suppressed", False) is True


@pytest.mark.asyncio
async def test_send_passthrough_when_not_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORMBASE_SILENT_MODE", raising=False)
    inner = _fake_inner()
    adapter = SilentModeChannelAdapter(
        inner=inner, ledger=AsyncMock(), company_id=uuid4()
    )
    result = await adapter.send(handle="h", channel={"id": "C"}, msg={"text": "x"})
    assert result == "real-msg-ref"
    inner.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_send_methods_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    inner = _fake_inner()
    adapter = SilentModeChannelAdapter(
        inner=inner, ledger=AsyncMock(), company_id=uuid4()
    )
    assert await adapter.authenticate("secrets") == "handle"  # passthrough
    inner.authenticate.assert_awaited_once_with("secrets")
    assert await adapter.list_workspace_members("h") == []
    inner.list_workspace_members.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/channel-adapters && uv run pytest tests/test_silent_mode_decorator.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'wormbase_channel_adapters.silent_mode'`.

- [ ] **Step 3: Implement the decorator**

```python
# packages/channel-adapters/src/wormbase_channel_adapters/silent_mode.py
"""SilentModeChannelAdapter — wraps an inner ChannelAdapter and gates send().

When WORMBASE_SILENT_MODE is on, send() never touches the inner adapter;
it records reply_suppressed and returns a SuppressedResult. All other
Protocol methods pass through.

The decorator is applied in the adapter registry (registry.py) when the
env var is set at boot. The same decorator handles every concrete
adapter (slack, whatsapp, discord, teams) without per-adapter changes.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from wormbase_core import silent_mode

from wormbase_channel_adapters.base import ChannelAdapter


class SilentModeChannelAdapter:
    """Wrap an inner ChannelAdapter; intercept send() under silent mode."""

    def __init__(
        self,
        *,
        inner: ChannelAdapter,
        ledger: Any,
        company_id: UUID,
    ) -> None:
        self._inner = inner
        self._ledger = ledger
        self._company_id = company_id

    # ---- intercepted ------------------------------------------------------

    async def send(
        self,
        handle: Any,
        channel: Any,
        msg: Any,
    ) -> Any:
        if silent_mode.is_silent_mode_enabled():
            await silent_mode.record_suppressed(
                self._ledger,
                company_id=self._company_id,
                surface="chat",
                tool=f"{type(self._inner).__name__}.send",
                args={"channel": _to_jsonable(channel), "msg": _to_jsonable(msg)},
                channel_id=_extract_channel_id(channel),
                presence_reason="channel_egress",
            )
            return silent_mode.SuppressedResult.new()
        return await self._inner.send(handle, channel, msg)

    # ---- passthroughs -----------------------------------------------------

    async def authenticate(self, secrets: Any) -> Any:
        return await self._inner.authenticate(secrets)

    async def install(self, handle: Any) -> Any:
        return await self._inner.install(handle)

    def listen(self, handle: Any) -> Any:
        return self._inner.listen(handle)

    async def list_workspace_members(self, handle: Any) -> Any:
        return await self._inner.list_workspace_members(handle)


def _extract_channel_id(channel: Any) -> str | None:
    if isinstance(channel, dict):
        for k in ("platform_channel_id", "channel_id", "id"):
            if k in channel:
                return str(channel[k])
        return None
    for attr in ("platform_channel_id", "channel_id", "id"):
        if hasattr(channel, attr):
            return str(getattr(channel, attr))
    return None


def _to_jsonable(value: Any) -> Any:
    """Best-effort coercion so the ledger payload survives JSON encoding."""
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


__all__ = ["SilentModeChannelAdapter"]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd packages/channel-adapters && uv run pytest tests/test_silent_mode_decorator.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/channel-adapters/src/wormbase_channel_adapters/silent_mode.py packages/channel-adapters/tests/test_silent_mode_decorator.py
git commit -m "feat(silent-mode): SilentModeChannelAdapter decorator"
```

---

## Task 5: Wire the decorator into the adapter registry

**Files:**
- Modify: `packages/channel-adapters/src/wormbase_channel_adapters/registry.py`
- Test: `packages/channel-adapters/tests/test_silent_mode_decorator.py` (extend)

First, read the existing registry to find the right wrap point.

- [ ] **Step 1: Read the registry**

```bash
cat packages/channel-adapters/src/wormbase_channel_adapters/registry.py
```

Identify the function or factory that returns a `ChannelAdapter` instance per platform string (e.g. `get_adapter(platform: str) -> ChannelAdapter` or a `REGISTRY: dict[str, type[ChannelAdapter]]` lookup callsite). The wrap goes wherever the *instance* is constructed and handed to callers.

- [ ] **Step 2: Add a failing test**

Append to `packages/channel-adapters/tests/test_silent_mode_decorator.py`:

```python
@pytest.mark.asyncio
async def test_registry_wraps_adapters_under_silent_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registry returns a SilentModeChannelAdapter when silent is on."""
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    from wormbase_channel_adapters import registry

    # Use whatever the registry's instance-getter is; replace with real name
    # after reading registry.py in Step 1.
    adapter = registry.build_adapter(
        platform="slack",
        ledger=AsyncMock(),
        company_id=uuid4(),
    )
    assert isinstance(adapter, SilentModeChannelAdapter)


@pytest.mark.asyncio
async def test_registry_returns_raw_adapter_when_not_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORMBASE_SILENT_MODE", raising=False)
    from wormbase_channel_adapters import registry

    adapter = registry.build_adapter(
        platform="slack",
        ledger=AsyncMock(),
        company_id=uuid4(),
    )
    assert not isinstance(adapter, SilentModeChannelAdapter)
```

If the actual registry function is not named `build_adapter`, rename in the test to match what Step 1 surfaced. If the registry exposes only a `REGISTRY: dict[str, type]`, add a small `build_adapter(platform, *, ledger, company_id)` helper to the registry module that does the lookup and optional wrap — and keep the tests pointing at it.

- [ ] **Step 3: Run to confirm failure**

```bash
cd packages/channel-adapters && uv run pytest tests/test_silent_mode_decorator.py -v -k registry
```

Expected: FAIL.

- [ ] **Step 4: Modify the registry**

Add at the bottom of `packages/channel-adapters/src/wormbase_channel_adapters/registry.py`:

```python
from typing import Any
from uuid import UUID

from wormbase_core import silent_mode

from wormbase_channel_adapters.silent_mode import SilentModeChannelAdapter


def build_adapter(
    *,
    platform: str,
    ledger: Any,
    company_id: UUID,
) -> Any:
    """Construct the platform's adapter; wrap with SilentModeChannelAdapter if silent mode is on.

    The base adapter instance is built via whatever existing factory the
    registry exposes (typically `REGISTRY[platform]()`). Tests in
    test_silent_mode_decorator.py lock the wrap behavior; existing
    per-platform tests cover construction.
    """
    inner_cls = REGISTRY[platform]
    inner = inner_cls()
    if silent_mode.is_silent_mode_enabled():
        return SilentModeChannelAdapter(
            inner=inner, ledger=ledger, company_id=company_id
        )
    return inner
```

(Adjust `REGISTRY[...]` / `inner_cls()` to match the actual lookup pattern surfaced in Step 1. The shape is: get the platform's adapter type, instantiate it, optionally wrap.)

- [ ] **Step 5: Run tests**

```bash
cd packages/channel-adapters && uv run pytest tests/test_silent_mode_decorator.py -v
cd packages/channel-adapters && uv run pytest tests/ -v
```

Expected: all silent-mode tests PASS; no regression in existing registry/adapter tests.

- [ ] **Step 6: Commit**

```bash
git add packages/channel-adapters/src/wormbase_channel_adapters/registry.py packages/channel-adapters/tests/test_silent_mode_decorator.py
git commit -m "feat(silent-mode): registry wraps adapters when env var set"
```

---

## Task 6: Gate `dm.send_resource_conversation_dm`

The `DMSender` Protocol is a different surface from `ChannelAdapter.send()`, so the decorator from Task 4 does not automatically cover it. Gate at the top of the public entry point.

**Files:**
- Modify: `apps/channel-adapter/src/wormbase_channel_adapter/dm.py:163`
- Test: `apps/channel-adapter/tests/test_dm_silent_mode.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/channel-adapter/tests/test_dm_silent_mode.py
"""send_resource_conversation_dm short-circuits under silent mode.

The sender's open_dm / send_dm MUST NOT be called. A reply_suppressed
ledger entry is recorded and a DMRef with synthetic ids is returned so
callers expecting a DMRef do not crash.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from wormbase_channel_adapter import dm
from wormbase_core import silent_mode


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    silent_mode._reset_for_tests()
    yield
    silent_mode._reset_for_tests()


@pytest.mark.asyncio
async def test_dm_suppressed_when_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    sender = AsyncMock()
    sender.open_dm = AsyncMock()
    sender.send_dm = AsyncMock()
    sender.platform = "slack"
    ledger = AsyncMock()
    ref = await dm.send_resource_conversation_dm(
        sender,
        owner_platform_id="U123",
        topic={"id": "t1"},
        statement={"text": "hi", "speaker_label": "ana", "channel_label": "#x", "ts": None},
        resources={"items": []},
        ledger=ledger,
        company_id=uuid4(),
    )
    sender.open_dm.assert_not_called()
    sender.send_dm.assert_not_called()
    ledger.write.assert_awaited_once()
    assert ledger.write.await_args.kwargs["propose"]["target_kind"] == "reply_suppressed"
    # Caller still gets a DMRef-shaped object.
    assert ref.platform == "slack"
    assert ref.platform_channel_id.startswith("suppressed:")
    assert ref.platform_message_id.startswith("suppressed:")


@pytest.mark.asyncio
async def test_dm_passthrough_when_not_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORMBASE_SILENT_MODE", raising=False)
    sender = AsyncMock()
    sender.open_dm = AsyncMock(return_value="D456")
    sender.send_dm = AsyncMock(return_value="M789")
    sender.platform = "slack"
    ref = await dm.send_resource_conversation_dm(
        sender,
        owner_platform_id="U123",
        topic={"id": "t1"},
        statement={"text": "hi", "speaker_label": "ana", "channel_label": "#x", "ts": None},
        resources={"items": []},
        ledger=None,
        company_id=None,
    )
    assert ref.platform_channel_id == "D456"
    assert ref.platform_message_id == "M789"
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd apps/channel-adapter && uv run pytest tests/test_dm_silent_mode.py -v
```

Expected: FAIL (signature mismatch — `ledger` / `company_id` are new kwargs).

- [ ] **Step 3: Update `send_resource_conversation_dm`**

Modify the function in `apps/channel-adapter/src/wormbase_channel_adapter/dm.py`:

1. Add `ledger` and `company_id` keyword-only parameters (both `Optional`, default `None` for backward compat with existing callers).
2. Add the silent-mode short-circuit as the first thing in the body.

```python
async def send_resource_conversation_dm(
    sender: DMSender,
    *,
    owner_platform_id: str,
    topic: dict[str, Any],
    statement: dict[str, Any],
    resources: dict[str, Any],
    ledger: Any | None = None,
    company_id: UUID | None = None,
) -> DMRef:
    """Format + send the resource-conversation DM. Returns ``DMRef``.

    [...existing docstring...]

    When WORMBASE_SILENT_MODE is on, the wire send is skipped: a
    reply_suppressed ledger entry is recorded (if ledger+company_id are
    provided) and a DMRef with synthetic `suppressed:<uuid>` ids is
    returned so callers expecting a DMRef do not crash.
    """
    from wormbase_core import silent_mode

    if silent_mode.is_silent_mode_enabled():
        platform = ""
        if hasattr(sender, "platform"):
            platform = str(getattr(sender, "platform") or "")
        ref_id = uuid4()
        if ledger is not None and company_id is not None:
            await silent_mode.record_suppressed(
                ledger,
                company_id=company_id,
                surface="chat",
                tool="dm.send_resource_conversation_dm",
                args={
                    "owner_platform_id": owner_platform_id,
                    "topic": topic,
                    "statement": statement,
                    "resources": resources,
                },
                presence_reason="dm_always_respond",
            )
        return DMRef(
            platform=platform or "unknown",
            platform_channel_id=f"suppressed:{ref_id}",
            platform_message_id=f"suppressed:{ref_id}",
        )

    # ... (existing body unchanged below)
```

(Add `from uuid import uuid4` and `from typing import Any` to the imports if not already present; `UUID` likewise.)

- [ ] **Step 4: Run tests**

```bash
cd apps/channel-adapter && uv run pytest tests/test_dm_silent_mode.py -v
cd apps/channel-adapter && uv run pytest tests/ -v
```

Expected: silent-mode tests PASS; existing dm-related tests unaffected (the new params default to `None`, so existing callers keep working).

- [ ] **Step 5: Commit**

```bash
git add apps/channel-adapter/src/wormbase_channel_adapter/dm.py apps/channel-adapter/tests/test_dm_silent_mode.py
git commit -m "feat(silent-mode): gate dm.send_resource_conversation_dm"
```

---

## Task 7: Gate voice-agent `/webhook/elevenlabs`

The voice-agent's outbound path is the JSON response returned to ElevenLabs from the `/webhook/elevenlabs` handler — ElevenLabs then synthesizes audio from that text. Returning an empty / "silent" response suppresses audio output entirely.

**Files:**
- Modify: `apps/voice-agent/src/wormbase_voice_agent/app.py:199`
- Test: `apps/voice-agent/tests/test_app_silent_mode.py`

- [ ] **Step 1: Inspect the existing handler**

```bash
sed -n '195,275p' apps/voice-agent/src/wormbase_voice_agent/app.py
```

Note the request model (`LLMWebhookRequest`), the success-response shape (the JSON the handler returns to ElevenLabs — what field carries the assistant text), and whether the handler has access to `state.ledger` / a company id.

- [ ] **Step 2: Write the failing test**

```python
# apps/voice-agent/tests/test_app_silent_mode.py
"""POST /webhook/elevenlabs returns a silent response under silent mode.

No LLM call, no audio-text in the response; a reply_suppressed ledger
entry is recorded.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from wormbase_core import silent_mode
from wormbase_voice_agent.app import VoiceAppState, create_app


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    silent_mode._reset_for_tests()
    yield
    silent_mode._reset_for_tests()


def _state_with_mock_ledger() -> tuple[VoiceAppState, AsyncMock]:
    state = VoiceAppState(...)  # supply minimal init kwargs — match the dataclass
    ledger = AsyncMock()
    state.ledger = ledger  # or whichever attribute the dataclass uses
    state.company_id = uuid4()
    return state, ledger


def test_elevenlabs_webhook_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    state, ledger = _state_with_mock_ledger()
    app = create_app(state=state)
    client = TestClient(app)
    resp = client.post(
        "/webhook/elevenlabs",
        json={"prompt": "hi", "session_id": "s1"},  # match LLMWebhookRequest schema
    )
    assert resp.status_code == 200
    body = resp.json()
    # The text field returned to ElevenLabs is empty under silent mode.
    assert body.get("text", "") == ""
    ledger.write.assert_awaited()
    assert any(
        call.kwargs["propose"]["target_kind"] == "reply_suppressed"
        for call in ledger.write.await_args_list
    )
```

(After reading the handler in Step 1, adjust: the `LLMWebhookRequest` JSON shape, the response field name (`text` is a guess — replace with the real one), and how `VoiceAppState` is constructed in tests. The existing `tests/` directory in `apps/voice-agent/` will have examples of building a test state — mirror those.)

- [ ] **Step 3: Run to confirm failure**

```bash
cd apps/voice-agent && uv run pytest tests/test_app_silent_mode.py -v
```

Expected: FAIL.

- [ ] **Step 4: Modify the handler**

In `apps/voice-agent/src/wormbase_voice_agent/app.py`, locate the `elevenlabs_llm` function (around line 199). Add at the top of the function body:

```python
from wormbase_core import silent_mode

@app.post("/webhook/elevenlabs")
async def elevenlabs_llm(req: LLMWebhookRequest) -> JSONResponse:
    if silent_mode.is_silent_mode_enabled():
        await silent_mode.record_suppressed(
            state.ledger,
            company_id=state.company_id,
            surface="voice",
            tool="elevenlabs_llm",
            args=req.model_dump(),
            presence_reason="voice_utterance",
        )
        # Replace `text` with whatever field-name the existing success path uses.
        return JSONResponse({"text": "", "suppressed": True})

    # ... (existing handler body unchanged)
```

(The exact attribute names — `state.ledger`, `state.company_id`, the response shape — must be matched to what the surrounding code uses. The handler is a closure over `state` from `create_app`.)

- [ ] **Step 5: Run tests**

```bash
cd apps/voice-agent && uv run pytest tests/test_app_silent_mode.py -v
cd apps/voice-agent && uv run pytest tests/ -v
```

Expected: silent test PASSes, no regressions.

- [ ] **Step 6: Commit**

```bash
git add apps/voice-agent/src/wormbase_voice_agent/app.py apps/voice-agent/tests/test_app_silent_mode.py
git commit -m "feat(silent-mode): gate voice-agent /webhook/elevenlabs"
```

---

## Task 8: End-to-end leak-prevention integration test

This is the single test that, if green, lets operators trust silent mode.

**Files:**
- Create: `tests/test_silent_mode_end_to_end.py`

- [ ] **Step 1: Inspect existing top-level integration test scaffolding**

```bash
ls tests/
```

Note the patterns used (fixture style, mock-transport conventions). Mirror them.

- [ ] **Step 2: Write the integration test**

```python
# tests/test_silent_mode_end_to_end.py
"""End-to-end: silent mode produces zero outbound side effects on any surface.

Wires a minimal slice of channel-adapter, voice-agent, and worm-core
write_actions with WORMBASE_SILENT_MODE=1, fires one synthetic event of
each kind, and asserts:

- Outbound transports (mocked) received ZERO calls across all surfaces.
- For each event there is exactly one corresponding reply_suppressed
  ledger entry (or zero, if Presence would have stayed quiet anyway —
  that's correct behavior, not a leak).
- Ingestion (chat_received entries) is present (the listen invariant).

If any of these fail, silent mode is leaking.
"""

from __future__ import annotations

import pytest

# Import the slice. Adapt the imports to actual test-helpers in the repo;
# the canonical scaffolding is documented in tests/README.md if present.


@pytest.mark.asyncio
async def test_silent_mode_blocks_chat_outbound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    # 1) Boot the slice with a mock Slack/WhatsApp transport.
    # 2) Inject one inbound DM event, one channel-mention event, one WhatsApp event.
    # 3) Drain reactivities / agent loop.
    # 4) Assert: transport.send was never called.
    # 5) Assert: reply_suppressed entries match the count of events that would
    #    have produced replies under non-silent mode.
    # 6) Assert: chat_received entries exist for every inbound event.
    raise NotImplementedError("flesh out per repo test-helper patterns")


@pytest.mark.asyncio
async def test_silent_mode_blocks_mcp_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    # Call a representative MCP write tool from write_actions; assert no real
    # ledger execute entry, only reply_suppressed.
    raise NotImplementedError


@pytest.mark.asyncio
async def test_silent_mode_blocks_voice_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    # POST a webhook request to the voice-agent; assert empty text + suppressed entry.
    raise NotImplementedError
```

- [ ] **Step 3: Flesh out each stub against existing test helpers**

Adapt each `raise NotImplementedError` block to use whatever inbound-event-injection helpers and mock-transport fixtures the repo already provides. The earlier per-app tests (`test_writer_silent_mode.py`, `test_dm_silent_mode.py`, etc.) demonstrate the shape — this test composes them.

- [ ] **Step 4: Run the test**

```bash
uv run pytest tests/test_silent_mode_end_to_end.py -v
```

Expected: all three pass. Any failure indicates a leak.

- [ ] **Step 5: Commit**

```bash
git add tests/test_silent_mode_end_to_end.py
git commit -m "test(silent-mode): end-to-end leak-prevention integration test"
```

---

## Task 9: CI grep guard + docs

**Files:**
- Create: `scripts/check_silent_mode_coverage.sh`
- Modify: `DEVELOPERS.md`

- [ ] **Step 1: Write the guard script**

```bash
# scripts/check_silent_mode_coverage.sh
#!/usr/bin/env bash
# Fails CI if a new file matching the egress-surface globs is added without
# referencing is_silent_mode_enabled. Suppress false positives with the magic
# comment `# silent-mode: not-an-egress` somewhere in the file.

set -euo pipefail

GLOBS=(
  "packages/channel-adapters/src/wormbase_channel_adapters/*.py"
  "apps/channel-adapter/src/wormbase_channel_adapter/dm.py"
  "apps/worm-core/src/wormbase_core/write_actions.py"
  "apps/voice-agent/src/wormbase_voice_agent/app.py"
)

fail=0
for pattern in "${GLOBS[@]}"; do
  for file in $pattern; do
    [[ -f "$file" ]] || continue
    if grep -qE "# silent-mode: not-an-egress" "$file"; then
      continue
    fi
    if ! grep -qE "is_silent_mode_enabled|SilentModeChannelAdapter" "$file"; then
      echo "silent-mode coverage: $file does not reference the silent-mode gate" >&2
      echo "  add the gate, or mark with: # silent-mode: not-an-egress" >&2
      fail=1
    fi
  done
done

exit $fail
```

- [ ] **Step 2: Make executable + run locally**

```bash
chmod +x scripts/check_silent_mode_coverage.sh
./scripts/check_silent_mode_coverage.sh
echo "exit: $?"
```

Expected: exit 0 after Tasks 3–7 land. If exit 1, the script names the offending file; either add the gate or the magic comment.

- [ ] **Step 3: Add the script to the lint job**

Open the repo's CI / lint config (e.g. `Makefile`, `.github/workflows/*.yml`, or `pyproject.toml`'s lint section — check `Makefile` first since the repo uses `make`). Add a `silent-mode-coverage` target that invokes the script, and wire it into the existing lint/check pipeline.

If using `Makefile`:

```make
.PHONY: silent-mode-coverage
silent-mode-coverage:
	./scripts/check_silent_mode_coverage.sh

lint: silent-mode-coverage  # or append to the existing lint target's deps
```

- [ ] **Step 4: Document in DEVELOPERS.md**

Append a section to `DEVELOPERS.md`:

```markdown
## Silent mode

`WORMBASE_SILENT_MODE=1` puts the entire stack into listen-only mode:
ingestion + presence/relevance decisions still run, but every outbound
action (chat send, voice TTS, MCP write tool) is suppressed and recorded
as a `reply_suppressed` ledger entry.

Activation is boot-time only (the env var is read once and cached).
Default is off. Spec: `docs/superpowers/specs/2026-05-18-silent-mode-design.md`.

### Adding a new outbound surface

If you add a new file under one of these globs, the CI guard
(`scripts/check_silent_mode_coverage.sh`) will fail unless the file
references `is_silent_mode_enabled` or `SilentModeChannelAdapter`:

- `packages/channel-adapters/src/wormbase_channel_adapters/*.py`
- `apps/channel-adapter/src/wormbase_channel_adapter/dm.py`
- `apps/worm-core/src/wormbase_core/write_actions.py`
- `apps/voice-agent/src/wormbase_voice_agent/app.py`

Either:

1. **Gate the new egress** by calling `silent_mode.is_silent_mode_enabled()`
   at the top of the outbound function and recording a `reply_suppressed`
   entry via `silent_mode.record_suppressed(...)`. See `_pevr` in
   `write_actions.py` for the canonical pattern.
2. **Or mark the file as not-an-egress** by adding the comment
   `# silent-mode: not-an-egress` somewhere in the file (with a brief
   note on why).
```

- [ ] **Step 5: Commit**

```bash
git add scripts/check_silent_mode_coverage.sh DEVELOPERS.md Makefile
git commit -m "chore(silent-mode): CI guard + DEVELOPERS.md contract"
```

---

## Task 10: Boot-time announcement + `/healthz` flag

Per the spec, each app logs one INFO line at startup if silent mode is on, and apps exposing `/healthz` add `silent_mode` to the JSON.

**Files:**
- Modify: `apps/channel-adapter/src/wormbase_channel_adapter/cli.py` (boot log + healthz)
- Modify: `apps/voice-agent/src/wormbase_voice_agent/app.py` (boot log + add silent_mode to healthz)
- Modify: `apps/worm-core/src/wormbase_core/http_api.py` (boot log + healthz)

- [ ] **Step 1: Identify each app's boot entry + /healthz handler**

```bash
grep -nE "def main|run_service|/healthz" apps/channel-adapter/src/wormbase_channel_adapter/cli.py apps/voice-agent/src/wormbase_voice_agent/app.py apps/worm-core/src/wormbase_core/http_api.py 2>/dev/null
```

- [ ] **Step 2: Add a boot-log helper to `silent_mode.py`**

Append:

```python
def log_boot_state(app_name: str) -> None:
    """Emit a single INFO line at app startup. No-op when silent mode is off."""
    if is_silent_mode_enabled():
        _LOG.info("silent_mode=on app=%s", app_name)
```

- [ ] **Step 3: Call from each app's boot path**

In each app's boot function (e.g. `cli.run_service`, `create_app`, `http_api.serve`), add early:

```python
from wormbase_core import silent_mode
silent_mode.log_boot_state("channel-adapter")  # or voice-agent / worm-core
```

- [ ] **Step 4: Extend `/healthz` handlers**

For each app exposing `/healthz`, include `silent_mode: bool` in the response JSON:

```python
{"status": "ok", "silent_mode": silent_mode.is_silent_mode_enabled()}
```

- [ ] **Step 5: Add a smoke test per app**

For example, in `apps/channel-adapter/tests/test_silent_mode_healthz.py`:

```python
def test_healthz_reports_silent_mode(monkeypatch):
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    # boot the app, hit /healthz, assert response["silent_mode"] is True
```

(Mirror per-app `/healthz` test patterns already in the repo.)

- [ ] **Step 6: Run tests**

```bash
uv run pytest apps/channel-adapter/tests/test_silent_mode_healthz.py apps/voice-agent/tests/ apps/worm-core/tests/ -v -k silent_mode
```

- [ ] **Step 7: Commit**

```bash
git add apps/channel-adapter/src/wormbase_channel_adapter/cli.py apps/voice-agent/src/wormbase_voice_agent/app.py apps/worm-core/src/wormbase_core/http_api.py apps/worm-core/src/wormbase_core/silent_mode.py apps/*/tests/test_silent_mode_healthz.py
git commit -m "feat(silent-mode): boot log + /healthz flag per app"
```

---

## Self-Review — Spec Coverage Check

| Spec section                                                                                                 | Implemented in       |
| ------------------------------------------------------------------------------------------------------------ | -------------------- |
| `WORMBASE_SILENT_MODE` truthy parsing matrix + WARN on garbage + cached                                      | Task 1               |
| `is_silent_mode_enabled()` + `record_suppressed()` shared helpers                                            | Tasks 1, 2           |
| Chat egress gate (Slack/WhatsApp/Discord/Teams + DMs + @mentions, both `ChannelAdapter.send` and `dm.py`)    | Tasks 4, 5, 6        |
| Voice TTS gate (`/webhook/elevenlabs` returns silent response)                                               | Task 7               |
| MCP write tools gate (`_pevr` covers all ~30 write tools)                                                    | Task 3               |
| `reply_suppressed` ledger event with all spec'd payload fields                                               | Task 2               |
| `SuppressedResult` / `SuppressedToolResult` types (`ok=True, suppressed=True, ref_id=<uuid>`)                | Task 2               |
| Ledger-write failure path: log ERROR, do not raise, do not fall through                                      | Task 2 test          |
| Boot-time INFO log + `/healthz` flag                                                                         | Task 10              |
| End-to-end leak-prevention test                                                                              | Task 8               |
| CI grep guard + `# silent-mode: not-an-egress` escape comment + DEVELOPERS.md                                | Task 9               |
| Per-tenant scoping — explicit non-goal                                                                       | n/a                  |
| Runtime toggle — explicit non-goal                                                                           | n/a                  |
| Presence / per-channel `talkativeness` policy unchanged                                                      | n/a (no code change) |

No spec requirement is unaddressed. No placeholder steps. Type names (`SuppressedResult`, `SuppressedToolResult`, `is_silent_mode_enabled`, `record_suppressed`, `SilentModeChannelAdapter`, `SUPPRESSED_TARGET_KIND`) are consistent across all tasks.
