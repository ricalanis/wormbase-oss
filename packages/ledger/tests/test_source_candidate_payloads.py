"""L1 Sub-wave A — three new lake-side source-candidate triage entry kinds.

Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=129.
21 kinds remain before the Wave F Addendum 4 ceiling at 150. L-axis
family count = 21 of 30 cap (L3=3 + L7=3 + L4=3 + L5=3 + L6=3 + L8=3 +
L1=3) per Addendum 4 §E — 9 headroom remaining (room for L2 + 2 future
axes).

Pins three new payload classes for the L1 lake loop that proposes
candidate data sources for admin triage + the admin lifecycle that
promotes/rejects them. L1 is the 7th lake-side compounding axis but
introduces ZERO new cross-axis Protocol chains in the L4→L3 / L6→L5 /
L8→L5 sense — its inference reads existing first-class platform
projections (``projection_sources`` / ``projection_kpi_nodes`` /
``projection_silver_conversations``) via lightweight Reader Protocols
rather than peer lake-axis projections. Cross-axis chain count stays
at 3.

* ``SourceCandidateProposedPayload`` (kind
  ``source_candidate_proposed``) — emitted by the L1 Compounding axis
  when a strategy (``kpi_gap`` / ``channel_mention`` /
  ``complementarity``) surfaces a candidate data source for triage.
  Carries a ``proposed_kind`` connector-registry string (runtime-
  validated against ``wormbase_lake_surfaces.registry.default_registry()``
  per spec §4.2 — NOT a ``Literal[...]``).
* ``SourceCandidatePromotedPayload`` (kind
  ``source_candidate_promoted``) — operator promotion of a previously-
  proposed candidate. Triggers a downstream ``source_proposed`` in
  Sub-wave C via dual-write; the optional
  ``downstream_source_proposed_id`` threads the candidate to its
  resulting source-pipeline row.
* ``SourceCandidateRejectedPayload`` (kind
  ``source_candidate_rejected``) — operator rejection with a
  categorical reason. The L1-specific 5th reason is ``duplicate``
  (distinct from L8's ``wrong_pairing``, L6's ``wrong_level``,
  L5's ``wrong_type``, L4's ``already_handled`` and L7's
  ``wrong_threshold``).

These tests pin:

* Registration in ``KIND_REGISTRY`` (auto-registration via
  ``EntryPayload.__init_subclass__``).
* Roundtrip via ``model_dump`` → ``model_validate`` byte-equivalently
  for full-field and minimal-field payloads.
* Strict validation: ``confidence`` in [0.0, 1.0]; ``reason`` pinned
  to the 5 documented values; non-empty ``candidate_id`` /
  ``proposed_identifier`` / ``strategy``.
* Runtime connector-kind validator: known kinds pass; unknown kinds
  raise. Empty kind raises non-empty error.
* ``domain_id_hint`` accepts None (strategies with no domain signal)
  and string values; ``downstream_source_proposed_id`` accepts None
  (unset before promote completes) and string values.
* ``make_candidate_id`` determinism + collision behavior (same args
  → same hash; different args → different hash).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

# Importing connectors first registers built-in connectors with the
# default registry so the runtime ``proposed_kind`` validator on
# ``SourceCandidateProposedPayload`` has the canonical kinds available
# (csv_local, postgres, snowflake, stripe, etc.) for the positive
# tests below.
import wormbase_lake_surfaces  # noqa: F401
from wormbase_lake_surfaces.registry import default_registry

from wormbase_ledger.entries import (
    ALL_KINDS,
    KIND_REGISTRY,
    SourceCandidateProposedPayload,
    SourceCandidatePromotedPayload,
    SourceCandidateRejectedPayload,
    make_candidate_id,
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        "source_candidate_proposed",
        "source_candidate_promoted",
        "source_candidate_rejected",
    ],
)
def test_source_candidate_kind_registered(kind: str) -> None:
    """Each new L1 kind auto-registers in KIND_REGISTRY + ALL_KINDS."""
    assert kind in KIND_REGISTRY
    assert kind in ALL_KINDS


def test_source_candidate_kinds_do_not_collide_with_source_pipeline() -> None:
    """L1's ``source_candidate_*`` namespace is distinct from the
    pre-existing ``source_*`` post-promotion lifecycle.

    Per spec §1 naming-collision check: the existing ``source_proposed``
    / ``source_confirmed`` / ``source_connected`` / ``source_profiled``
    kinds are the post-promotion lifecycle of an already-decided
    source; L1 is the prequel triage layer. Pinning this here so a
    future rename collision triggers at commit time."""
    pipeline_kinds = {
        "source_proposed",
        "source_confirmed",
        "source_connected",
        "source_profiled",
    }
    candidate_kinds = {
        "source_candidate_proposed",
        "source_candidate_promoted",
        "source_candidate_rejected",
    }
    # All pipeline kinds present (we did not rename them).
    assert pipeline_kinds <= set(KIND_REGISTRY.keys())
    # All candidate kinds present (we added them).
    assert candidate_kinds <= set(KIND_REGISTRY.keys())
    # No overlap (L1 didn't reuse existing kind names).
    assert pipeline_kinds.isdisjoint(candidate_kinds)


# ---------------------------------------------------------------------------
# make_candidate_id determinism + collision behavior
# ---------------------------------------------------------------------------


def test_make_candidate_id_deterministic_same_args() -> None:
    """Same args → identical hash (idempotent dedup primitive)."""
    a = make_candidate_id(
        proposed_kind="csv_local",
        proposed_identifier="/data/q3_sales.csv",
        strategy="kpi_gap",
    )
    b = make_candidate_id(
        proposed_kind="csv_local",
        proposed_identifier="/data/q3_sales.csv",
        strategy="kpi_gap",
    )
    assert a == b


def test_make_candidate_id_collision_only_on_full_triple() -> None:
    """Different identifier OR kind OR strategy → distinct hash.

    Same strategy proposing the same source → dedup naturally;
    different strategies proposing the same source → distinct rows
    so each strategy's case to the admin surfaces independently."""
    base = make_candidate_id(
        proposed_kind="postgres",
        proposed_identifier="prod-app-db",
        strategy="complementarity",
    )
    diff_kind = make_candidate_id(
        proposed_kind="snowflake",
        proposed_identifier="prod-app-db",
        strategy="complementarity",
    )
    diff_id = make_candidate_id(
        proposed_kind="postgres",
        proposed_identifier="staging-app-db",
        strategy="complementarity",
    )
    diff_strategy = make_candidate_id(
        proposed_kind="postgres",
        proposed_identifier="prod-app-db",
        strategy="kpi_gap",
    )
    assert base != diff_kind
    assert base != diff_id
    assert base != diff_strategy
    assert len({base, diff_kind, diff_id, diff_strategy}) == 4


