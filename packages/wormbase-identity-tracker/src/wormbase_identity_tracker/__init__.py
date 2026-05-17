"""WormBase IdentityTracker — agentic identity resolution.

See `docs/superpowers/notes/2026-05-03-identity-worm-phase-0-spike.md`
for the architecture and the GO-WITH-CAVEATS design rationale.

Public surface (frozen after Wave A landing per C2):
"""
from __future__ import annotations

from wormbase_identity_tracker.factory import make_identity_reactivities
from wormbase_identity_tracker.lifecycle import (
    wire_identity_for_install,
    wire_whatsapp_identity_for_install,
)
from wormbase_identity_tracker.protocols import IdentityResolver
from wormbase_identity_tracker.reactivities import (
    LEGACY_REACTIVITY_ID,
    UnknownPlatformIdReactivity,
)
from wormbase_identity_tracker.types import (
    MemberLookup,
    Person,
    PersonHint,
    Position,
    ProposalRef,
    ResourceRole,
    TeamMembership,
)
from wormbase_identity_tracker.whatsapp_discovery import (
    WhatsAppOrganicDiscoveryReactivity,
)

__all__ = [
    "IdentityResolver",
    "LEGACY_REACTIVITY_ID",
    "MemberLookup",
    "Person",
    "PersonHint",
    "Position",
    "ProposalRef",
    "ResourceRole",
    "TeamMembership",
    "UnknownPlatformIdReactivity",
    "WhatsAppOrganicDiscoveryReactivity",
    "make_identity_reactivities",
    "wire_identity_for_install",
    "wire_whatsapp_identity_for_install",
]
