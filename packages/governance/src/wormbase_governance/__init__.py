"""wormbase_governance — 5 entities as ledger projections + gate implementations.

Public exports:

    Entities (Pydantic, frozen):
        Person, Domain, Resource, Policy
        Classification = Literal[...]

    Projections (pure ledger -> entity-list functions):
        project_people, project_domains, project_resources,
        project_classifications, project_policies

    Gates:
        pii_redaction_gate     (PIIGate alias)
        warmup_gate            (WarmupGate alias)
        interjection_gate      (InterjectionGate alias)
        knowledge_gate         (KnowledgeGate alias)

    Bootstrap:
        PolicyLoader, CompanyWarmup
"""

from __future__ import annotations

__version__ = "0.1.0"

from wormbase_governance.entities import (
    Classification,
    Domain,
    Person,
    Policy,
    Resource,
)
from wormbase_governance.gates import (
    InterjectionGate,
    KnowledgeGate,
    PIIGate,
    WarmupGate,
    interjection_gate,
    knowledge_gate,
    pii_redaction_gate,
    warmup_gate,
)
from wormbase_governance.policies import CompanyWarmup, PolicyLoader, WarmupReport
from wormbase_governance.policies.masked_column_refusal import (
    GATE_NAME as MASKED_COLUMN_GATE_NAME,
)
from wormbase_governance.policies.masked_column_refusal import (
    POLICY_NAME as MASKED_COLUMN_POLICY_NAME,
)
from wormbase_governance.policies.masked_column_refusal import (
    MaskedColumnQuery,
    MaskedColumnRefusalGate,
    MaskedColumnRefusalResult,
    masked_column_refusal_gate,
)
from wormbase_governance.projections import (
    project_classifications,
    project_domains,
    project_people,
    project_policies,
    project_resources,
)
from wormbase_governance.relevance import (
    RulesBasedRelevanceGate,
    Talkativeness,
)
from wormbase_governance.types import (
    GateDecision,
    InterjectionGateProtocol,
    PIIGateProtocol,
    PIIGateResult,
    PolicyGate,
)

__all__ = [
    "MASKED_COLUMN_GATE_NAME",
    "MASKED_COLUMN_POLICY_NAME",
    "Classification",
    "CompanyWarmup",
    "Domain",
    "GateDecision",
    "InterjectionGate",
    "InterjectionGateProtocol",
    "KnowledgeGate",
    "MaskedColumnQuery",
    "MaskedColumnRefusalGate",
    "MaskedColumnRefusalResult",
    "PIIGate",
    "PIIGateProtocol",
    "PIIGateResult",
    "Person",
    "Policy",
    "PolicyGate",
    "PolicyLoader",
    "Resource",
    "RulesBasedRelevanceGate",
    "Talkativeness",
    "WarmupGate",
    "WarmupReport",
    "__version__",
    "interjection_gate",
    "knowledge_gate",
    "masked_column_refusal_gate",
    "pii_redaction_gate",
    "project_classifications",
    "project_domains",
    "project_people",
    "project_policies",
    "project_resources",
    "warmup_gate",
]