def test_make_candidate_id_is_32_hex_chars() -> None:
    """Returns a 32-char hex prefix (sha256[:32]); URL/SQL-safe opaque."""
    h = make_candidate_id(
        proposed_kind="stripe",
        proposed_identifier="acct_1234",
        strategy="kpi_gap",
    )
    assert len(h) == 32
    assert all(c in "0123456789abcdef" for c in h)


def test_make_candidate_id_keyword_only() -> None:
    """All args are keyword-only (no positional confusion at call sites)."""
    with pytest.raises(TypeError):
        # Positional call must fail — mirrors L8's make_stitch_id contract.
        make_candidate_id("csv_local", "/data/x.csv", "kpi_gap")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SourceCandidateProposedPayload
# ---------------------------------------------------------------------------


def test_source_candidate_proposed_roundtrip_full() -> None:
    """Full payload (with domain hint + rich evidence) survives
    model_dump → model_validate byte-equivalently."""
    cid = make_candidate_id(
        proposed_kind="stripe",
        proposed_identifier="acct_q3_revenue",
        strategy="kpi_gap",
    )
    p = SourceCandidateProposedPayload(
        candidate_id=cid,
        proposed_kind="stripe",
        proposed_identifier="acct_q3_revenue",
        domain_id_hint="domain-finance-1",
        strategy="kpi_gap",
        reasoning="KPI 'q3_revenue' has no backing data source; revenue KPIs typically map to Stripe or Salesforce.",
        confidence=0.72,
        evidence={
            "kpi_node_id": "kpi-q3-revenue",
            "kpi_name_pattern": "*_revenue",
        },
    )
    assert SourceCandidateProposedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "source_candidate_proposed"


def test_source_candidate_proposed_roundtrip_minimal_no_domain_hint() -> None:
    """Minimal payload (no domain hint) — strategies with no domain
    signal omit the field; it defaults to None."""
    cid = make_candidate_id(
        proposed_kind="csv_local",
        proposed_identifier="/uploads/marketing.csv",
        strategy="complementarity",
    )
    p = SourceCandidateProposedPayload(
        candidate_id=cid,
        proposed_kind="csv_local",
        proposed_identifier="/uploads/marketing.csv",
        strategy="complementarity",
        reasoning="ad-hoc file drops not configured",
        confidence=0.45,
        evidence={},
    )
    assert p.domain_id_hint is None
    assert SourceCandidateProposedPayload.model_validate(p.model_dump()) == p


@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0, -1.0])
def test_source_candidate_proposed_rejects_out_of_range_confidence(bad: float) -> None:
    """confidence outside [0.0, 1.0] raises ValidationError."""
    cid = make_candidate_id(
        proposed_kind="csv_local",
        proposed_identifier="x",
        strategy="kpi_gap",
    )
    with pytest.raises(ValidationError) as exc:
        SourceCandidateProposedPayload(
            candidate_id=cid,
            proposed_kind="csv_local",
            proposed_identifier="x",
            strategy="kpi_gap",
            reasoning="r",
            confidence=bad,
            evidence={},
        )
    assert "confidence" in str(exc.value)


