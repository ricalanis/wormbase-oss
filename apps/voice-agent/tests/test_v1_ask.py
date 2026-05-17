"""Tests for the dashboard-facing ``POST /v1/ask`` endpoint (W3.A12).

The dashboard's "Ask the worm" floater proxies to this surface so
questions asked from any (app) route flow through the same pipeline as
phone-call utterances. Acceptance:

- 200 with ``{answer, hash_receipt, ledger_seq, model, session_id}`` on
  the happy path.
- ``hash_receipt`` is deterministic — same transcript + same answer +
  same model produces the same digest across calls.
- 400 when ``transcript`` is empty / missing (no Kimi call, no ledger
  write).
- 503 when the inference router (Kimi) raises — the route surfaces an
  honest "service unavailable" rather than a stub answer.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from wormbase_voice_agent.app import (
    VoiceAppState,
    compute_hash_receipt,
    create_app,
)
from wormbase_voice_agent.audio_store import AudioStore

from .conftest import FakeKimi


def _make_app(
    *,
    ledger: Any,
    kimi: FakeKimi,
    company_id: Any,
    audio_store: AudioStore | None = None,
) -> TestClient:
    state = VoiceAppState(
        ledger=ledger,
        kimi=kimi,  # type: ignore[arg-type]
        audio_store=audio_store or AudioStore("/tmp/voice-audio-test"),
        tenant_slug="baseworm",
        company_id=company_id,
    )
    app = create_app(state=state)
    return TestClient(app)


class TestAskEndpoint:
    def test_returns_answer_hash_and_ledger_seq(
        self, in_memory_ledger, baseworm_company_id, fake_kimi,
    ) -> None:
        client = _make_app(
            ledger=in_memory_ledger,
            kimi=fake_kimi,
            company_id=baseworm_company_id,
        )
        r = client.post(
            "/v1/ask",
            json={
                "transcript": "What was Q3 net revenue?",
                "person_id": "00000000-0000-0000-0000-000000000abc",
                "tenant_id": "baseworm",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["answer"] == fake_kimi._reply
        # 64-char hex sha256 digest.
        assert isinstance(body["hash_receipt"], str)
        assert len(body["hash_receipt"]) == 64
        int(body["hash_receipt"], 16)  # valid hex
        # ledger_seq is the seq of the chat_sent execute row. We've now
        # written two PEVR cycles (chat_received + chat_sent) so the
        # chat_sent execute is at seq 6 (1: rcv-propose, 2: rcv-execute,
        # 3: rcv-verify, 4: rcv-resolve, 5: snd-propose, 6: snd-execute).
        assert body["ledger_seq"] == 6
        assert body["model"]
        assert body["session_id"].startswith("dashboard-baseworm-")

    def test_hash_receipt_is_deterministic(
        self, in_memory_ledger, baseworm_company_id,
    ) -> None:
        # Two requests with the same transcript and the same Kimi reply
        # MUST produce the same hash_receipt — that's the C2
        # determinism contract.
        kimi = FakeKimi(reply="four point two million dollars.")
        client = _make_app(
            ledger=in_memory_ledger,
            kimi=kimi,
            company_id=baseworm_company_id,
        )
        body = {"transcript": "What was Q3 net revenue?"}
        r1 = client.post("/v1/ask", json=body)
        r2 = client.post("/v1/ask", json=body)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["hash_receipt"] == r2.json()["hash_receipt"]
        # And matches the standalone helper.
        assert r1.json()["hash_receipt"] == compute_hash_receipt(
            transcript="What was Q3 net revenue?",
            answer="four point two million dollars.",
            model=r1.json()["model"],
        )

    def test_empty_transcript_returns_400(
        self, in_memory_ledger, baseworm_company_id, fake_kimi,
    ) -> None:
        client = _make_app(
            ledger=in_memory_ledger,
            kimi=fake_kimi,
            company_id=baseworm_company_id,
        )
        r = client.post("/v1/ask", json={"transcript": "   "})
        assert r.status_code == 400
        # No Kimi call, no ledger write.
        assert fake_kimi.calls == []

    def test_kimi_failure_returns_503(
        self, in_memory_ledger, baseworm_company_id,
    ) -> None:
        class BrokenKimi:
            calls: list[Any] = []

            async def chat(self, messages, **_: Any) -> str:
                BrokenKimi.calls.append(list(messages))
                raise RuntimeError("ollama unreachable")

        client = _make_app(
            ledger=in_memory_ledger,
            kimi=BrokenKimi(),  # type: ignore[arg-type]
            company_id=baseworm_company_id,
        )
        r = client.post(
            "/v1/ask",
            json={"transcript": "What was Q3 net revenue?"},
        )
        assert r.status_code == 503
        assert "inference router unavailable" in r.text.lower()
