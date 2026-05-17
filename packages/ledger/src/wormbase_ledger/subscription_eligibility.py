"""Subscription-eligible kinds catalog — v1.4 #5.

Replaces the hardcoded 8-kind list that ``SubscriptionForm.tsx`` shipped
in v2.A Batch C with a derived, drift-free list. The eligibility logic
lives next to ``KIND_REGISTRY`` so the same exclusion rules apply to
the dashboard form, MCP tooling, and any future surface.

Inclusion criteria (per v1.4 #5 spec):

* Kinds emitted by reactivity-driven processes the worm produces
  on the agent's behalf — ``data_product_recommended``,
  ``bad_pattern_proposed``, ``semantic_gap_escalated``,
  ``query_template_promoted``, ``source_*``, etc.
* Kinds that represent business-meaningful events the agent might
  want push notifications on — ``chat_received``, KPI-related
  entries, ``decision_recorded``, ``process_map_proposed``,
  ``data_product_consumed``.

Exclusion criteria:

* **Meta-kinds** (would cause subscription recursion):
  ``agent_subscription_created``, ``agent_subscription_revoked``,
  ``agent_event_delivered``.
* **Ledger primitives** (PEVR cycle bookkeeping is not user-meaningful
  as a subscription axis): ``propose``, ``execute``, ``verify``,
  ``resolve``.
* **Clock / infra heartbeats**: ``clock_tick``, ``inference_cache_refreshed``.
* **Internal credential machinery**: ``credential``.

Categorization into UI-friendly ``family`` buckets groups the eligible
kinds visually. The labels are presentation strings (human-readable),
not new identifiers — the kind string is the durable identifier.

The shape is deliberately small (kind / label / description / family)
so the HTTP endpoint and the MCP tool can return it verbatim. No
versioning is needed because the function returns derived data — any
new kind that doesn't appear in the exclusion list flows into the
eligible list automatically with a sensible default family.
"""

from __future__ import annotations

from typing import TypedDict


# Meta-kinds — including these as subscription axes would cause the
# subscription system to fire on its own writes (infinite recursion).
META_KINDS: frozenset[str] = frozenset({
    "agent_subscription_created",
    "agent_subscription_revoked",
    "agent_event_delivered",
})

# PEVR cycle primitives — every entry is one of these at the envelope
# level, so they aren't useful subscription axes (every write would
# match). Subscribers filter on the inner ``target_kind`` instead.
PEVR_KINDS: frozenset[str] = frozenset({
    "propose",
    "execute",
    "verify",
    "resolve",
})

# Infrastructure / heartbeat / credential primitives — high-volume,
# low semantic content, or carrying material that should never escape
# the worm boundary.
INFRA_KINDS: frozenset[str] = frozenset({
    "clock_tick",
    "inference_cache_refreshed",
    "credential",
})

EXCLUDED_KINDS: frozenset[str] = META_KINDS | PEVR_KINDS | INFRA_KINDS


# Family classification — used by the dashboard SubscriptionForm to
# group the checkbox grid. The pattern matches the prefix of the kind
# string for cheap categorization; "other" catches anything new.
FAMILY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("agent_", "agent_lifecycle"),
    ("source_", "data_sources"),
    ("ingest_", "data_sources"),
    ("lake_", "data_sources"),
    ("data_product_", "data_products"),
    ("notebook_", "data_products"),
    ("kpi_", "metrics_and_kpis"),
    ("metric_", "metrics_and_kpis"),
    ("metrics_", "metrics_and_kpis"),
    ("external_", "external_catalog"),
    # L2 catalog-drift family — same external-catalog bucket as the
    # ``external_catalog_*`` cousins. The L2 axis is the inference-
    # bearing prequel to the ``external_catalog_drift_detected``
    # substrate; both surface as catalog observability in the UI.
    ("catalog_drift_", "external_catalog"),
    ("experiment_", "research_loop"),
    ("heuristic_", "research_loop"),
    ("phenomenon_", "research_loop"),
    ("query_", "research_loop"),
    ("template_", "research_loop"),
    ("bad_pattern_", "research_loop"),
    ("semantic_gap_", "research_loop"),
    ("inference_", "research_loop"),
    ("chat_", "conversations"),
    ("conversation_", "conversations"),
    ("recurring_", "conversations"),
    ("topic_", "conversations"),
    ("install_", "platform_lifecycle"),
    ("tenant_signup_", "platform_lifecycle"),
    ("setup_", "platform_lifecycle"),
    ("mcp_", "platform_lifecycle"),
    ("person_", "identity_and_roles"),
    ("identity_", "identity_and_roles"),
    ("position_", "identity_and_roles"),
    ("role_", "identity_and_roles"),
    ("resource_role_", "identity_and_roles"),
    ("resource_conversation_", "identity_and_roles"),
    ("domain_role_", "identity_and_roles"),
    ("decision_", "decisions_and_processes"),
    ("process_map_", "decisions_and_processes"),
    ("policy_", "decisions_and_processes"),
    ("system_map_", "decisions_and_processes"),
    ("gate_", "governance"),
    ("memory_", "governance"),
    ("reactivity_", "governance"),
    ("concept_", "governance"),
    ("classification_", "governance"),
)


