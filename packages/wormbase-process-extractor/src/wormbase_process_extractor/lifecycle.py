"""Lifecycle: register the four process-worm Reactivities with W5a.

Mirrors lake-maintainer's ``wire_maintenance_for_source`` shape
(``packages/lake-maintainer/src/wormbase_lake_maintainer/registry.py:54-79``)
exactly — call the factory, then ``register()`` each result with the
``ReactivityRegistry`` and return the list of ids for audit logging.

Scope difference from lake-maintainer (important):

* lake-maintainer wires **per Source** — every connector install adds
  four new Reactivities, one per source × maintenance-method.
* process-worm wires **per process boot** — the same four Reactivities
  serve every tenant. State is per-tenant **inside** each Reactivity
  (e.g. the system-map accumulator, recurring-question history),
  rekeyed by ``context.company_id`` at fire time. There is no
  per-tenant Reactivity instance to construct.

Consequence: ``wire_process_for_install`` is called **once at process
boot**, not on every tenant install. Calling it more than once on the
same registry is a no-op (the lifecycle catches W5a's ValueError on
duplicate registration and skips silently).
"""
from __future__ import annotations

import logging

from wormbase_process_extractor.factory import make_process_reactivities

logger = logging.getLogger(__name__)


def wire_process_for_install(
    *,
    registry: object,
    llm_client: object | None = None,
    topic_labeler: object | None = None,
) -> list[str]:
    """Register the four process-worm Reactivities. Idempotent.

    Called **once per process boot** (not per tenant install) — the
    same four Reactivity instances serve every tenant; state is
    per-tenant inside each instance, keyed on
    ``context.company_id``. This distinction matters because
    lake-maintainer's analogous ``wire_maintenance_for_source``
    is called once per Source and registers four fresh instances
    each time. Process-worm has no per-tenant instance.

    Idempotency: W5a's ``ReactivityRegistry.register`` raises
    ``ValueError`` on a duplicate id (see
    ``packages/reactivities/src/wormbase_reactivities/registry.py:170-173``).
    The lifecycle catches that error and skips silently so a second
    invocation on the same registry is a no-op rather than a crash —
    safe for restart-after-partial-init recovery.

    Args:
        registry: A W5a ``ReactivityRegistry`` (or a structural stub
            in tests). Only ``register(reactivity)`` is touched.
        llm_client: Optional injected LLM client. Accepted for
            symmetry with the factory; the current implementation does
            not thread it into Reactivity instances (resolution is
            lazy via ``context.extras``).

    Returns:
        Stable list of registered Reactivity ids in factory order
        (``["topic_synthesis", "recurring_question_process_mapper",
        "decision_record", "system_map_node"]``).
    """
    reactivities = make_process_reactivities(
        llm_client=llm_client,
        topic_labeler=topic_labeler,
    )
    ids: list[str] = []
    for reactivity in reactivities:
        try:
            registry.register(reactivity)  # type: ignore[attr-defined]
        except ValueError:
            # Duplicate id — already registered by a prior call. Per
            # the idempotency contract above, treat as a no-op.
            logger.debug(
                "process Reactivity %r already registered; skipping",
                reactivity.id,
            )
        ids.append(reactivity.id)
    return ids


__all__ = ["wire_process_for_install"]
