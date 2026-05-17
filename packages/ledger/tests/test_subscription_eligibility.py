"""Tests for ``wormbase_ledger.subscription_eligibility`` (v1.4 #5).

These tests pin the eligibility contract — recursion-blocking
exclusions, PEVR primitive exclusions, and clock_tick exclusion — so
adding a new agent_subscription_* kind to the registry can't
accidentally re-open the recursion door.
"""

from __future__ import annotations

from wormbase_ledger.entries import KIND_REGISTRY
from wormbase_ledger.subscription_eligibility import (
    EXCLUDED_KINDS,
    META_KINDS,
    PEVR_KINDS,
    INFRA_KINDS,
    get_subscription_eligible_kinds,
)


# ---------------------------------------------------------------------------
# Eligibility contract — drift-resistant invariants.
# ---------------------------------------------------------------------------


def test_eligible_list_is_nonempty_and_ordered() -> None:
    rows = get_subscription_eligible_kinds()
    assert len(rows) > 0
    kinds = [r["kind"] for r in rows]
    assert kinds == sorted(kinds)


def test_meta_kinds_excluded_to_prevent_recursion() -> None:
    """``agent_subscription_*`` / ``agent_event_delivered`` MUST stay
    excluded — including them as subscribable kinds would let the
    subscription system fire on its own writes.
    """
    rows = get_subscription_eligible_kinds()
    kinds = {r["kind"] for r in rows}
    for meta_kind in META_KINDS:
        assert meta_kind not in kinds, (
            f"{meta_kind!r} is a meta-kind — including it as "
            f"subscription-eligible would trigger infinite "
            f"recursion. Add to META_KINDS in "
            f"subscription_eligibility.py if it's a new meta-kind."
        )


def test_pevr_primitives_excluded() -> None:
    """The four PEVR cycle primitives are excluded — every entry is
    one of them at the envelope level, so they're useless as filter
    axes (every write would match).
    """
    rows = get_subscription_eligible_kinds()
    kinds = {r["kind"] for r in rows}
    for pevr in PEVR_KINDS:
        assert pevr not in kinds


def test_infra_kinds_excluded() -> None:
    """``clock_tick`` is high-volume heartbeat noise. ``credential``
    carries material that should never escape. Both excluded.
    """
    rows = get_subscription_eligible_kinds()
    kinds = {r["kind"] for r in rows}
    for infra in INFRA_KINDS:
        assert infra not in kinds


def test_all_excluded_are_in_registry() -> None:
    """The exclusion list should not contain ghost kinds — if a kind
    is listed as excluded, it must actually exist in the registry
    (otherwise the exclusion list has drifted out of date).
    """
    for kind in EXCLUDED_KINDS:
        assert kind in KIND_REGISTRY, (
            f"{kind!r} is in EXCLUDED_KINDS but not in KIND_REGISTRY "
            f"— probably a rename drifted",
        )


def test_eligible_plus_excluded_equals_registry() -> None:
    """No registry kinds fall through the cracks.

    Every kind is either subscription-eligible or explicitly
    excluded. This pins the contract that adding a new entry kind
    surfaces it automatically without an extra registration step,
    while keeping the recursion-blocking exclusions explicit.
    """
    rows = get_subscription_eligible_kinds()
    eligible_kinds = {r["kind"] for r in rows}
    assert eligible_kinds | EXCLUDED_KINDS == set(KIND_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Row shape — every row carries the four fields the form needs.
# ---------------------------------------------------------------------------


def test_every_row_has_required_fields() -> None:
    rows = get_subscription_eligible_kinds()
    for row in rows:
        assert set(row.keys()) == {"kind", "label", "description", "family"}
        assert isinstance(row["kind"], str) and row["kind"]
        assert isinstance(row["label"], str) and row["label"]
        assert isinstance(row["description"], str) and row["description"]
        assert isinstance(row["family"], str) and row["family"]


def test_curated_descriptions_apply() -> None:
    """The canonical kinds the v2.A Batch C form surfaced get curated
    descriptions, not the default ``"event of kind X"``.

    (The v2.A list referenced ``source_disconnected`` and
    ``template_promoted`` aspirationally — those kinds aren't in
    KIND_REGISTRY yet. We test only what's actually present so this
    test won't break on the future-add side.)
    """
    rows = get_subscription_eligible_kinds()
    descriptions = {r["kind"]: r["description"] for r in rows}
    for canon in (
        "bad_pattern_proposed",
        "semantic_gap_escalated",
        "data_product_recommended",
        "source_connected",
        "data_product_consumed",
        "query_outcome_recorded",
        "query_template_promoted",
    ):
        assert canon in descriptions, f"{canon} is no longer eligible?"
        # Curated descriptions are full sentences and do NOT start
        # with "event of kind".
        assert not descriptions[canon].startswith("event of kind"), (
            f"{canon} should have a curated description, not the "
            f"default"
        )


def test_families_are_stable_set() -> None:
    """Every row's family is one of the documented family tags.

    Family tags are presentation-layer groupings; new families can
    be added but should not be invented per-call. This test makes
    a family rename visible.
    """
    expected_families = {
        "agent_lifecycle",
        "data_sources",
        "data_products",
        "metrics_and_kpis",
        "external_catalog",
        "research_loop",
        "conversations",
        "platform_lifecycle",
        "identity_and_roles",
        "decisions_and_processes",
        "governance",
        "other",
    }
    rows = get_subscription_eligible_kinds()
    seen = {r["family"] for r in rows}
    assert seen <= expected_families, (
        f"new family tag introduced: {seen - expected_families} — "
        f"update test or rename in FAMILY_PREFIXES"
    )
