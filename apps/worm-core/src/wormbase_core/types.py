"""Shared types reused across worm-core modules.

These models are intentionally narrow: anything that crosses two modules
lives here so we don't end up with parallel definitions. The frozen
Pydantic configs make them safe to pass across coroutine boundaries.
"""

from __future__ import annotations

from typing import NewType

from pydantic import BaseModel, ConfigDict

from wormbase_governance.types import (  # noqa: F401
    GateDecision,
    PIIGateResult,
)

CorrelationId = NewType("CorrelationId", str)


class RampState(BaseModel):
    """Six-axis knowledge ramp. Each axis ∈ [0.0, 100.0].

    Note: the schema axis is named ``schema_axis`` (not ``schema``) to
    avoid shadowing Pydantic's ``BaseModel.schema()`` classmethod, which
    triggers a PydanticDeprecationWarning on every access. The wire/dict
    key remains ``"schema"`` (see :meth:`as_dict`) so existing ledger
    payloads, dashboard JSON, and fixtures stay untouched.
    """

    model_config = ConfigDict(
        extra="forbid", frozen=True, protected_namespaces=()
    )

    ontology: float = 0.0
    schema_axis: float = 0.0
    business_definitions: float = 0.0
    kpi_relational: float = 0.0
    conversational: float = 0.0
    operational: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "ontology": self.ontology,
            "schema": self.schema_axis,
            "business_definitions": self.business_definitions,
            "kpi_relational": self.kpi_relational,
            "conversational": self.conversational,
            "operational": self.operational,
        }


__all__ = ["CorrelationId", "GateDecision", "PIIGateResult", "RampState"]
