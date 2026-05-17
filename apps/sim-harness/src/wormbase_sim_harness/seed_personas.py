"""Seed the four canonical personas as Persons in the ledger via worm-core API.

E5 of ``docs/superpowers/plans/2026-04-26-production-dashboard.md``.

Replaces the demo seam where ``personas.yml`` was the canonical persona
roster the dashboard rendered. After E5:

* ``personas.yml`` is the **bot-account roster** only — display name,
  emoji, voice hint for the persona-bot post overrides on Slack.
* Canonical Person rows live in the ledger via ``emit_person_proposed``
  + ``emit_person_confirmed`` PEVR cycles, written through worm-core's
  HTTP API at ``POST /api/v1/people`` and ``POST /api/v1/people/{id}/
  confirm`` (Block A3.5).

This means the dashboard's ``/people`` roster, the demo's
auto-discovery ramp gauge, and the seed flow all read from the same
source of truth — the ledger projection. No YAML in production paths.

Public API:

* ``seed_personas(*, tenant, dashboard_api_base, api_token)`` — async
  function that POSTs Alice / Bob / Carol / Dave through the canonical
  PEVR cycle and returns the list of person_ids created. Idempotent
  modulo the underlying API: re-runs against an already-populated
  tenant return existing person_ids if the API surfaces them, or
  raise the API's error string otherwise.
* ``CANONICAL_PERSONAS`` — frozen tuple of persona descriptors
  (display_name, role, position, slack platform_user_id) used by the
  seed and by tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

logger = logging.getLogger("wormbase.sim.seed_personas")


# ---------------------------------------------------------------------------
# Canonical persona descriptors (matches personas.yml's 4-persona roster)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CanonicalPersona:
    """A canonical persona descriptor used to seed Person rows.

    The fields here cover everything worm-core's
    ``POST /api/v1/people`` requires (Block A3 contract). The
    bot-side ``display_name`` / ``icon_emoji`` / ``voice_hint``
    continue to live in ``personas.yml`` because Slack's
    ``chat.postMessage`` overrides need them at post time, not at
    propose time.
    """

    pid: str  # short id — alice / bob / carol / dave
    name: str
    email: str
    position: str
    # Stable Slack platform_user_id used by the seed history writer +
    # the dashboard's /people roster. Matches the value the lurker
    # would synthesize in production from a Slack workspace_member
    # response.
    platform: str
    platform_user_id: str


CANONICAL_PERSONAS: tuple[CanonicalPersona, ...] = (
    CanonicalPersona(
        pid="alice",
        name="Alice Chen",
        email="alice@baseworm.test",
        position="marketing_lead",
        platform="slack",
        platform_user_id="UALICE",
    ),
    CanonicalPersona(
        pid="bob",
        name="Bob Martin",
        email="bob@baseworm.test",
        position="data_engineer",
        platform="slack",
        platform_user_id="UBOB",
    ),
    CanonicalPersona(
        pid="carol",
        name="Carol Reyes",
        email="carol@baseworm.test",
        position="cfo",
        platform="slack",
        platform_user_id="UCAROL",
    ),
    CanonicalPersona(
        pid="dave",
        name="Dave Park",
        email="dave@baseworm.test",
        position="data_engineer",
        platform="slack",
        platform_user_id="UDAVE",
    ),
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


@dataclass
class SeedPersonasReport:
    """Outcome of a ``seed_personas`` call."""

    person_ids: list[UUID]
    proposed: int
    confirmed: int
    skipped: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "person_ids": [str(pid) for pid in self.person_ids],
            "proposed": self.proposed,
            "confirmed": self.confirmed,
            "skipped": self.skipped,
        }


async def seed_personas(
    *,
    tenant: str,
    dashboard_api_base: str,
    api_token: str,
    confirmed_by: UUID | None = None,
    http_client: httpx.AsyncClient | None = None,
    timeout_s: float = 10.0,
) -> SeedPersonasReport:
    """POST the four canonical personas to worm-core's /api/v1/people.

    Each persona is proposed via ``POST /api/v1/people`` (full PEVR
    cycle) and then confirmed via ``POST /api/v1/people/{id}/confirm``
    (a second PEVR cycle) so the resulting Person rows land in
    status="active" — same path the dashboard /people surface uses.

    Parameters
    ----------
    tenant:
        Tenant slug; sent as ``X-Tenant-Slug`` header.
    dashboard_api_base:
        Base URL of the worm-core write API (e.g.
        ``http://worm-core:8910``). The path ``/api/v1/people`` is
        appended.
    api_token:
        Bearer token; matched against ``WORMBASE_LEDGER_API_TOKEN`` on
        the worm-core side.
    confirmed_by:
        Admin UUID to attribute the confirmation. Defaults to a
        deterministic synthetic admin id derived from the tenant slug.
    http_client:
        Optional client; tests inject one for mock transport.
    timeout_s:
        Per-request timeout.
    """
    if not api_token:
        raise ValueError("api_token is required (worm-core bearer auth)")
    if not dashboard_api_base:
        raise ValueError("dashboard_api_base is required")
    if not tenant:
        raise ValueError("tenant is required")

    # The 'confirmed_by' is an audit-trail field; the demo seed has no
    # human admin yet (the worm hasn't been installed by a real person
    # in the seed path), so we synthesize a deterministic admin id
    # tagged to the tenant slug.
    if confirmed_by is None:
        confirmed_by = _synthetic_admin_id(tenant)

    base = dashboard_api_base.rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_token}",
        "X-Tenant-Slug": tenant,
        "Content-Type": "application/json",
    }

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=timeout_s)

    person_ids: list[UUID] = []
    proposed = 0
    confirmed = 0
    skipped = 0

    try:
        for persona in CANONICAL_PERSONAS:
            propose_body = {
                "name": persona.name,
                "email": persona.email,
                "platform": persona.platform,
                "platform_user_id": persona.platform_user_id,
                "position": persona.position,
                "proposed_by": "sim-harness.seed_personas",
            }
            try:
                propose_resp = await client.post(
                    f"{base}/api/v1/people",
                    headers=headers,
                    json=propose_body,
                )
            except httpx.HTTPError as exc:
                raise RuntimeError(
                    f"propose_person failed for {persona.pid}: {exc}",
                ) from exc

            if propose_resp.status_code >= 400:
                raise RuntimeError(
                    f"propose_person {persona.pid} returned "
                    f"HTTP {propose_resp.status_code}: {propose_resp.text}"
                )
            propose_data = propose_resp.json()
            person_id = UUID(propose_data["person_id"])
            person_ids.append(person_id)
            proposed += 1

            confirm_body = {"confirmed_by": str(confirmed_by)}
            try:
                confirm_resp = await client.post(
                    f"{base}/api/v1/people/{person_id}/confirm",
                    headers=headers,
                    json=confirm_body,
                )
            except httpx.HTTPError as exc:
                raise RuntimeError(
                    f"confirm_person failed for {persona.pid}: {exc}",
                ) from exc

            if confirm_resp.status_code >= 400:
                raise RuntimeError(
                    f"confirm_person {persona.pid} returned "
                    f"HTTP {confirm_resp.status_code}: {confirm_resp.text}"
                )
            confirmed += 1

        logger.info(
            "seeded %d personas as Person rows (proposed=%d confirmed=%d)",
            len(person_ids), proposed, confirmed,
        )
        return SeedPersonasReport(
            person_ids=person_ids,
            proposed=proposed,
            confirmed=confirmed,
            skipped=skipped,
        )
    finally:
        if owns_client:
            await client.aclose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _synthetic_admin_id(tenant: str) -> UUID:
    """Derive a stable synthetic admin UUID for the seed-path attribution.

    In production, real admin Persons confirm via the dashboard. The
    seed path has no admin yet (it's running before any real install),
    so we attribute the confirmation to a synthetic
    ``sim-harness.seed_personas`` admin keyed on the tenant slug. The
    same tenant always gets the same synthetic admin id, which keeps
    the audit trail readable.
    """
    from uuid import NAMESPACE_DNS, uuid5

    return uuid5(NAMESPACE_DNS, f"wormbase.seed_admin.{tenant}")


__all__ = [
    "CANONICAL_PERSONAS",
    "CanonicalPersona",
    "SeedPersonasReport",
    "seed_personas",
]