@pytest.mark.parametrize(
    "field",
    [
        "candidate_id",
        "proposed_kind",
        "proposed_identifier",
        "strategy",
    ],
)
def test_source_candidate_proposed_rejects_empty_required_string(field: str) -> None:
    """Each required identifier / strategy field rejects the empty string."""
    valid = dict(
        candidate_id="abc123",
        proposed_kind="csv_local",
        proposed_identifier="x",
        strategy="kpi_gap",
        reasoning="r",
        confidence=0.5,
        evidence={},
    )
    valid[field] = ""
    with pytest.raises(ValidationError) as exc:
        SourceCandidateProposedPayload(**valid)  # type: ignore[arg-type]
    assert field in str(exc.value) or "non-empty" in str(exc.value)


@pytest.mark.parametrize(
    "strategy",
    ["kpi_gap", "channel_mention", "complementarity"],
)
def test_source_candidate_proposed_accepts_canonical_strategies(strategy: str) -> None:
    """The three canonical strategies (spec §4.3) round-trip cleanly."""
    cid = make_candidate_id(
        proposed_kind="csv_local",
        proposed_identifier="x",
        strategy=strategy,
    )
    p = SourceCandidateProposedPayload(
        candidate_id=cid,
        proposed_kind="csv_local",
        proposed_identifier="x",
        strategy=strategy,
        reasoning="r",
        confidence=0.5,
        evidence={},
    )
    assert p.strategy == strategy


def test_source_candidate_proposed_accepts_future_strategy_plugin() -> None:
    """``strategy`` is an open string field with a non-empty guard —
    future strategy plug-ins ship without ledger churn (only the
    canonical three are documented per spec §4.3)."""
    cid = make_candidate_id(
        proposed_kind="csv_local",
        proposed_identifier="x",
        strategy="custom_plugin",
    )
    p = SourceCandidateProposedPayload(
        candidate_id=cid,
        proposed_kind="csv_local",
        proposed_identifier="x",
        strategy="custom_plugin",
        reasoning="experimental strategy",
        confidence=0.5,
        evidence={},
    )
    assert p.strategy == "custom_plugin"


# ---------------------------------------------------------------------------
# SurfaceDriver-kind runtime validator
# ---------------------------------------------------------------------------


def test_source_candidate_proposed_accepts_every_registered_connector_kind() -> None:
    """Every kind in the default registry is accepted by the runtime
    validator — strategies must consult ``default_registry()`` before
    proposing, and the ledger must accept every kind the registry
    exposes."""
    registry = default_registry()
    known = registry.all_kinds()
    # Smoke: at least the day-one connectors should be present so this
    # test exercises the positive path on something real.
    assert len(known) > 0, (
        "connector registry empty — wormbase_lake_surfaces should auto-register "
        "built-in connectors at import time"
    )
    for kind in known:
        cid = make_candidate_id(
            proposed_kind=kind,
            proposed_identifier="x",
            strategy="kpi_gap",
        )
        p = SourceCandidateProposedPayload(
            candidate_id=cid,
            proposed_kind=kind,
            proposed_identifier="x",
            strategy="kpi_gap",
            reasoning="r",
            confidence=0.5,
            evidence={},
        )
        assert p.proposed_kind == kind


def test_source_candidate_proposed_rejects_unknown_connector_kind() -> None:
    """Unknown ``proposed_kind`` raises ValidationError naming the
    field — strategies must not propose connectors the registry can't
    materialise (per spec §4.2)."""
    cid = make_candidate_id(
        proposed_kind="totally_made_up_xyz",
        proposed_identifier="x",
        strategy="kpi_gap",
    )
    with pytest.raises(ValidationError) as exc:
        SourceCandidateProposedPayload(
            candidate_id=cid,
            proposed_kind="totally_made_up_xyz",
            proposed_identifier="x",
            strategy="kpi_gap",
            reasoning="r",
            confidence=0.5,
            evidence={},
        )
    msg = str(exc.value)
    assert "proposed_kind" in msg or "connector registry" in msg