def _family_for(kind: str) -> str:
    """Return the UI family bucket for a kind. Unmatched → ``other``."""
    for prefix, family in FAMILY_PREFIXES:
        if kind.startswith(prefix):
            return family
    return "other"


def _label_for(kind: str) -> str:
    """Human-readable label — title-cased with underscores → spaces."""
    return kind.replace("_", " ")


# Optional curated descriptions for the most commonly-subscribed
# kinds. New kinds that don't appear here get a sensible default
# (``"event of kind X"``) so the endpoint never returns a missing
# field.
KIND_DESCRIPTIONS: dict[str, str] = {
    "bad_pattern_proposed": (
        "A pattern that consistently produces low-quality query "
        "outcomes — proposed for admin review."
    ),
    "semantic_gap_escalated": (
        "A query intent the worm couldn't satisfy — escalated for "
        "admin attention."
    ),
    "data_product_recommended": (
        "The worm recommends a new data product based on observed "
        "query outcomes."
    ),
    "data_product_consumed": (
        "An agent or human read a data product — useful for usage "
        "tracking."
    ),
    "data_product_generated": (
        "A data product was generated (notebook output, materialised "
        "view, etc.)."
    ),
    "data_product_proposed": (
        "A new data product is proposed — pending admin confirmation."
    ),
    "source_connected": (
        "A new data source finished connecting and is now part of "
        "the lake."
    ),
    "source_disconnected": (
        "A previously-connected source has been disconnected or "
        "revoked."
    ),
    "source_proposed": (
        "A candidate data source is proposed — pending admin or "
        "owner confirmation."
    ),
    "source_profiled": (
        "A source has been profiled — schema, distributions, and "
        "classification hints are now in the lake."
    ),
    "query_outcome_recorded": (
        "An agent recorded the outcome of a query (success / "
        "failure / partial)."
    ),
    "query_template_promoted": (
        "A query pattern has been promoted to a durable template — "
        "the worm has learned a new shortcut."
    ),
    "kpi_proposed": "A new KPI is proposed for the tenant's KPI tree.",
    "kpi_answered": (
        "The worm answered a KPI question — value, freshness, and "
        "provenance attached."
    ),
    "decision_recorded": (
        "A decision has been recorded against a domain or resource "
        "(immutable)."
    ),
    "process_map_proposed": (
        "A process map (how decisions flow through the org) was "
        "proposed by the worm."
    ),
    "chat_received": (
        "A message arrived on a connected channel. High volume — "
        "scope with domain or payload_path filters."
    ),
    "external_catalog_imported": (
        "An external catalog (dbt, Snowflake, …) has been imported."
    ),
    "external_metric_imported": (
        "An external metric definition has been imported into the lake."
    ),
}


class SubscriptionEligibleKind(TypedDict):
    """One row in the subscription-eligible kinds payload."""

    kind: str
    label: str
    description: str
    family: str


def get_subscription_eligible_kinds() -> list[SubscriptionEligibleKind]:
    """Return KIND_REGISTRY filtered to subscription-eligible kinds.

    Derives the list at call time so the answer always reflects the
    current registry — no hand-maintained mirror table to drift.
    Excludes the meta-kinds, PEVR primitives, and infra heartbeats
    documented in this module's docstring.

    Ordered alphabetically by ``kind`` for deterministic test output
    and predictable UI rendering.
    """
    # Import inside the function so this module is import-cheap; the
    # registry import resolves quickly once the registry has been
    # populated by the entries module.
    from wormbase_ledger.entries import KIND_REGISTRY

    rows: list[SubscriptionEligibleKind] = []
    for kind in sorted(KIND_REGISTRY.keys()):
        if kind in EXCLUDED_KINDS:
            continue
        rows.append(
            SubscriptionEligibleKind(
                kind=kind,
                label=_label_for(kind),
                description=KIND_DESCRIPTIONS.get(
                    kind, f"event of kind {kind}",
                ),
                family=_family_for(kind),
            )
        )
    return rows
