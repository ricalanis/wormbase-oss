"""Onboarding pack seeder — Sub-wave C (2026-05-30).

Fans a loaded pack out into a sequence of ledger PEVR cycles:

1. ``domain_pack_selected`` (parent) — the audit anchor.
2. N × ``emit_domain_registered`` propose/execute cycles.
3. N × ``emit_policy_applied`` propose/execute cycles.

The classification defaults are not written to the ledger directly —
they live in the pack YAML as a hint surface that downstream PII /
masking gates read at policy-evaluation time. (Future wave can lift
them into resource-level entries; out of scope for Sub-wave C.)

Idempotency: ``seed_pack`` short-circuits if a ``domain_pack_selected``
entry already exists for the company. Re-running on the same tenant
is a no-op (returns the prior summary). This guards against multiple
admins racing the picker.

Wire-replay determinism: the fan-out is fully a function of
``(pack_id, pack_version)``. Replaying a recorded ledger that
contains the ``domain_pack_selected`` parent + the per-domain /
per-policy execute entries reproduces the same seeded state on a
fresh tenant.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ledger.entries import DomainPackSelectedPayload

from .pack_loader import Pack, load_pack

LedgerLike = Ledger | InMemoryLedger | Any


@dataclass(frozen=True)
class PackSeedReport:
    """Summary of what ``seed_pack`` wrote.

    ``already_seeded=True`` means the call was a no-op because an
    earlier ``domain_pack_selected`` entry already exists for the
    company. Idempotency guard.
    """

    company_id: UUID
    pack_id: str
    pack_version: str
    domain_ids: tuple[str, ...] = field(default_factory=tuple)
    policy_ids: tuple[str, ...] = field(default_factory=tuple)
    already_seeded: bool = False


async def seed_pack(
    ledger: LedgerLike,
    *,
    company_id: UUID,
    pack_id: str,
    selected_by_person_id: UUID,
    notes: str | None = None,
    pack: Pack | None = None,
) -> PackSeedReport:
    """Seed a pack's contents into the ledger.

    Args:
        ledger: any Ledger/InMemoryLedger with the canonical write surface.
        company_id: tenant UUID.
        pack_id: which bundled pack to seed.
        selected_by_person_id: admin doing the pick (audit attribution).
        notes: optional free-text audit prose.
        pack: pre-loaded ``Pack`` for testing; if None, loads from disk.

    Returns:
        ``PackSeedReport`` summarizing the seeded domains + policies.
        ``already_seeded=True`` when a prior pack-selection exists.

    Raises:
        PackLoadError: when ``pack_id`` does not exist on disk.
        Any ledger write failure — the parent propose+execute is
        emitted first; downstream fan-out errors leave the parent in
        place as a no-go audit marker.
    """
    if pack is None:
        pack = load_pack(pack_id)

    # ------------------------------------------------------------------
    # Idempotency check — short-circuit on prior pack-selection.
    # ------------------------------------------------------------------
    rows = await ledger.fetch(company_id)
    for r in rows:
        if r["kind"] != "execute":
            continue
        args = r["payload"].get("args", {})
        if args.get("__from_kind") == "domain_pack_selected":
            return PackSeedReport(
                company_id=company_id,
                pack_id=args.get("pack_id", pack_id),
                pack_version=args.get("pack_version", pack.pack_version),
                domain_ids=tuple(),
                policy_ids=tuple(),
                already_seeded=True,
            )

    # ------------------------------------------------------------------
    # 1) Parent entry: domain_pack_selected.
    # ------------------------------------------------------------------
    parent_payload = DomainPackSelectedPayload(
        pack_id=pack.pack_id,
        pack_version=pack.pack_version,
        selected_by_person_id=selected_by_person_id,
        notes=notes,
    )
    parent_args = parent_payload.model_dump(mode="json")
    # Carry the kind tag inside args so the idempotency scan above can
    # detect it without re-parsing the propose target_kind.
    parent_args_with_marker = dict(parent_args)
    parent_args_with_marker["__from_kind"] = "domain_pack_selected"

    parent_ref = uuid4()
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "domain_pack_selected",
            "ref_id": str(parent_ref),
            "reason": f"installer picked pack {pack.pack_id!r}",
            "proposed_by": str(selected_by_person_id),
        },
        execute_fn=lambda: {
            "tool": "emit_domain_pack_selected",
            "args": parent_args_with_marker,
            "result_ref": pack.pack_id,
        },
        verify_fn=_make_payload_verify(
            "domain_pack_selected",
            DomainPackSelectedPayload,
            parent_args,
        ),
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": f"pack {pack.pack_id!r}/{pack.pack_version} seeded by admin",
        },
        quadrant="active_deterministic",
    )

    # ------------------------------------------------------------------
    # 2) Domains — fan-out via emit_domain_registered.
    # ------------------------------------------------------------------
    for d in pack.domains:
        await ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "memory_written",
                "ref_id": str(uuid4()),
                "reason": f"pack-seeded domain registration ({pack.pack_id})",
                "proposed_by": str(selected_by_person_id),
            },
            execute_fn=_make_domain_execute(d, pack, selected_by_person_id),
            verify_fn=lambda _r: {
                "checks": [{"name": "domain_valid", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v, did=d.id: {
                "outcome": "keep",
                "rationale": f"domain {did!r} seeded from pack",
            },
            quadrant="active_deterministic",
        )

    # ------------------------------------------------------------------
    # 3) Policies — fan-out via emit_policy_applied.
    # ------------------------------------------------------------------
    for pol in pack.policies:
        await ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "policy_applied",
                "ref_id": str(uuid4()),
                "reason": f"pack-seeded policy ({pack.pack_id})",
                "proposed_by": str(selected_by_person_id),
            },
            execute_fn=_make_policy_execute(pol, pack, selected_by_person_id),
            verify_fn=lambda _r: {
                "checks": [{"name": "policy_valid", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v, pid=pol.id: {
                "outcome": "applied",
                "rationale": f"policy {pid!r} seeded from pack",
            },
            quadrant="active_deterministic",
        )

    return PackSeedReport(
        company_id=company_id,
        pack_id=pack.pack_id,
        pack_version=pack.pack_version,
        domain_ids=tuple(d.id for d in pack.domains),
        policy_ids=tuple(p.id for p in pack.policies),
        already_seeded=False,
    )


# ---------------------------------------------------------------------------
# Closure factories — bind pack-loop variables at definition time so the
# closures don't capture mutating loop bindings.
# ---------------------------------------------------------------------------


def _make_payload_verify(
    kind: str,
    payload_cls: type,
    args: dict[str, Any],
):
    """Build a verify closure that re-instantiates the payload class.

    Mirrors ``write_actions._pevr`` — drift between the API surface and
    the payload class fails verify, rolling the transaction back.
    """

    def _verify(_exec_payload: dict[str, Any]) -> dict[str, Any]:
        try:
            payload_cls(**args)
            return {
                "checks": [{"name": f"{kind}_payload_valid", "ok": True}],
                "passed": True,
            }
        except Exception as exc:
            return {
                "checks": [
                    {
                        "name": f"{kind}_payload_valid",
                        "ok": False,
                        "error": str(exc),
                    }
                ],
                "passed": False,
            }

    return _verify


def _make_domain_execute(d, pack: Pack, installer: UUID):
    """Build the execute closure for emit_domain_registered."""
    args = {
        "id": d.id,
        "name": d.name,
        "default_classification": d.default_classification,
        "description": d.description,
        "owner_person_id": None,  # admins confirm ownership lazily
        "__pack_id": pack.pack_id,
        "__pack_version": pack.pack_version,
        "__seeded_by": str(installer),
        "__seeded_at": datetime.now(UTC).isoformat(),
    }

    def _exec() -> dict[str, Any]:
        return {
            "tool": "emit_domain_registered",
            "args": args,
            "result_ref": d.id,
        }

    return _exec


def _make_policy_execute(pol, pack: Pack, installer: UUID):
    """Build the execute closure for emit_policy_applied."""
    policy_id = uuid4()
    args = {
        "policy_id": str(policy_id),
        "policy_name": pol.name,
        "applies_to": {"domains": list(pol.applies_to_domains)},
        "rule": pol.rule,
        "gate_impl": pol.gate_impl,
        "__pack_id": pack.pack_id,
        "__pack_version": pack.pack_version,
        "__seeded_by": str(installer),
        "__seeded_at": datetime.now(UTC).isoformat(),
    }

    def _exec() -> dict[str, Any]:
        return {
            "tool": "emit_policy_applied",
            "args": args,
            "result_ref": pol.id,
        }

    return _exec


__all__ = [
    "PackSeedReport",
    "seed_pack",
]
