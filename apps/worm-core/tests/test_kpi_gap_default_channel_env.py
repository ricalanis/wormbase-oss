"""Tests for ``kpi_gap_default_channel_id`` env-knob — Onboarding Sub-wave C
(2026-05-30), addressing Sub-wave A handoff #4.

Lets operators thread the worm's owner-channel target for KPI-gap
escalations through env. Default OFF preserves the previous per-domain
mapping path.
"""
from __future__ import annotations

import os

import pytest

from wormbase_core.service import kpi_gap_default_channel_id


@pytest.fixture(autouse=True)
def _restore_env(monkeypatch: pytest.MonkeyPatch):
    """Each test starts with a clean env slot."""
    monkeypatch.delenv("WORMBASE_KPI_GAP_DEFAULT_CHANNEL", raising=False)
    yield


def test_default_when_unset_is_none() -> None:
    """Env unset → None (per-domain mapping path)."""
    assert "WORMBASE_KPI_GAP_DEFAULT_CHANNEL" not in os.environ
    assert kpi_gap_default_channel_id() is None


def test_empty_string_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty / whitespace-only values are treated as unset."""
    monkeypatch.setenv("WORMBASE_KPI_GAP_DEFAULT_CHANNEL", "")
    assert kpi_gap_default_channel_id() is None
    monkeypatch.setenv("WORMBASE_KPI_GAP_DEFAULT_CHANNEL", "   ")
    assert kpi_gap_default_channel_id() is None


def test_value_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real channel id round-trips through the helper."""
    monkeypatch.setenv("WORMBASE_KPI_GAP_DEFAULT_CHANNEL", "C01ABC123")
    assert kpi_gap_default_channel_id() == "C01ABC123"


def test_whitespace_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Surrounding whitespace gets stripped — preserves usability for
    operators copying values from web UIs."""
    monkeypatch.setenv("WORMBASE_KPI_GAP_DEFAULT_CHANNEL", "  C01ABC123  ")
    assert kpi_gap_default_channel_id() == "C01ABC123"
