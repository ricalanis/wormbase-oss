"""Capability-honesty: every registered SurfaceDriver exposes status + status_note.

The dashboard's connector picker (D4) renders these fields verbatim.
This test is the single enforcement point: if a new connector lands
without ``status`` / ``status_note``, this test fails — a connector
cannot quietly ship as ambiguous.

The three allowed values are documented in
``docs/architecture/connectors.md`` (production / preview / coming_soon).
"""

from __future__ import annotations

import pytest

from wormbase_lake_surfaces.registry import default_registry

ALLOWED_STATUSES = {"production", "preview", "coming_soon"}

# Concrete expectations per kind. Production-grade connectors with
# every method wired land as "production"; skeletals that exist for
# proof-of-abstraction only land as "coming_soon". Update when a
# skeleton is promoted past v1.5.
EXPECTED_STATUS: dict[str, str] = {
    "csv_local": "production",
    "postgres": "production",
    "snowflake": "production",
    "s3_csv": "production",
    "http_csv": "production",
    "stripe": "production",
    "bigquery": "coming_soon",
    "salesforce": "coming_soon",
    "hubspot": "coming_soon",
    "gsheets": "coming_soon",
    "notion": "coming_soon",
    "linear": "coming_soon",
}


def _all_registered_classes() -> list[type]:
    reg = default_registry()
    return [reg.get(k) for k in reg.all_kinds() if reg.get(k) is not None]


@pytest.mark.parametrize("cls", _all_registered_classes())
def test_connector_declares_status(cls: type) -> None:
    status = getattr(cls, "status", None)
    assert isinstance(status, str), f"{cls.__name__}.status must be a str"
    assert status in ALLOWED_STATUSES, (
        f"{cls.__name__}.status={status!r} must be one of {ALLOWED_STATUSES}"
    )


@pytest.mark.parametrize("cls", _all_registered_classes())
def test_connector_declares_status_note(cls: type) -> None:
    note = getattr(cls, "status_note", None)
    assert isinstance(note, str) and len(note) > 0, (
        f"{cls.__name__}.status_note must be a non-empty str"
    )
    # User-facing — keep terse so it fits on a card.
    assert len(note) <= 200, (
        f"{cls.__name__}.status_note exceeds 200 chars — too long for "
        "the connector card UI"
    )


@pytest.mark.parametrize("kind,expected", sorted(EXPECTED_STATUS.items()))
def test_connector_status_matches_expectation(
    kind: str, expected: str,
) -> None:
    """Hard assertion of expected status for each day-one kind.

    If you're promoting a skeletal to production, update both
    EXPECTED_STATUS here and the connector's class-level ``status``.
    """
    cls = default_registry().get(kind)
    assert cls is not None, f"{kind} should be registered"
    assert cls.status == expected, (
        f"{kind} declared status={cls.status!r}, expected {expected!r}"
    )


def test_no_default_status_in_concrete_connectors() -> None:
    """Every concrete connector explicitly sets status (not via base default).

    The skeletal base provides ``"coming_soon"`` as a fallback, but each
    concrete class should still declare its own — so promotions are
    explicit. We allow the skeletals to accept the base default if they
    pin to coming_soon, but production connectors must not.
    """
    for cls in _all_registered_classes():
        # If the class itself doesn't define status in its dict, it's
        # inheriting — only allowable for skeletons keeping coming_soon.
        owns_status = "status" in cls.__dict__
        assert owns_status, (
            f"{cls.__name__} should declare its own `status` attribute "
            f"rather than relying on inheritance"
        )
