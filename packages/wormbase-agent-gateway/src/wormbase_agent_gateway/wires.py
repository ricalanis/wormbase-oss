"""wire_agent_gateway_for_install — boot wire for the agent-gateway worm.

Per the Wave-2 spec (Task 8): registers the ``OutcomeToTemplatePromotion``
W5a Reactivity into the supplied ``ReactivityRegistry`` at install boot.
This becomes the 5th install-scope boot wire after Wave 1's cleanup-1a
reverted ``catalog-mirror`` off the boot path.

Sibling-wire pattern: kwarg-only, ``async def``, returns the list of
``Reactivity`` instances that were registered. Mirrors
``wire_research_for_install`` / ``wire_chat_for_install`` /
``wire_process_for_install`` so the worm-core orchestrator can call all
five in a single uniform style.

Production split (v1):

  * The Reactivity is registered at boot via this wire. Its dispatch is
    driven by the existing ``ReactivityRunner`` already started by
    worm-core; no extra runner is needed.
  * The MCP server is started by the worm-core boot orchestrator using
    its own DI (CatalogClient, BrokerExecutor, etc. live in the hub).
    The ``mcp_server`` kwarg here is reserved for future deployments
    that prefer to lift MCP startup into the wire; v1 keeps the
    one-loop / one-server hub responsibility intact.
  * ``credential_broker`` is also reserved for v1.1 — the Reactivity
    does not consume credentials in v1 (clustering is observation-only
    over the ledger). When ``OutcomeToTemplatePromotion`` learns to
    issue credentials during template promotion (v1.1), the broker
    will be wired into the Reactivity's ``execute_fn`` via this kwarg.

The wire never starts long-lived asyncio tasks of its own. Registration
is synchronous on the registry; the function is ``async`` only to match
the sibling wires' call-shape convention (some siblings perform async
lookups during registration; agent-gateway v1 does not).
"""
from __future__ import annotations

from typing import Any

from wormbase_reactivities.protocol import Reactivity

from .credential_broker import CredentialBroker
from .reactivities import make_agent_gateway_reactivities


async def wire_agent_gateway_for_install(
    *,
    install: Any,
    ledger: Any,
    reactivity_registry: Any,
    credential_broker: CredentialBroker | None = None,
    mcp_server: Any | None = None,
    subscription_dispatcher_deps: Any | None = None,
    projection_reader: Any | None = None,
) -> list[Reactivity]:
    """Register the agent-gateway Reactivities for this Install.

    Args:
        install: duck-typed in v1 (no formal Install dataclass
            requirement here — same posture as ``wire_research_for_install``
            and ``wire_identity_for_install``). Reserved for future
            platform-aware wiring (per-Install Reactivity instances).
        ledger: ledger handle (``Ledger`` or ``InMemoryLedger``). NOT
            consumed by registration directly — each Reactivity
            receives the ledger via ``ReactivityContext`` at dispatch
            time. Accepted for API-consistency with sibling wires that
            DO need a ledger handle at registration time (e.g. to
            construct lazy publishers).
        reactivity_registry: the W5a ``ReactivityRegistry`` to register
            into. Typed ``Any`` to keep this module's import surface
            light (matches the sibling wires' convention).
        credential_broker: optional credential broker. **Reserved for
            v1.1** — the v1 Reactivity does not issue credentials during
            promotion. Accepting the kwarg now keeps the wire signature
            stable when broker injection lands.
        mcp_server: optional MCP server handle. **Reserved for v1.1** —
            v1 keeps MCP startup in the worm-core boot orchestrator;
            promoting it into the wire is a future refactor.
        subscription_dispatcher_deps: optional v2.A Batch B opt-in. When
            provided, ``make_agent_gateway_reactivities`` includes the
            ``SubscriptionDispatcher`` Reactivity. Default ``None``
            preserves byte-identical pre-v2.A registration (5 Reactivities).

    Returns the list of registered ``Reactivity`` instances, in the
    fixed factory order. Mirrors the sibling-wires' return shape so
    the orchestrator's logging can enumerate registrations uniformly.
    """
    reactivities = make_agent_gateway_reactivities(
        subscription_dispatcher_deps=subscription_dispatcher_deps,
        projection_reader=projection_reader,
    )
    for r in reactivities:
        # Synchronous registration — confirmed in Wave 1 Task 5 against
        # ReactivityRegistry.register's signature.
        reactivity_registry.register(r)
    return list(reactivities)


__all__ = [
    "wire_agent_gateway_for_install",
]
