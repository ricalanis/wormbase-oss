# > AUTHORED 2026-05-03: shape mirrors C5 of the spike. Per-Install
# > scope. Registers Reactivities into the existing registry; returns
# > the Protocol-shaped resolver for hub-side DI.
"""Lifecycle factory — wire identity Reactivities for one Install.

Hub-side boot path (apps/worm-core/cli.py) calls this once per Install
record at startup. The function:

  1. Calls `make_identity_reactivities(install, member_lookup)` to get
     the list of Reactivities (one in v1).
  2. Registers each with the existing `ReactivityRegistry` at
     `initial_state="active"` (code-registered Reactivities are trusted
     per `ReactivityRegistry.register` docstring).
  3. Constructs a `_LedgerBackedIdentityResolver` bound to (ledger,
     company_id) and returns it.

The returned resolver is the public surface — DOWNSTREAM consumers
(StatementToOwnerReactivity, autoresearch_loop's team_loop_runner,
chat-worm, process-worm, research-worm in subsequent waves) take it via
DI. They never construct it themselves.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from wormbase_ledger import InMemoryLedger, Ledger

from wormbase_identity_tracker.factory import make_identity_reactivities
from wormbase_identity_tracker.protocols import IdentityResolver
from wormbase_identity_tracker.resolver import _LedgerBackedIdentityResolver
from wormbase_identity_tracker.types import MemberLookup
from wormbase_identity_tracker.whatsapp_discovery import (
    WhatsAppOrganicDiscoveryReactivity,
)


async def wire_identity_for_install(
    *,
    install: Any,  # duck-typed for v1 (see Block F header)
    member_lookup: MemberLookup,
    reactivity_registry: Any,  # ReactivityRegistry — typed Any to avoid
                               # importing it (light dep policy)
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
) -> IdentityResolver:
    """Register identity Reactivities + return the resolver Protocol impl.

    Per **C5** of the spike, scope is per-Install (NOT per-Source like
    lake-maintainer): an Install is one (tenant, channel-platform) pair,
    and Reactivities are company-scoped. One call per Install per boot.

    Returns the single production `IdentityResolver` impl for the
    hub-side caller to thread into downstream Reactivities via DI.
    """
    reactivities = make_identity_reactivities(
        install=install, member_lookup=member_lookup,
    )
    for reactivity in reactivities:
        reactivity_registry.register(reactivity)
    return _LedgerBackedIdentityResolver(
        ledger=ledger, company_id=company_id,
    )


async def wire_whatsapp_identity_for_install(
    *,
    install: Any,  # duck-typed: needs .id, .platform == "whatsapp"
    reactivity_registry: Any,  # ReactivityRegistry — typed Any per the
                               # light-dep policy used by sister wires.
) -> WhatsAppOrganicDiscoveryReactivity:
    """Register the WhatsApp organic-discovery Reactivity (Wave B2).

    Slack identity discovery (:func:`wire_identity_for_install`) uses a
    workspace-roster ``member_lookup`` callable — WhatsApp has no
    equivalent (:meth:`WhatsAppChannelAdapter.list_workspace_members`
    honestly returns ``[]``). This helper registers a parallel
    Reactivity that learns Persons organically from inbound chat.

    Designed to be called in addition to (NOT instead of)
    :func:`wire_identity_for_install` when the deployment has both a
    Slack and a WhatsApp Install. The two Reactivities co-exist:
    Slack's ``UnknownPlatformIdReactivity`` no-ops on WhatsApp jids
    because its Slack ``member_lookup`` returns None for them;
    WhatsApp's ``WhatsAppOrganicDiscoveryReactivity`` no-ops on Slack
    ids because of its inner platform filter.

    No resolver is returned — the hub wires identity-resolution once
    via :func:`wire_identity_for_install` and downstream consumers
    share that single resolver. This wire only adds the WhatsApp
    propose path.
    """
    if getattr(install, "platform", None) != "whatsapp":
        raise ValueError(
            "wire_whatsapp_identity_for_install requires "
            "install.platform == 'whatsapp'"
        )
    reactivity = WhatsAppOrganicDiscoveryReactivity()
    reactivity_registry.register(reactivity)
    return reactivity


__all__ = [
    "wire_identity_for_install",
    "wire_whatsapp_identity_for_install",
]
