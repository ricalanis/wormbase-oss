"""Tests for ConversationSyncPayload — the lineage entry for bulk
historical-message imports.

Per-message ChatReceivedPayload entries from a sync reference this entry
via history_sync_id. The PEVR cycle is observation-only (verify always
passes; resolve always keeps); content lives in the execute payload.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from wormbase_ledger.entries import KIND_REGISTRY, ConversationSyncPayload


TS_START = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
TS_END = datetime(2026, 5, 5, 12, 0, 30, tzinfo=UTC)
TS_EARLIEST = datetime(2026, 5, 5, 9, 0, tzinfo=UTC)
TS_LATEST = datetime(2026, 5, 5, 11, 59, tzinfo=UTC)


class TestRegistry:
    def test_conversation_sync_in_kind_registry(self) -> None:
        assert "conversation_sync" in KIND_REGISTRY

    def test_kind_registry_size_is_at_least_75(self) -> None:
        # Plan (§4.5) targets the registry crossing 74 → 75 with
        # conversation_sync's addition. Empirical baseline at the time
        # this test was written was already higher (the doctrine's
        # Addendum 1 calibration noted the registry was undercounted),
        # so the assertion is "at least 75" — the new kind landed.
        assert len(KIND_REGISTRY) >= 75

    def test_kind_registry_class_is_conversation_sync_payload(self) -> None:
        assert KIND_REGISTRY["conversation_sync"] is ConversationSyncPayload

    def test_kind_attribute_matches_registry_key(self) -> None:
        assert ConversationSyncPayload.kind == "conversation_sync"


class TestPayloadConstruction:
    def test_minimum_required_fields(self) -> None:
        sync_id = uuid4()
        p = ConversationSyncPayload(
            sync_id=sync_id,
            platform="whatsapp",
            trigger="initial_connect",
            started_at=TS_START,
        )
        assert p.sync_id == sync_id
        assert p.platform == "whatsapp"
        assert p.trigger == "initial_connect"
        assert p.started_at == TS_START

    def test_channels_default_empty_list(self) -> None:
        p = ConversationSyncPayload(
            sync_id=uuid4(),
            platform="whatsapp",
            trigger="initial_connect",
            started_at=TS_START,
        )
        assert p.channels == []

    def test_status_defaults_to_in_progress(self) -> None:
        p = ConversationSyncPayload(
            sync_id=uuid4(),
            platform="whatsapp",
            trigger="initial_connect",
            started_at=TS_START,
        )
        assert p.status == "in_progress"

    def test_message_count_defaults_zero(self) -> None:
        p = ConversationSyncPayload(
            sync_id=uuid4(),
            platform="whatsapp",
            trigger="initial_connect",
            started_at=TS_START,
        )
        assert p.message_count == 0

    def test_full_completed_sync_payload(self) -> None:
        sync_id = uuid4()
        p = ConversationSyncPayload(
            sync_id=sync_id,
            platform="whatsapp",
            install_id="install-xyz",
            channels=["120363012345678901@g.us", "5511999999999@s.whatsapp.net"],
            trigger="reconnect",
            started_at=TS_START,
            completed_at=TS_END,
            message_count=42,
            earliest_ts=TS_EARLIEST,
            latest_ts=TS_LATEST,
            status="completed",
        )
        assert p.message_count == 42
        assert len(p.channels) == 2
        assert p.status == "completed"

    def test_round_trip(self) -> None:
        sync_id = uuid4()
        p = ConversationSyncPayload(
            sync_id=sync_id,
            platform="whatsapp",
            install_id="install-xyz",
            channels=["a@s.whatsapp.net"],
            trigger="reconnect",
            started_at=TS_START,
            completed_at=TS_END,
            message_count=5,
            earliest_ts=TS_EARLIEST,
            latest_ts=TS_LATEST,
            status="completed",
        )
        wire = p.model_dump(mode="json")
        roundtripped = ConversationSyncPayload.model_validate(wire)
        assert roundtripped == p


class TestStatusTransitions:
    @pytest.mark.parametrize(
        "status", ["in_progress", "completed", "interrupted"],
    )
    def test_valid_status_values(self, status: str) -> None:
        p = ConversationSyncPayload(
            sync_id=uuid4(),
            platform="whatsapp",
            trigger="initial_connect",
            started_at=TS_START,
            status=status,  # type: ignore[arg-type]
        )
        assert p.status == status

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConversationSyncPayload(
                sync_id=uuid4(),
                platform="whatsapp",
                trigger="initial_connect",
                started_at=TS_START,
                status="bogus",  # type: ignore[arg-type]
            )

    def test_invalid_trigger_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConversationSyncPayload(
                sync_id=uuid4(),
                platform="whatsapp",
                trigger="bogus",  # type: ignore[arg-type]
                started_at=TS_START,
            )


class TestTzAwareValidators:
    def test_naive_started_at_rejected(self) -> None:
        naive = datetime(2026, 5, 5, 12, 0)
        with pytest.raises(ValidationError):
            ConversationSyncPayload(
                sync_id=uuid4(),
                platform="whatsapp",
                trigger="initial_connect",
                started_at=naive,
            )

    def test_naive_completed_at_rejected(self) -> None:
        naive = datetime(2026, 5, 5, 12, 0)
        with pytest.raises(ValidationError):
            ConversationSyncPayload(
                sync_id=uuid4(),
                platform="whatsapp",
                trigger="initial_connect",
                started_at=TS_START,
                completed_at=naive,
            )

    def test_none_completed_at_allowed(self) -> None:
        p = ConversationSyncPayload(
            sync_id=uuid4(),
            platform="whatsapp",
            trigger="initial_connect",
            started_at=TS_START,
            completed_at=None,
        )
        assert p.completed_at is None
