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
