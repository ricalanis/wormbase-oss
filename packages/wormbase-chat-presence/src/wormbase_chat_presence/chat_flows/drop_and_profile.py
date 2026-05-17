"""DropAndProfileFlow — channel file_drop event → bronze cascade.

Lifted verbatim from apps/worm-core/src/wormbase_core/flows.py:111-198 in
Wave B. Behavior unchanged. Construction signature unchanged.
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any, Literal
from uuid import UUID

from wormbase_chat_presence.chat_flows._shared import (
    FileProfile,
    _BuilderHostingFlow,
)
from wormbase_core.source_builder import SourceBuilder, SourceProposal
from wormbase_core.types import CorrelationId
from wormbase_core.reactivity import InfraEvent


_ALLOWED_MIMETYPES = {
    "text/csv",
    "application/parquet",
    "application/json",
    "application/x-ndjson",
    "application/octet-stream",
}


# Underscore is a word char in Python regex, so "customers_ssn" matches as a
# single word. We use a permissive boundary that breaks on underscore too.
_PII_FILENAME_HINTS = re.compile(
    r"(?:^|[^a-z0-9])(ssn|sin|tax_id|customers?|users?|pii|email|phone|dob|"
    r"cardholder|kyc)(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)


def _is_uuid(s: str) -> bool:
    try:
        UUID(s)
        return True
    except ValueError:
        return False


class DropAndProfileFlow(_BuilderHostingFlow):
    """File-drop entry point. Emits a proposal, waits for confirmation, then connects+profiles."""

    def __init__(
        self,
        builder: SourceBuilder,
        classifier: Any,
        file_profiler: Callable[[str], Awaitable[FileProfile]] | None = None,
    ) -> None:
        self._builder = builder
        self._classifier = classifier
        self._profiler = file_profiler

    async def on_file_drop(
        self, event: InfraEvent
    ) -> CorrelationId | None:
        payload = event.payload or {}
        filename = payload.get("filename") or payload.get("name") or "unknown"
        mimetype = payload.get("mimetype") or "application/octet-stream"
        bytes_url = payload.get("bytes_url") or payload.get("url") or ""
        if mimetype not in _ALLOWED_MIMETYPES:
            return None  # caller should raise gate_fired separately

        # Use classifier to suggest a domain; default if low-conf.
        interp = await self._classifier.classify(filename, {"source": "file_drop"})
        domain = "general"
        for c in interp.concepts:
            if c:
                domain = c
                break
        classification: Literal["internal", "pii"] = "internal"
        if _PII_FILENAME_HINTS.search(filename):
            classification = "pii"

        proposal = SourceProposal(
            proposed_uri=bytes_url or f"file://{filename}",
            proposed_type="file",
            proposed_domain=domain,
            proposed_classification=classification,
            proposed_owner_person_id=(
                UUID(event.person_id) if event.person_id and _is_uuid(event.person_id)
                else None
            ),
            added_by_person_id=(
                UUID(event.person_id) if event.person_id and _is_uuid(event.person_id)
                else None
            ),
            added_via_flow="drop_and_profile",
            added_in_response_to=f"channel_msg:{event.message_id}",
            company_id=event.company_id,
        )
        return await self._builder.propose(proposal)

    async def on_confirmation(
        self,
        correlation_id: str,
        confirmer_person_id: UUID,
        domain_id: UUID,
        *,
        connection_ref: str | None = None,
    ) -> None:
        await self._builder.confirm(
            correlation_id, confirmer_person_id, domain_id, "internal"
        )
        ref = connection_ref or f"file-conn-{correlation_id[:8]}"
        await self._builder.connect(correlation_id, ref)
        if self._profiler is not None:
            prof = await self._profiler(ref)
            await self._builder.profile(
                correlation_id,
                row_count=prof.row_count,
                column_count=prof.column_count,
                schema_hash=prof.schema_hash,
                profile_ref=ref,
            )
        else:
            # No profiler registered for this connector kind: record a
            # "unprofiled" profile entry so the cascade still advances and
            # the source carries a Receipt. A profiler can be registered
            # later and a re-profile run via the source-builder API; the
            # ledger entry is auditable either way.
            await self._builder.profile(
                correlation_id,
                row_count=0,
                column_count=0,
                schema_hash="unprofiled",
                profile_ref=ref,
            )


__all__ = ["DropAndProfileFlow"]
