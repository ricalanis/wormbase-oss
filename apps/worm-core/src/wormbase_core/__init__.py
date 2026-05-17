"""wormbase_core — the worm's brain.

Public API surfaces (consumed by P4 dashboard, P5 sim, P6 integration):

    Reactivity & contract
        ReactivityPipeline, DefaultInfrastructureTrigger,
        DefaultSemanticTrigger, RulesBasedRelevanceGate,
        ConversationContract

    Classifier
        OllamaCloudClassifier, StubClassifier, ClassifierResult

    Source flows
        SourceBuilder, build_full_sequence,
        DropAndProfileFlow, CredentialInDmFlow,
        MentionedInConversationFlow, DashboardFormFlow,
        KpiGapTriggeredFlow

    Gates
        PIIGate, WarmupGate, InterjectionGate, KnowledgeGate

    Ramp
        KnowledgeRamp, RampState

    Autoresearch
        Extracted to ``wormbase_research_loop`` (Wave C₁); the legacy
        in-process autoresearch shim was deleted with zero production
        callers.

    Lurker
        SlackLurker — concurrent SocketMode listener writing chat_received
"""

from __future__ import annotations

__version__ = "0.1.0"

from wormbase_core.types import (
    CorrelationId,
    GateDecision,
    PIIGateResult,
    RampState,
)

__all__ = [
    "CorrelationId",
    "GateDecision",
    "PIIGateResult",
    "RampState",
    "__version__",
]
