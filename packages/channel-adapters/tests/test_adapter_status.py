"""Capability-honesty: every registered ChannelAdapter exposes status + status_note.

Mirrors :mod:`tests.test_connector_status` for the channel-adapter
package. The dashboard's channels tab renders these verbatim.

Status grading for adapters:
- production: every method (authenticate, install, listen, send,
  file_upload, list_workspace_members) is wired against the real platform.
- preview: install + listen are real (worm will lurk + wire-events
  flow); send / file_upload may be skeletal.
- coming_soon: skeleton only; not yet usable end-to-end.
"""

from __future__ import annotations

import pytest

from wormbase_channel_adapters.registry import default_registry

ALLOWED_STATUSES = {"production", "preview", "coming_soon"}

EXPECTED_STATUS: dict[str, str] = {
    "slack": "production",
    "discord": "preview",
    "teams": "preview",
}


def _all_registered_classes() -> list[type]:
    reg = default_registry()
    return [
        reg.get(p)
        for p in reg.all_platforms()
        if reg.get(p) is not None
    ]


@pytest.mark.parametrize("cls", _all_registered_classes())
def test_adapter_declares_status(cls: type) -> None:
    status = getattr(cls, "status", None)
    assert isinstance(status, str), f"{cls.__name__}.status must be a str"
    assert status in ALLOWED_STATUSES, (
        f"{cls.__name__}.status={status!r} must be one of {ALLOWED_STATUSES}"
    )


@pytest.mark.parametrize("cls", _all_registered_classes())
def test_adapter_declares_status_note(cls: type) -> None:
    note = getattr(cls, "status_note", None)
    assert isinstance(note, str) and len(note) > 0, (
        f"{cls.__name__}.status_note must be a non-empty str"
    )
    assert len(note) <= 200, (
        f"{cls.__name__}.status_note exceeds 200 chars — too long for "
        "the adapter card UI"
    )


@pytest.mark.parametrize("platform,expected", sorted(EXPECTED_STATUS.items()))
def test_adapter_status_matches_expectation(
    platform: str, expected: str,
) -> None:
    cls = default_registry().get(platform)
    assert cls is not None, f"{platform} should be registered"
    assert cls.status == expected, (
        f"{platform} declared status={cls.status!r}, expected {expected!r}"
    )


def test_every_adapter_owns_status() -> None:
    for cls in _all_registered_classes():
        assert "status" in cls.__dict__, (
            f"{cls.__name__} should declare its own `status` attribute"
        )
        assert "status_note" in cls.__dict__, (
            f"{cls.__name__} should declare its own `status_note` attribute"
        )
