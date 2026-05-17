"""DropAndProfileFlow tests — lifted from apps/worm-core/tests/test_flows.py
in Wave B (D1). Imports updated; assertions unchanged."""

from __future__ import annotations

from uuid import uuid4

from wormbase_chat_presence.chat_flows import DropAndProfileFlow
from wormbase_chat_presence.chat_flows._shared import FileProfile
from wormbase_chat_presence.classifier import StubClassifier
from wormbase_core.reactivity import InfraEvent
from wormbase_core.source_builder import SourceBuilder


# -- 1) drop_and_profile ---------------------------------------------


async def test_drop_and_profile_proposes_on_csv_upload(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    classifier = StubClassifier(domain="saas")
    flow = DropAndProfileFlow(builder, classifier)
    event = InfraEvent(
        source="file_drop",
        payload={
            "filename": "subscriptions.csv",
            "mimetype": "text/csv",
            "bytes_url": "https://files/abc",
        },
        ts=clock.now(),
        company_id=company_id,
        message_id="msg-1",
        channel_id="C1",
        text="subscriptions.csv",
    )
    cid = await flow.on_file_drop(event)
    assert cid is not None
    rows = await ledger.fetch(company_id)
    assert any(
        r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_proposed"
        for r in rows
    )


async def test_drop_and_profile_classifies_pii_filename(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    classifier = StubClassifier(domain="saas")
    flow = DropAndProfileFlow(builder, classifier)
    event = InfraEvent(
        source="file_drop",
        payload={
            "filename": "customers_ssn.csv",
            "mimetype": "text/csv",
            "bytes_url": "https://files/x",
        },
        ts=clock.now(),
        company_id=company_id,
        message_id="m",
        channel_id="C1",
        text="customers_ssn.csv",
    )
    await flow.on_file_drop(event)
    rows = await ledger.fetch(company_id)
    proposal = [r for r in rows if r["kind"] == "execute"
                and r["payload"]["tool"] == "emit_source_proposed"][0]
    assert proposal["payload"]["args"]["suggested_classification"] == "pii"


async def test_drop_and_profile_rejects_unsupported_mimetype(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    classifier = StubClassifier(domain="saas")
    flow = DropAndProfileFlow(builder, classifier)
    event = InfraEvent(
        source="file_drop",
        payload={"filename": "foo.exe", "mimetype": "application/x-msdownload"},
        ts=clock.now(),
        company_id=company_id, message_id="m", channel_id="C1", text="foo.exe",
    )
    cid = await flow.on_file_drop(event)
    assert cid is None


async def test_drop_and_profile_full_sequence_after_confirmation(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    classifier = StubClassifier(domain="saas")

    async def profiler(uri):
        return FileProfile(
            row_count=100, column_count=5,
            columns=[{"name": "id", "dtype": "int"}],
            schema_hash="hash-abc",
        )

    flow = DropAndProfileFlow(builder, classifier, file_profiler=profiler)
    event = InfraEvent(
        source="file_drop",
        payload={"filename": "data.csv", "mimetype": "text/csv",
                 "bytes_url": "url"},
        ts=clock.now(), company_id=company_id, message_id="m",
        channel_id="C1", text="data.csv",
    )
    cid = await flow.on_file_drop(event)
    await flow.on_confirmation(str(cid), uuid4(), uuid4())
    rows = await ledger.fetch(company_id)
    tools = [r["payload"]["tool"] for r in rows if r["kind"] == "execute"]
    for t in ("emit_source_proposed", "emit_source_confirmed",
              "emit_source_connected", "emit_source_profiled"):
        assert t in tools
