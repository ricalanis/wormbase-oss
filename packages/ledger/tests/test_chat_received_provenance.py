"""Tests for ChatReceivedPayload provenance fields.

The three additive fields (delivery_mode, platform_ts, history_sync_id)
land per the schema-evolution doctrine's Rule 2 — defaults preserve
back-compat for pre-2026-05-05 entries replayed through current code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from wormbase_ledger.entries import ChatReceivedPayload


SENDER = UUID("0190a0a0-0000-7000-8000-0000000000a1")
TS = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)


class TestBackwardCompat:
    def test_payload_without_provenance_fields_uses_defaults(self) -> None:
        """Pre-provenance entries (no delivery_mode etc.) parse cleanly."""
        p = ChatReceivedPayload(
            channel_id="C1",
            message_id="m1",
            sender_person=SENDER,
            text="hello",
            classification="internal",
        )
        assert p.delivery_mode == "push"
        assert p.platform_ts is None
        assert p.history_sync_id is None

    def test_legacy_serialized_payload_round_trips(self) -> None:
        """Old wire-format dict (no provenance keys) survives validate."""
        legacy = {
            "channel_id": "C1",
            "message_id": "m1",
            "sender_person": str(SENDER),
            "text": "hello",
            "classification": "internal",
        }
        p = ChatReceivedPayload.model_validate(legacy)
        assert p.delivery_mode == "push"
        assert p.platform_ts is None
        assert p.history_sync_id is None


class TestProvenanceFields:
    def test_full_payload_with_provenance(self) -> None:
        p = ChatReceivedPayload(
            channel_id="C1",
            message_id="m1",
            sender_person=SENDER,
            text="hello",
            classification="internal",
            delivery_mode="history_sync",
            platform_ts=TS,
            history_sync_id="sync-abc",
        )
        assert p.delivery_mode == "history_sync"
        assert p.platform_ts == TS
        assert p.history_sync_id == "sync-abc"

    def test_round_trip_preserves_provenance(self) -> None:
        p = ChatReceivedPayload(
            channel_id="C1",
            message_id="m1",
            sender_person=SENDER,
            text="hello",
            classification="internal",
            delivery_mode="history_sync",
            platform_ts=TS,
            history_sync_id="sync-abc",
        )
        wire = p.model_dump(mode="json")
        roundtripped = ChatReceivedPayload.model_validate(wire)
        assert roundtripped == p

    def test_invalid_delivery_mode_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChatReceivedPayload(
                channel_id="C1",
                message_id="m1",
                sender_person=SENDER,
                text="hello",
                classification="internal",
                delivery_mode="bogus",  # type: ignore[arg-type]
            )

    def test_history_sync_mode_validates(self) -> None:
        p = ChatReceivedPayload(
            channel_id="C1",
            message_id="m1",
            sender_person=SENDER,
            text="hello",
            classification="internal",
            delivery_mode="history_sync",
        )
        assert p.delivery_mode == "history_sync"
