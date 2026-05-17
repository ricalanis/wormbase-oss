"""Five governance entities as Pydantic models (frozen / extra=forbid)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


Classification = Literal["public", "internal", "confidential", "pii", "regulated"]


class Person(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    name: str
    email: str | None = None
    role: Literal["admin", "owner", "member", "observer"] = "member"
    company_id: UUID
    active: bool = True


class Domain(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    default_classification: Classification = "internal"
    owner_person_id: UUID | None = None
    company_id: UUID
    description: str | None = None


class Resource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    type: Literal["source", "table", "model", "mart", "concept", "kpi", "policy"]
    identifier: str
    domain_id: str | None = None
    owner_person_id: UUID | None = None
    classification: Classification = "internal"
    company_id: UUID


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    name: str
    applies_to: dict[str, str]
    rule: str
    gate_impl: str
    company_id: UUID
    active: bool = True


__all__ = ["Classification", "Domain", "Person", "Policy", "Resource"]
