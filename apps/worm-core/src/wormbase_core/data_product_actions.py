"""High-level data-product + notebook write actions for the worm-core HTTP API.

Mirrors the ``write_actions`` module pattern (A3.5). Each function builds a
full PEVR cycle via ``ledger.write`` and delegates payload validation to
the canonical Pydantic models in ``wormbase_ledger.entries`` (Block F1).

The module is the single boundary between "Pydantic payload class" and
"hash-chained ledger entry sequence" for data-product / notebook writes
driven by the dashboard, the worm itself (KPI Q+A, autoresearch keep), and
the process_extractor (recurring questions).

Quadrants:

- Admin-driven generation / publish / archive: ``active_deterministic``
  (the dashboard is admin-driven and deterministic).
- Worm-driven autoresearch / KPI proposal: ``passive_probabilistic``
  (the worm publishes proactively from chatter signal).

Verify step convention: re-instantiate the payload class on the execute
args. If Pydantic raises (drift between API surface and canonical
payload), verify fails and the surrounding write_primitive transaction
rolls back. Mirrors A3.5.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID, uuid4

from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ledger.entries import (
    DataProductArchivedPayload,
    DataProductConsumedPayload,
    DataProductGeneratedPayload,
    DataProductProposedPayload,
    NotebookArchivedPayload,
    NotebookProposedPayload,
    NotebookPublishedPayload,
    NotebookRunPayload,
)
from wormbase_ledger.write_primitive import WriteResult


# Type alias — anything with the canonical async ``write`` surface works.
LedgerLike = Ledger | InMemoryLedger | Any


# ---------------------------------------------------------------------------
# PEVR helper (mirrors write_actions._pevr)
# ---------------------------------------------------------------------------


def _pevr(
    *,
    ledger: LedgerLike,
    company_id: UUID,
    target_kind: str,
    ref_id: UUID,
    reason: str,
    proposed_by: str,
    tool: str,
    args: dict[str, Any],
    result_ref: str,
    payload_cls: type,
    rationale: str,
    quadrant: str = "active_deterministic",
):
    """Build the four PEVR closures and return the awaitable from ``ledger.write``."""

    def _verify(_exec_payload: dict[str, Any]) -> dict[str, Any]:
        try:
            payload_cls(**args)
            return {
                "checks": [{"name": f"{tool}_payload_valid", "ok": True}],
                "passed": True,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "checks": [
                    {
                        "name": f"{tool}_payload_valid",
                        "ok": False,
                        "error": str(exc),
                    }
                ],
                "passed": False,
            }

    return ledger.write(
        company_id=company_id,
        propose={
            "target_kind": target_kind,
            "ref_id": str(ref_id),
            "reason": reason,
            "proposed_by": proposed_by,
        },
        execute_fn=lambda: {
            "tool": tool,
            "args": args,
            "result_ref": result_ref,
        },
        verify_fn=_verify,
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": rationale,
        },
        quadrant=quadrant,
    )


# ---------------------------------------------------------------------------
# Data product lifecycle
# ---------------------------------------------------------------------------


async def propose_data_product(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    data_product_id: UUID | None = None,
    name: str,
    kind: str,
    requested_by_person_id: UUID,
    sources_required: list[UUID],
    domain_id: UUID | None = None,
    parameters: dict[str, Any] | None = None,
    prompted_by_message_id: str | None = None,
    proposed_by: str = "worm",
    quadrant: str = "active_deterministic",
) -> tuple[UUID, WriteResult]:
    """Propose a new data product.

    Returns ``(data_product_id, WriteResult)``. ``data_product_id`` is
    generated if not supplied so the caller can chain proposal +
    generation in one orchestrator call.
    """
    dp_id = data_product_id or uuid4()
    payload = DataProductProposedPayload(
        data_product_id=dp_id,
        name=name,
        kind=kind,
        requested_by_person_id=requested_by_person_id,
        sources_required=list(sources_required),
        domain_id=domain_id,
        parameters=parameters or {},
        prompted_by_message_id=prompted_by_message_id,
    )
    args = payload.model_dump(mode="json", by_alias=True)

    result = await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="data_product_proposed",
        ref_id=dp_id,
        reason=f"propose data product {name!r}",
        proposed_by=proposed_by,
        tool=f"emit_{DataProductProposedPayload.kind}",
        args=args,
        result_ref=str(dp_id),
        payload_cls=DataProductProposedPayload,
        rationale="data product proposed",
        quadrant=quadrant,
    )
    return dp_id, result


async def generate_data_product(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    data_product_id: UUID,
    contents_uri: str,
    content_hash: str,
    kind: str,
    source_hashes: list[str],
    duration_ms: int,
    generated_by: str = "worm",
    quadrant: str = "active_deterministic",
) -> WriteResult:
    """Emit data_product_generated for a previously-proposed artifact."""
    payload = DataProductGeneratedPayload(
        data_product_id=data_product_id,
        contents_uri=contents_uri,
        content_hash=content_hash,
        kind=kind,
        source_hashes=list(source_hashes),
        generated_by=generated_by,
        duration_ms=duration_ms,
    )
    args = payload.model_dump(mode="json", by_alias=True)

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="data_product_generated",
        ref_id=data_product_id,
        reason=f"generate data product {data_product_id}",
        proposed_by=generated_by,
        tool=f"emit_{DataProductGeneratedPayload.kind}",
        args=args,
        result_ref=str(data_product_id),
        payload_cls=DataProductGeneratedPayload,
        rationale="data product generated",
        quadrant=quadrant,
    )


async def consume_data_product(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    data_product_id: UUID,
    consumed_by_person_id: UUID,
    surface: str,
    channel: str | None = None,
) -> WriteResult:
    """Record a data-product consumption (view / share / export)."""
    payload = DataProductConsumedPayload(
        data_product_id=data_product_id,
        consumed_by_person_id=consumed_by_person_id,
        surface=surface,
        channel=channel,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="data_product_consumed",
        ref_id=data_product_id,
        reason=f"consume data product {data_product_id} via {surface}",
        proposed_by=str(consumed_by_person_id),
        tool=f"emit_{DataProductConsumedPayload.kind}",
        args=args,
        result_ref=str(data_product_id),
        payload_cls=DataProductConsumedPayload,
        rationale="data product consumed",
    )


async def archive_data_product(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    data_product_id: UUID,
    archived_by: UUID,
    reason: str,
) -> WriteResult:
    """Archive a data product (admin retired)."""
    payload = DataProductArchivedPayload(
        data_product_id=data_product_id,
        archived_by=archived_by,
        reason=reason,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="data_product_archived",
        ref_id=data_product_id,
        reason=f"archive data product {data_product_id}: {reason}",
        proposed_by=str(archived_by),
        tool=f"emit_{DataProductArchivedPayload.kind}",
        args=args,
        result_ref=str(data_product_id),
        payload_cls=DataProductArchivedPayload,
        rationale="data product archived",
    )


# ---------------------------------------------------------------------------
# Notebook lifecycle
# ---------------------------------------------------------------------------


async def propose_notebook(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    notebook_id: UUID | None = None,
    name: str,
    cells: list[dict[str, Any]],
    kernel: str,
    proposed_by_person_id: UUID,
    domain_id: UUID | None = None,
    quadrant: str = "active_deterministic",
) -> tuple[UUID, WriteResult]:
    """Propose a new notebook. Returns ``(notebook_id, WriteResult)``."""
    nb_id = notebook_id or uuid4()
    payload = NotebookProposedPayload(
        notebook_id=nb_id,
        name=name,
        cells=list(cells),
        kernel=kernel,
        proposed_by_person_id=proposed_by_person_id,
        domain_id=domain_id,
    )
    args = payload.model_dump(mode="json")

    result = await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="notebook_proposed",
        ref_id=nb_id,
        reason=f"propose notebook {name!r}",
        proposed_by=str(proposed_by_person_id),
        tool=f"emit_{NotebookProposedPayload.kind}",
        args=args,
        result_ref=str(nb_id),
        payload_cls=NotebookProposedPayload,
        rationale="notebook proposed",
        quadrant=quadrant,
    )
    return nb_id, result


async def run_notebook(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    notebook_id: UUID,
    run_id: UUID | None = None,
    cell_outputs: list[dict[str, Any]],
    cell_hashes: list[str],
    duration_ms: int,
    kernel_state_hash: str,
    status: str,
    run_by: str = "worm",
    quadrant: str = "active_deterministic",
) -> tuple[UUID, WriteResult]:
    """Record one notebook run. Returns ``(run_id, WriteResult)``."""
    rid = run_id or uuid4()
    payload = NotebookRunPayload(
        notebook_id=notebook_id,
        run_id=rid,
        cell_outputs=list(cell_outputs),
        cell_hashes=list(cell_hashes),
        duration_ms=duration_ms,
        kernel_state_hash=kernel_state_hash,
        status=status,
        run_by=run_by,
    )
    args = payload.model_dump(mode="json")

    result = await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="notebook_run",
        ref_id=notebook_id,
        reason=f"run notebook {notebook_id} ({status})",
        proposed_by=run_by,
        tool=f"emit_{NotebookRunPayload.kind}",
        args=args,
        result_ref=str(rid),
        payload_cls=NotebookRunPayload,
        rationale="notebook run",
        quadrant=quadrant,
    )
    return rid, result


async def publish_notebook(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    notebook_id: UUID,
    run_id: UUID,
    owner_person_id: UUID,
    version: str,
    published_by: UUID,
    domain_id: UUID | None = None,
) -> WriteResult:
    """Promote a run to a canonical published version."""
    payload = NotebookPublishedPayload(
        notebook_id=notebook_id,
        run_id=run_id,
        owner_person_id=owner_person_id,
        domain_id=domain_id,
        version=version,
        published_by=published_by,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="notebook_published",
        ref_id=notebook_id,
        reason=f"publish notebook {notebook_id} v{version}",
        proposed_by=str(published_by),
        tool=f"emit_{NotebookPublishedPayload.kind}",
        args=args,
        result_ref=str(notebook_id),
        payload_cls=NotebookPublishedPayload,
        rationale="notebook published",
    )


async def archive_notebook(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    notebook_id: UUID,
    archived_by: UUID,
    reason: str,
) -> WriteResult:
    """Archive a notebook (admin retired)."""
    payload = NotebookArchivedPayload(
        notebook_id=notebook_id,
        archived_by=archived_by,
        reason=reason,
    )
    args = payload.model_dump(mode="json")

    return await _pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="notebook_archived",
        ref_id=notebook_id,
        reason=f"archive notebook {notebook_id}: {reason}",
        proposed_by=str(archived_by),
        tool=f"emit_{NotebookArchivedPayload.kind}",
        args=args,
        result_ref=str(notebook_id),
        payload_cls=NotebookArchivedPayload,
        rationale="notebook archived",
    )


# ---------------------------------------------------------------------------
# Replay + Sign orchestrators (W2.A8)
# ---------------------------------------------------------------------------


class ReplayMismatchError(RuntimeError):
    """Raised when a replay produces a content_hash that drifts from origin.

    The replay determinism guarantee is the load-bearing invariant of the
    autoresearch reproducibility story (Karpathy autoresearch axis): given
    pinned source-hashes + the recorded contents, re-running the artifact
    must produce a byte-identical output.

    If this raises, either:
    - the original artifact bytes have drifted in the object store, or
    - the recorded source-hashes are insufficient to pin the result, or
    - the replay path itself is non-deterministic.

    All three are governance-relevant; the exception message carries both
    hashes so the dashboard can surface the divergence without re-fetch.
    """

    def __init__(self, *, expected: str, actual: str) -> None:
        super().__init__(
            f"replay content_hash mismatch: expected={expected} actual={actual}",
        )
        self.expected = expected
        self.actual = actual


class ReplayResult:
    """Return value of ``replay_data_product``.

    Carries the new ``run_id``, the recomputed ``content_hash``, the
    ``matches_original`` flag (always True if no exception raised), and
    the underlying ledger write entry ids for the new ``data_product_generated``
    cycle. The dashboard reads ``matches_original`` to surface the
    "✓ bit-identical content_hash" badge.
    """

    __slots__ = ("run_id", "content_hash", "expected_hash", "matches_original", "entry_ids")

    def __init__(
        self,
        *,
        run_id: UUID,
        content_hash: str,
        expected_hash: str,
        matches_original: bool,
        entry_ids: list[UUID],
    ) -> None:
        self.run_id = run_id
        self.content_hash = content_hash
        self.expected_hash = expected_hash
        self.matches_original = matches_original
        self.entry_ids = entry_ids


async def replay_data_product(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    data_product_id: UUID,
    original_content_hash: str,
    original_kind: str,
    source_hashes: list[str],
    contents_bytes: bytes,
    new_contents_uri: str,
    duration_ms: int = 0,
    generated_by: str = "replay",
    strict: bool = True,
) -> ReplayResult:
    """Replay a data product against pinned source-hashes.

    The orchestrator:

    1. Re-hashes ``contents_bytes`` (the canonical serialization the
       caller produced from the pinned source-hashes).
    2. Asserts the replay hash equals ``original_content_hash``. In
       strict mode (default), drift raises :class:`ReplayMismatchError`
       and **no ledger write occurs**. In non-strict mode the cycle is
       still written but the result carries ``matches_original=False``.
    3. Writes a new ``data_product_generated`` PEVR cycle pointing at
       the freshly-written artifact.

    The strict mode is the production path: the dashboard's "Replay"
    button needs the bit-identical guarantee or the badge is a lie.
    Non-strict is reserved for governance auditors who need to see
    drift-on-purpose (e.g. quarterly drift-tracking jobs).
    """
    new_hash = hashlib.sha256(contents_bytes).hexdigest()
    matches = new_hash == original_content_hash
    if strict and not matches:
        raise ReplayMismatchError(
            expected=original_content_hash, actual=new_hash,
        )

    new_run_id = uuid4()
    write_result = await generate_data_product(
        ledger,
        company_id,
        data_product_id=data_product_id,
        contents_uri=new_contents_uri,
        content_hash=new_hash,
        kind=original_kind,
        source_hashes=list(source_hashes),
        duration_ms=duration_ms,
        generated_by=generated_by,
    )

    return ReplayResult(
        run_id=new_run_id,
        content_hash=new_hash,
        expected_hash=original_content_hash,
        matches_original=matches,
        entry_ids=list(write_result.entry_ids),
    )


async def sign_notebook(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    notebook_id: UUID,
    run_id: UUID,
    owner_person_id: UUID,
    version: str,
    signed_by: UUID,
    domain_id: UUID | None = None,
) -> tuple[WriteResult, dict[str, Any]]:
    """Sign (publish) a notebook with a per-Person signature receipt.

    "Sign" is the governance-framed name for "publish" — the act of an
    admin Person attesting that this notebook run is canonical. Same
    underlying ledger entry (``emit_notebook_published``); the signature
    receipt is the deterministic projection of the Person + run + time
    that the dashboard surfaces back to the user.

    Returns ``(WriteResult, signature_receipt)`` so the HTTP handler
    can surface both the entry ids and the receipt the user sees on
    screen.

    The receipt's ``signature_hash`` is a sha256 of
    ``notebook_id|run_id|owner|version|signed_by`` — deterministic, so
    re-signing the same run by the same admin produces the same
    receipt. This is the on-screen "signed by ... · receipt: <hash>"
    badge.
    """
    write_result = await publish_notebook(
        ledger,
        company_id,
        notebook_id=notebook_id,
        run_id=run_id,
        owner_person_id=owner_person_id,
        version=version,
        published_by=signed_by,
        domain_id=domain_id,
    )

    receipt_seed = (
        f"{notebook_id}|{run_id}|{owner_person_id}|{version}|{signed_by}"
    ).encode("utf-8")
    signature_hash = hashlib.sha256(receipt_seed).hexdigest()

    receipt = {
        "notebook_id": str(notebook_id),
        "run_id": str(run_id),
        "owner_person_id": str(owner_person_id),
        "version": version,
        "signed_by": str(signed_by),
        "signature_hash": signature_hash,
        "entry_ids": [str(eid) for eid in write_result.entry_ids],
    }
    return write_result, receipt


__all__ = [
    "ReplayMismatchError",
    "ReplayResult",
    "archive_data_product",
    "archive_notebook",
    "consume_data_product",
    "generate_data_product",
    "propose_data_product",
    "propose_notebook",
    "publish_notebook",
    "replay_data_product",
    "run_notebook",
    "sign_notebook",
]
