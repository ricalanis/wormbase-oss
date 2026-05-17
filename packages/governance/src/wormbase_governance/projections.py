"""Five governance projections (pure functions of the ledger).

Each projection iterates ledger rows in order and applies the relevant
event into a dict-keyed-by-id state, then returns sorted lists. Projection
functions accept either a list of pre-fetched rows OR an async ledger;
the dashboard (Phase 4) is expected to pass pre-fetched rows for speed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from wormbase_governance.entities import (
    Classification,
    Domain,
    Person,
    Policy,
    Resource,
)


def _filter_rows(
    rows: Iterable[Mapping[str, Any]],
    company_id: UUID,
    until_ts: datetime | None = None,
) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    for r in rows:
        if r.get("company_id") and r["company_id"] != company_id:
            continue
        if until_ts is not None and r["ts"] > until_ts:
            continue
        out.append(r)
    return out


def project_people(
    rows: Iterable[Mapping[str, Any]],
    company_id: UUID,
    until_ts: datetime | None = None,
) -> list[Person]:
    state: dict[str, dict[str, Any]] = {}
    for r in _filter_rows(rows, company_id, until_ts):
        if r["kind"] != "execute":
            continue
        args = r["payload"].get("args", {})
        tool = r["payload"].get("tool", "")
        if tool == "emit_person_registered":
            state[args["id"]] = {
                "id": UUID(args["id"]),
                "name": args.get("name", ""),
                "email": args.get("email"),
                "role": args.get("role", "member"),
                "company_id": company_id,
                "active": True,
            }
        elif tool == "emit_person_updated" and args["id"] in state:
            state[args["id"]].update({
                k: v for k, v in args.items()
                if k in {"name", "email", "role"}
            })
        elif tool == "emit_person_deactivated" and args["id"] in state:
            state[args["id"]]["active"] = False
    return [Person(**state[k]) for k in sorted(state.keys())]


def project_domains(
    rows: Iterable[Mapping[str, Any]],
    company_id: UUID,
    until_ts: datetime | None = None,
) -> list[Domain]:
    state: dict[str, dict[str, Any]] = {}
    for r in _filter_rows(rows, company_id, until_ts):
        if r["kind"] != "execute":
            continue
        args = r["payload"].get("args", {})
        tool = r["payload"].get("tool", "")
        if tool == "emit_domain_registered":
            state[args["id"]] = {
                "id": args["id"],
                "name": args.get("name", args["id"]),
                "default_classification": args.get(
                    "default_classification", "internal"
                ),
                "owner_person_id": (
                    UUID(args["owner_person_id"])
                    if args.get("owner_person_id") else None
                ),
                "company_id": company_id,
                "description": args.get("description"),
            }
        elif tool == "emit_domain_updated" and args["id"] in state:
            for k in ("name", "default_classification", "description"):
                if k in args:
                    state[args["id"]][k] = args[k]
            if "owner_person_id" in args:
                state[args["id"]]["owner_person_id"] = (
                    UUID(args["owner_person_id"])
                    if args["owner_person_id"] else None
                )
    return [Domain(**state[k]) for k in sorted(state.keys())]


def project_resources(
    rows: Iterable[Mapping[str, Any]],
    company_id: UUID,
    until_ts: datetime | None = None,
) -> list[Resource]:
    """Resources include sources (proposed/confirmed) and any explicit
    resource_registered events."""
    state: dict[str, dict[str, Any]] = {}
    for r in _filter_rows(rows, company_id, until_ts):
        if r["kind"] != "execute":
            continue
        args = r["payload"].get("args", {})
        tool = r["payload"].get("tool", "")
        if tool == "emit_source_proposed":
            sid = args["source_id"]
            state[sid] = {
                "id": UUID(sid),
                "type": "source",
                "identifier": args.get("uri", ""),
                "domain_id": None,
                "owner_person_id": None,
                "classification": args.get(
                    "suggested_classification", "internal"
                ),
                "company_id": company_id,
            }
        elif tool == "emit_source_confirmed" and args["source_id"] in state:
            s = state[args["source_id"]]
            if args.get("classification"):
                s["classification"] = args["classification"]
            if args.get("domain_id"):
                s["domain_id"] = args["domain_id"] if not _is_uuid_string(
                    args["domain_id"]
                ) else args["domain_id"]
            if args.get("confirmed_by_person"):
                s["owner_person_id"] = UUID(args["confirmed_by_person"])
        elif tool == "emit_resource_classified" and args.get("id") in state:
            state[args["id"]]["classification"] = args["classification"]
        elif tool == "emit_resource_registered":
            state[args["id"]] = {
                "id": UUID(args["id"]),
                "type": args.get("type", "table"),
                "identifier": args.get("identifier", ""),
                "domain_id": args.get("domain_id"),
                "owner_person_id": (
                    UUID(args["owner_person_id"])
                    if args.get("owner_person_id") else None
                ),
                "classification": args.get("classification", "internal"),
                "company_id": company_id,
            }
    out: list[Resource] = []
    for k in sorted(state.keys()):
        s = state[k]
        # Coerce domain_id to a string-id (Resource model expects string).
        out.append(Resource(**s))
    return out


def project_classifications(
    resources: list[Resource],
) -> dict[Classification, int]:
    counts: dict[Classification, int] = {
        "public": 0, "internal": 0, "confidential": 0, "pii": 0, "regulated": 0,
    }
    for r in resources:
        counts[r.classification] = counts.get(r.classification, 0) + 1
    return counts


def project_policies(
    rows: Iterable[Mapping[str, Any]],
    company_id: UUID,
    until_ts: datetime | None = None,
) -> list[Policy]:
    state: dict[str, dict[str, Any]] = {}
    for r in _filter_rows(rows, company_id, until_ts):
        if r["kind"] != "execute":
            continue
        args = r["payload"].get("args", {})
        tool = r["payload"].get("tool", "")
        if tool == "emit_policy_applied":
            pid = args.get("policy_id") or args.get("id")
            if pid is None:
                continue
            state[pid] = {
                "id": UUID(pid),
                "name": args.get("policy_name", args.get("name", "")),
                "applies_to": args.get("applies_to", {}),
                "rule": args.get("rule", ""),
                "gate_impl": args.get("gate_impl", ""),
                "company_id": company_id,
                "active": True,
            }
        elif tool == "emit_policy_retired":
            pid = args.get("policy_id") or args.get("id")
            if pid in state:
                state[pid]["active"] = False
    return [Policy(**state[k]) for k in sorted(state.keys()) if state[k]["active"]]


def _is_uuid_string(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    try:
        UUID(s)
        return True
    except ValueError:
        return False


__all__ = [
    "project_classifications",
    "project_domains",
    "project_people",
    "project_policies",
    "project_resources",
]
