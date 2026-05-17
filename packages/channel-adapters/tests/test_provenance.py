"""Tests for InfraEvent provenance fields and the is_live derivation.

The provenance triple (delivery_mode, platform_ts, history_sync_id) is
the substrate's way of distinguishing live wire events from history-replay
imports (WhatsApp/Baileys reconnect, Slack stale-fetch). The is_live
predicate composes both into the speak-path gate.

Permissiveness is intentional: pre-provenance entries (no platform_ts)
default to is_live=True so the gate doesn't retroactively suppress
legitimate live messages written before the fields existed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from wormbase_channel_adapters.types import InfraEvent


def _make_event(
    *,
    delivery_mode: str = "push",
    platform_ts: datetime | None = None,
    ts: datetime | None = None,
    history_sync_id: str | None = None,
) -> InfraEvent:
    """Build a synthetic InfraEvent with the given provenance shape."""
    ts = ts or datetime.now(timezone.utc)
    return InfraEvent(
        source="channel_message",
        platform="slack",
        platform_channel_id="C1",
        platform_user_id="U1",
        platform_message_id="m1",
        text="hello",
        payload={},
        ts=ts,
        delivery_mode=delivery_mode,  # type: ignore[arg-type]
        platform_ts=platform_ts,
        history_sync_id=history_sync_id,
    )


class TestInfraEventDefaults:
    def test_delivery_mode_defaults_to_push(self) -> None:
        e = _make_event()
        assert e.delivery_mode == "push"

    def test_platform_ts_defaults_to_none(self) -> None:
        e = _make_event()
        assert e.platform_ts is None

    def test_history_sync_id_defaults_to_none(self) -> None:
        e = _make_event()
        assert e.history_sync_id is None


class TestIsLive:
    def test_push_with_recent_platform_ts_is_live(self) -> None:
        now = datetime.now(timezone.utc)
        e = _make_event(platform_ts=now - timedelta(seconds=5), ts=now)
        assert e.is_live is True

    def test_push_with_old_platform_ts_is_stale(self) -> None:
        now = datetime.now(timezone.utc)
        e = _make_event(platform_ts=now - timedelta(seconds=120), ts=now)
        assert e.is_live is False

    def test_history_sync_is_never_live_even_when_fresh(self) -> None:
        now = datetime.now(timezone.utc)
        e = _make_event(
            delivery_mode="history_sync",
            platform_ts=now,
            ts=now,
            history_sync_id="sync-1",
        )
        assert e.is_live is False

    def test_history_sync_with_old_platform_ts_is_not_live(self) -> None:
        now = datetime.now(timezone.utc)
        e = _make_event(
            delivery_mode="history_sync",
            platform_ts=now - timedelta(hours=2),
            ts=now,
            history_sync_id="sync-1",
        )
        assert e.is_live is False

    def test_push_with_none_platform_ts_is_live_permissive(self) -> None:
        e = _make_event(platform_ts=None)
        assert e.is_live is True

    def test_freshness_window_env_override_extends(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A larger window makes a 90s-old message live."""
        monkeypatch.setenv("WORMBASE_FRESHNESS_WINDOW_S", "300")
        now = datetime.now(timezone.utc)
        e = _make_event(platform_ts=now - timedelta(seconds=90), ts=now)
        assert e.is_live is True

    def test_freshness_window_env_override_tightens(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A smaller window makes a 30s-old message stale."""
        monkeypatch.setenv("WORMBASE_FRESHNESS_WINDOW_S", "10")
        now = datetime.now(timezone.utc)
        e = _make_event(platform_ts=now - timedelta(seconds=30), ts=now)
        assert e.is_live is False

    def test_freshness_window_env_invalid_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WORMBASE_FRESHNESS_WINDOW_S", "not-a-number")
        now = datetime.now(timezone.utc)
        e = _make_event(platform_ts=now - timedelta(seconds=120), ts=now)
        # 120s is past the 60s default
        assert e.is_live is False
