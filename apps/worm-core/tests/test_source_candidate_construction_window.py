"""Env-var wiring for ChannelMentionAcquisitionStrategy.lookback_seconds.

WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_WINDOW (seconds) overrides
the strategy's default 24h lookback. Required for the Altis kickoff
demo on 2026-05-25, where the May 22 prep-call SRT was ingested
~36-48h before the kickoff (outside the default window).
"""

from __future__ import annotations

import pytest

from wormbase_core.agent_gateway_construction import (
    build_source_candidate_service_from_env,
    is_source_candidate_channel_mention_enabled,
    is_source_candidate_discovery_enabled,
)
from wormbase_ledger import InMemoryLedger


def _enable_channel_mention(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED", "1")
    monkeypatch.setenv("WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED", "1")


def test_window_override_propagates_to_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting the WINDOW env to 7d makes the strategy use 604800s."""
    _enable_channel_mention(monkeypatch)
    monkeypatch.setenv(
        "WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_WINDOW", "604800",
    )
    service = build_source_candidate_service_from_env(
        ledger=InMemoryLedger(),
    )
    assert service is not None
    strategy = service._strategies.get("channel_mention")
    assert strategy is not None
    assert strategy.lookback_seconds == 604800


def test_no_window_override_uses_strategy_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent / zero env var means the strategy uses its 86400s default."""
    _enable_channel_mention(monkeypatch)
    monkeypatch.delenv(
        "WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_WINDOW", raising=False,
    )
    service = build_source_candidate_service_from_env(
        ledger=InMemoryLedger(),
    )
    assert service is not None
    strategy = service._strategies.get("channel_mention")
    assert strategy is not None
    assert strategy.lookback_seconds == 86400  # DEFAULT_LOOKBACK_SECONDS


def test_zero_window_override_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 0 value (sentinel for 'not set') falls back to the default."""
    _enable_channel_mention(monkeypatch)
    monkeypatch.setenv(
        "WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_WINDOW", "0",
    )
    service = build_source_candidate_service_from_env(
        ledger=InMemoryLedger(),
    )
    assert service is not None
    strategy = service._strategies.get("channel_mention")
    assert strategy is not None
    assert strategy.lookback_seconds == 86400
