"""log_boot_state emits exactly one INFO line iff silent mode is on."""

from __future__ import annotations

import logging

import pytest

from wormbase_core import silent_mode


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    silent_mode._reset_for_tests()
    yield
    silent_mode._reset_for_tests()


def test_log_boot_state_emits_when_silent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    with caplog.at_level(logging.INFO, logger="wormbase_core.silent_mode"):
        silent_mode.log_boot_state("test-app")
    assert any(
        "silent_mode=on" in r.message and "test-app" in r.message
        for r in caplog.records
    )


def test_log_boot_state_silent_when_off(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("WORMBASE_SILENT_MODE", raising=False)
    with caplog.at_level(logging.INFO, logger="wormbase_core.silent_mode"):
        silent_mode.log_boot_state("test-app")
    assert not any(
        "silent_mode" in r.message for r in caplog.records
    )
