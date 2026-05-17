"""Rich-seed enrichment for Beat-9 (Statement-to-Owner) standalone replay.

W7.A1 — companion to ``seed.py``, ``seed_install.py``, ``seed_personas.py``,
``seed_local_lake.py``. After the canonical four personas are confirmed,
this module pre-populates the tenant with the resources Beat-9 needs to
fire deterministically:

* a confirmed ``churn_rate`` KPI (matches "churn" via topic_extractor's
  multi-word partial-match heuristic at confidence ≥ 0.7),
* a custom ``retention`` domain with Carol granted ``domain.owner``,
* Carol granted ``resource.maintainer`` on the KPI itself,
* 2 retention-tagged decisions, 1 process map, 1 data product —
  enough to populate the resource_aggregator bundle the DM template
  pins.

Without these, ``topic_extractor`` returns ``None`` for "churn" on a
fresh install, and Beat-9 never fires — the only reactivity that
engages is the phenomenon-gap detector. This helper restores Beat-9 to
a single-tenant standalone runnable state, which the ``beat9-focused``
scenario depends on.

The module strictly uses the worm-core HTTP write API (the same path
the dashboard uses). The only direct ledger write is the
``emit_domain_registered`` shim — there is no HTTP endpoint for that
because in production domains are registered by ``CompanyWarmup``.
We synthesize a "retention" domain entry to make it discoverable to
``topic_extractor._build_catalog`` without altering the ontology
packs.

Hash stability:

* Resource UUIDs are auto-generated on the worm-core side (the API
  bodies do not surface optional ids). Content (label, formula,
  decision text, process_name, source_hashes) is deterministic across
  runs; UUIDs vary. This is consistent with the production write path.
* Visual-baseline regeneration (W7.A6) operates against the rendered
  surface, which keys on label / status / position rather than UUID,
  so this is fine.

Public API:

* ``seed_rich(*, tenant, carol_person_id, dashboard_api_base, api_token,
  ledger=None, ...)`` — async function that drives one full propose
  cycle of each artifact (KPI, role grants, domain registration,
  decisions, process map, data product) and returns a
  ``SeedRichReport``. Idempotent over the content axis: re-running
  produces the same labels / texts / source_hashes; UUIDs differ per
  run.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid5, NAMESPACE_DNS

import httpx

from wormbase_ledger import InMemoryLedger, Ledger

logger = logging.getLogger("wormbase.sim.seed_rich")


# ---------------------------------------------------------------------------
# Canonical content — deterministic across runs.
# ---------------------------------------------------------------------------


# KPI label is the exact string topic_extractor scores against. We use
# "churn_rate" (vs the bare "churn") so it stays distinguishable from
# the saas ontology's churn metric while still scoring 0.7 against the
# bare "churn" token (multi-word partial-match path).
KPI_LABEL = "churn_rate"
KPI_FORMULA = "cancelled_customers / total_customers"
KPI_UNIT = "ratio"

# Domain we register. Not in the saas pack templates; we add it as a
# discoverable label so topic_extractor can surface it at catalog walk
# time.
RETENTION_DOMAIN_NAME = "retention"
# Stable UUID per tenant — derived from tenant slug for replay parity.
RETENTION_DOMAIN_NAMESPACE = uuid5(
    NAMESPACE_DNS, "wormbase.tenant.retention-domain",
)

# Decisions seeded for retention. Two records, both attributable.
DECISION_TEXTS: tuple[str, ...] = (
    "Moved Europe activation experiment to control on 2026-02-15 — "
    "retention curves diverged from expectation.",
    "Increased onboarding email cadence from 3 to 5 touches over the "
    "first week to lift D7 retention.",
)

PROCESS_NAME = "customer_recovery_flow"
PROCESS_DOMAIN = "retention"

# Data-product source_hashes are pinned so replay tests hash-stable.
# These are derived deterministically from the artifact content below.
DATA_PRODUCT_NAME = "q3_churn_cohort"
DATA_PRODUCT_KIND = "report"
DATA_PRODUCT_HTML = (
    "<html><body><h1>Q3 Churn Cohort</h1>"
    "<p>Cohort: customers acquired Q1 2026, observed through Q3 2026.</p>"
    "<table><tr><th>Cohort</th><th>D30</th><th>D60</th><th>D90</th></tr>"
    "<tr><td>Q1 2026</td><td>0.94</td><td>0.87</td><td>0.79</td></tr>"
    "</table></body></html>"
)


def _stable_source_hashes() -> list[str]:
    """Pinned source_hashes for the data product — hash-stable across runs."""
    seeds = (
        b"wormbase.seed_rich.q3_churn_cohort.source.0",
        b"wormbase.seed_rich.q3_churn_cohort.source.1",
    )
    return [hashlib.sha256(s).hexdigest() for s in seeds]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class SeedRichReport:
    """Outcome of a ``seed_rich`` call."""

    tenant: str
    carol_person_id: UUID
    retention_domain_id: UUID
    kpi_id: UUID | None = None
    decision_ids: list[UUID] = field(default_factory=list)
    process_id: UUID | None = None
    data_product_id: UUID | None = None
    domain_role_granted: bool = False
    resource_role_granted: bool = False
    domain_registered: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant": self.tenant,
            "carol_person_id": str(self.carol_person_id),
            "retention_domain_id": str(self.retention_domain_id),
            "kpi_id": str(self.kpi_id) if self.kpi_id else None,
            "decision_ids": [str(d) for d in self.decision_ids],
            "process_id": str(self.process_id) if self.process_id else None,
            "data_product_id": (
                str(self.data_product_id) if self.data_product_id else None
            ),
            "domain_role_granted": self.domain_role_granted,
            "resource_role_granted": self.resource_role_granted,
            "domain_registered": self.domain_registered,
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def seed_rich(
    *,
    tenant: str,
    carol_person_id: UUID,
    dashboard_api_base: str,
    api_token: str,
    ledger: Ledger | InMemoryLedger | None = None,
    company_id: UUID | None = None,
    granted_by: UUID | None = None,
    http_client: httpx.AsyncClient | None = None,
    timeout_s: float = 15.0,
) -> SeedRichReport:
    """Drive the rich-seed enrichment via worm-core's HTTP write API.

    Parameters
    ----------
    tenant:
        Tenant slug (sent as ``X-Tenant-Slug`` header).
    carol_person_id:
        Carol's Person UUID — typically the index-2 entry from
        ``seed_personas``'s returned ``person_ids`` list.
    dashboard_api_base:
        Worm-core HTTP write API base URL (e.g. ``http://worm-core:8910``).
    api_token:
        Bearer token (``WORMBASE_LEDGER_API_TOKEN``).
    ledger:
        Optional ledger handle for the one direct write
        (``emit_domain_registered`` — no HTTP endpoint exists for it).
        When ``None`` the domain registration step is skipped (and the
        topic_extractor catalog walk will not surface "retention" as a
        domain entry, but the KPI / role grants still land).
    company_id:
        Tenant uuid (matches ``tenant_to_uuid(tenant)``). Required when
        ``ledger`` is set.
    granted_by:
        Admin Person attribution for role grants. Defaults to a
        synthetic seed admin id keyed on the tenant slug (mirrors the
        seed_personas convention).
    http_client / timeout_s:
        Wired through for tests (``MockTransport``).
    """
    if not tenant:
        raise ValueError("tenant is required")
    if not api_token:
        raise ValueError("api_token is required (worm-core bearer auth)")
    if not dashboard_api_base:
        raise ValueError("dashboard_api_base is required")
    if ledger is not None and company_id is None:
        raise ValueError("company_id is required when ledger is supplied")

    if granted_by is None:
        granted_by = _synthetic_admin_id(tenant)

    base = dashboard_api_base.rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_token}",
        "X-Tenant-Slug": tenant,
        "Content-Type": "application/json",
    }

    retention_domain_id = retention_domain_uuid_for_tenant(tenant)
    report = SeedRichReport(
        tenant=tenant,
        carol_person_id=carol_person_id,
        retention_domain_id=retention_domain_id,
    )

    # Step 0 — register the retention domain. Direct ledger write:
    # there is no HTTP endpoint for ``emit_domain_registered`` in the
    # production surface (CompanyWarmup is the only writer), so we
    # mirror its shape here. Skipped when no ledger is supplied; the
    # rest of the rich seed continues regardless.
    if ledger is not None and company_id is not None:
        await _register_retention_domain(ledger, company_id, retention_domain_id)
        report.domain_registered = True

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=timeout_s)
    try:
        # Step 1 — propose KPI.
        kpi_resp = await client.post(
            f"{base}/api/v1/kpis/propose",
            headers=headers,
            json={
                "label": KPI_LABEL,
                "formula": KPI_FORMULA,
                "unit": KPI_UNIT,
                "owner_position": "cfo",
                "proposed_by": "sim-harness.seed_rich",
            },
        )
        if kpi_resp.status_code >= 400:
            raise RuntimeError(
                f"propose_kpi {KPI_LABEL!r} returned "
                f"HTTP {kpi_resp.status_code}: {kpi_resp.text}"
            )
        kpi_id = UUID(kpi_resp.json()["kpi_id"])
        report.kpi_id = kpi_id

        # Step 2 — grant Carol resource.maintainer on the KPI.
        grant_resource_resp = await client.post(
            f"{base}/api/v1/people/{carol_person_id}/roles",
            headers=headers,
            json={
                "facet": "resource",
                "role": "maintainer",
                "scope_id": str(kpi_id),
                "scope_type": "kpi",
                "granted_by": str(granted_by),
            },
        )
        if grant_resource_resp.status_code >= 400:
            raise RuntimeError(
                f"grant resource.maintainer on KPI {kpi_id} returned "
                f"HTTP {grant_resource_resp.status_code}: "
                f"{grant_resource_resp.text}"
            )
        report.resource_role_granted = True

        # Step 3 — grant Carol domain.owner on retention domain.
        grant_domain_resp = await client.post(
            f"{base}/api/v1/people/{carol_person_id}/roles",
            headers=headers,
            json={
                "facet": "domain",
                "role": "owner",
                "scope_id": str(retention_domain_id),
                "granted_by": str(granted_by),
            },
        )
        if grant_domain_resp.status_code >= 400:
            raise RuntimeError(
                f"grant domain.owner on retention "
                f"({retention_domain_id}) returned "
                f"HTTP {grant_domain_resp.status_code}: "
                f"{grant_domain_resp.text}"
            )
        report.domain_role_granted = True

        # Step 4 — record 2 decisions tagged retention.
        for text in DECISION_TEXTS:
            decision_resp = await client.post(
                f"{base}/api/v1/decisions",
                headers=headers,
                json={
                    "decision_text": text,
                    "channel_id": "C_GROWTH",
                    "decided_by_persons": [str(carol_person_id)],
                    "evidence_message_ids": [],
                    "confidence": 0.95,
                    "proposed_by": "sim-harness.seed_rich",
                },
            )
            if decision_resp.status_code >= 400:
                raise RuntimeError(
                    f"record_decision returned HTTP "
                    f"{decision_resp.status_code}: {decision_resp.text}"
                )
            report.decision_ids.append(UUID(decision_resp.json()["decision_id"]))

        # Step 5 — propose process map customer_recovery_flow.
        process_resp = await client.post(
            f"{base}/api/v1/processes",
            headers=headers,
            json={
                "process_name": PROCESS_NAME,
                "domain": PROCESS_DOMAIN,
                "confidence": 0.9,
                "proposed_by": "sim-harness.seed_rich",
                "steps": [
                    {
                        "order": 1,
                        "actor": "Alice",
                        "action": "detect at-risk cohort via churn dashboard",
                        "source_message_id": "",
                    },
                    {
                        "order": 2,
                        "actor": "Carol",
                        "action": "approve recovery offer",
                        "source_message_id": "",
                    },
                    {
                        "order": 3,
                        "actor": "Bob",
                        "action": "send recovery campaign to cohort",
                        "source_message_id": "",
                    },
                ],
            },
        )
        if process_resp.status_code >= 400:
            raise RuntimeError(
                f"propose_process_map {PROCESS_NAME!r} returned "
                f"HTTP {process_resp.status_code}: {process_resp.text}"
            )
        report.process_id = UUID(process_resp.json()["process_id"])

        # Step 6 — propose + generate data product q3_churn_cohort with
        # pinned source_hashes. We pass the contents inline; the API
        # stores the artifact and returns the data_product_id. Source
        # hashes are pinned in the canonical content above so replay
        # tests stay deterministic regardless of upstream lake state.
        contents_b64 = base64.b64encode(DATA_PRODUCT_HTML.encode("utf-8")).decode(
            "ascii",
        )
        dp_resp = await client.post(
            f"{base}/api/v1/data-products",
            headers=headers,
            json={
                "name": DATA_PRODUCT_NAME,
                "kind": DATA_PRODUCT_KIND,
                "requested_by_person_id": str(carol_person_id),
                "sources_required": [],
                "domain_id": str(retention_domain_id),
                "parameters": {
                    "cohort": "Q1 2026",
                    "horizon_days": 90,
                    "source_hashes": _stable_source_hashes(),
                },
                "contents_bytes_b64": contents_b64,
                "contents_ext": "html",
            },
        )
        if dp_resp.status_code >= 400:
            raise RuntimeError(
                f"propose+generate data_product {DATA_PRODUCT_NAME!r} "
                f"returned HTTP {dp_resp.status_code}: {dp_resp.text}"
            )
        report.data_product_id = UUID(dp_resp.json()["data_product_id"])

        logger.info(
            "rich seed complete: tenant=%s kpi=%s decisions=%d process=%s "
            "data_product=%s domain=%s carol=%s",
            tenant, report.kpi_id, len(report.decision_ids),
            report.process_id, report.data_product_id,
            report.retention_domain_id, carol_person_id,
        )
        return report
    finally:
        if owns_client:
            await client.aclose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def retention_domain_uuid_for_tenant(tenant: str) -> UUID:
    """Stable UUID5 per-tenant for the synthetic retention domain.

    Same tenant always derives the same UUID so the catalog walk and
    role-grant lookups agree across the full seed → replay cycle.
    """
    return uuid5(RETENTION_DOMAIN_NAMESPACE, tenant)


def _synthetic_admin_id(tenant: str) -> UUID:
    """Mirror ``seed_personas._synthetic_admin_id`` so role grants get
    a stable attribution that matches the persona-confirm audit trail.
    """
    return uuid5(NAMESPACE_DNS, f"wormbase.seed_admin.{tenant}")


async def _register_retention_domain(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    retention_domain_id: UUID,
) -> None:
    """Write a synthetic ``emit_domain_registered`` PEVR cycle.

    There is no HTTP endpoint for domain registration — production
    domains land via ``CompanyWarmup`` from the saas/marketplace/fintech
    domain templates. The "retention" domain is not in any of those
    packs, so we add it here as a focused-Beat-9 enabler.

    The shape mirrors ``CompanyWarmup._register_domain``: same tool name,
    same arg keys, same target_kind. The catalog walk's
    ``emit_domain_role_assigned`` reader pairs with this entry to
    surface "retention" in the topic_extractor catalog.

    Idempotent over the canonical (id, name) pair — re-runs produce a
    second entry with identical args, which the projection collapses
    via last-write-wins. We do not check existence first because the
    caller (``seed_rich``) is invoked in a controlled context.
    """
    args = {
        "id": str(retention_domain_id),
        "name": RETENTION_DOMAIN_NAME,
        "default_classification": "internal",
        "description": (
            "Customer retention, churn, account health — synthetic "
            "domain seeded by sim-harness for Beat-9 standalone replay."
        ),
        "owner_person_id": None,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "memory_written",
            "ref_id": str(retention_domain_id),
            "reason": "rich-seed retention domain registration",
            "proposed_by": "sim-harness.seed_rich",
        },
        execute_fn=lambda a=args: {
            "tool": "emit_domain_registered",
            "args": a,
            "result_ref": str(retention_domain_id),
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "domain_valid", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "retention domain seeded for Beat-9",
        },
        quadrant="active_deterministic",
    )


__all__ = [
    "DATA_PRODUCT_NAME",
    "DECISION_TEXTS",
    "KPI_LABEL",
    "PROCESS_NAME",
    "RETENTION_DOMAIN_NAME",
    "SeedRichReport",
    "retention_domain_uuid_for_tenant",
    "seed_rich",
]