def test_source_candidate_proposed_accepts_mcp_namespaced_kind() -> None:
    """``mcp:*`` prefixed kinds are first-class registry entries per
    the registry naming convention. If any MCP connector preset is
    registered, it accepts cleanly; if none are, the test skips.

    Spec §4.2 lists ``mcp:notion`` as a valid example proposed_kind.
    """
    registry = default_registry()
    mcp_kinds = [k for k in registry.all_kinds() if k.startswith("mcp:")]
    if not mcp_kinds:
        pytest.skip("no mcp:* connectors registered in default registry")
    kind = mcp_kinds[0]
    cid = make_candidate_id(
        proposed_kind=kind,
        proposed_identifier="workspace-abc",
        strategy="channel_mention",
    )
    p = SourceCandidateProposedPayload(
        candidate_id=cid,
        proposed_kind=kind,
        proposed_identifier="workspace-abc",
        strategy="channel_mention",
        reasoning="r",
        confidence=0.5,
        evidence={},
    )
    assert p.proposed_kind == kind


# ---------------------------------------------------------------------------
# SourceCandidatePromotedPayload
# ---------------------------------------------------------------------------


def test_source_candidate_promoted_roundtrip_full() -> None:
    """Full payload (with downstream link + notes) survives roundtrip."""
    p = SourceCandidatePromotedPayload(
        candidate_id="abc123",
        promoted_by_person_id="person-uuid-1",
        downstream_source_proposed_id="entry-uuid-downstream-1",
        notes="approved for connection",
    )
    assert SourceCandidatePromotedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "source_candidate_promoted"


def test_source_candidate_promoted_roundtrip_minimal() -> None:
    """Minimal payload — no notes, no downstream link (Sub-wave B may
    promote without immediately threading downstream; the projection
    fold accepts NULL)."""
    p = SourceCandidatePromotedPayload(
        candidate_id="abc123",
        promoted_by_person_id="person-uuid-1",
    )
    assert p.notes is None
    assert p.downstream_source_proposed_id is None
    assert SourceCandidatePromotedPayload.model_validate(p.model_dump()) == p


def test_source_candidate_promoted_rejects_empty_candidate_id() -> None:
    """Empty candidate_id raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        SourceCandidatePromotedPayload(
            candidate_id="",
            promoted_by_person_id="person-uuid-1",
        )
    assert "candidate_id" in str(exc.value) or "non-empty" in str(exc.value)


# ---------------------------------------------------------------------------
# SourceCandidateRejectedPayload
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        "duplicate",
        "false_positive",
        "low_value",
        "out_of_scope",
        "other",
    ],
)
def test_source_candidate_rejected_accepts_every_reason(reason: str) -> None:
    """All 5 documented rejection reasons are accepted (including the
    L1-specific ``duplicate``)."""
    p = SourceCandidateRejectedPayload(
        candidate_id="abc123",
        rejected_by_person_id="person-uuid-1",
        reason=reason,  # type: ignore[arg-type]
    )
    assert p.reason == reason
    assert SourceCandidateRejectedPayload.model_validate(p.model_dump()) == p


def test_source_candidate_rejected_includes_duplicate() -> None:
    """``duplicate`` is the L1-specific reason (distinct from L8's
    ``wrong_pairing``, L6's ``wrong_level``, L5's ``wrong_type``,
    L4's ``already_handled`` and L7's ``wrong_threshold``)."""
    p = SourceCandidateRejectedPayload(
        candidate_id="abc123",
        rejected_by_person_id="person-uuid-1",
        reason="duplicate",
        notes="we already have an equivalent stripe connection",
    )
    assert p.reason == "duplicate"
    assert p.kind == "source_candidate_rejected"


def test_source_candidate_rejected_rejects_unknown_reason() -> None:
    """An out-of-enum reason raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        SourceCandidateRejectedPayload(
            candidate_id="abc123",
            rejected_by_person_id="person-uuid-1",
            reason="bogus_reason",  # type: ignore[arg-type]
        )
    assert "reason" in str(exc.value)


def test_source_candidate_rejected_rejects_empty_candidate_id() -> None:
    """Empty candidate_id raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        SourceCandidateRejectedPayload(
            candidate_id="",
            rejected_by_person_id="person-uuid-1",
            reason="false_positive",
        )
    assert "candidate_id" in str(exc.value) or "non-empty" in str(exc.value)


# ---------------------------------------------------------------------------
# Subscription eligibility
# ---------------------------------------------------------------------------


def test_source_candidate_kinds_are_subscription_eligible() -> None:
    """L1 kinds appear in the subscription-eligible catalog and fall
    under the ``data_sources`` family by prefix match."""
    from wormbase_ledger.subscription_eligibility import (
        get_subscription_eligible_kinds,
    )

    rows = get_subscription_eligible_kinds()
    by_kind = {row["kind"]: row for row in rows}
    for kind in (
        "source_candidate_proposed",
        "source_candidate_promoted",
        "source_candidate_rejected",
    ):
        assert kind in by_kind, f"{kind} missing from subscription-eligible catalog"
        # ``source_*`` prefix matches the ``data_sources`` family in
        # ``FAMILY_PREFIXES``; this pins the categorization so future
        # registry edits don't silently re-bucket L1.
        assert by_kind[kind]["family"] == "data_sources"
