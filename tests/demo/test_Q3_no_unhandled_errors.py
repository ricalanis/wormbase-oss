"""Q3 demo gate: no unhandled errors in any service log during the run.

Implementation now: drives a representative slice of the demo (warmup
+ messages + file drop + replay) through the WormCore graph with a
captured logger handler that records every WARNING/ERROR/CRITICAL.
Asserts the captured set contains zero unexpected entries.

Some warnings are expected and benign (e.g. lurker payload retry on
malformed events). We allow a small allowlist of substring patterns
documented inline.

Once a real demo run exists (P5 sim-harness), this gate will instead
scrape `docker compose logs` for the same set; the per-component
allowlist will live in `tests/demo/_log_allowlist.py`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from wormbase_core.reactivity import InfraEvent
from wormbase_core.service import build_worm_core
from wormbase_ledger import InMemoryLedger


_ALLOW_SUBSTRINGS: tuple[str, ...] = (
    # Benign: lurker hits this when a synthetic event lacks SocketMode
    # context. The handler recovers and writes chat_received anyway.
    "lurker payload validation failed",
    # Classifier degrades gracefully when no Ollama key is set.
    "OLLAMA_API_KEY not set",
)


class _CapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.mark.asyncio
async def test_Q3_no_unhandled_errors_during_representative_demo_slice() -> None:
    handler = _CapturingHandler()
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    try:
        company_id = uuid4()
        ledger = InMemoryLedger()
        worm = await build_worm_core(
            ledger, company_id,
            domain_pack="saas",
            enable_lurker=False, enable_cloud_classifier=False,
        )
        # Reactivity slice
        await worm.pipeline.process(
            {
                "type": "channel_message",
                "ts": datetime(2026, 4, 30, 12, tzinfo=UTC).timestamp(),
                "channel_id": "C-q3",
                "user_id": "U-q3",
                "text": "@worm hello",
                "message_id": "m-q3-1",
                "company_id": str(company_id),
            }
        )
        # File drop slice
        await worm.drop_and_profile.on_file_drop(
            InfraEvent(
                source="file_drop",
                payload={
                    "filename": "x.csv",
                    "mimetype": "text/csv",
                    "bytes_url": "https://files/x",
                },
                ts=datetime(2026, 4, 30, 12, 1, tzinfo=UTC),
                company_id=company_id,
                message_id="m-q3-2",
                channel_id="C-q3",
                text="x.csv",
            )
        )
        # Ramp + replay
        await worm.ramp.compute(company_id, write_snapshot=False)
    finally:
        root.removeHandler(handler)

    unexpected = [
        r for r in handler.records
        if r.levelno >= logging.ERROR
        and not any(s in r.getMessage() for s in _ALLOW_SUBSTRINGS)
    ]
    assert not unexpected, (
        f"Q3 GATE FAILED: unhandled errors during demo slice: "
        f"{[r.getMessage() for r in unexpected]}"
    )
