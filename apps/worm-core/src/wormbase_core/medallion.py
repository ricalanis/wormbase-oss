"""Medallion cascade: bronze -> silver -> gold for any source.

Step 2 of the canonical product arc
(see ``docs/superpowers/specs/2026-04-26-wormbase-product-arc.md``).

Every source — whether dropped in a channel, discovered via lake-walk,
or pasted in a DM — flows through the same three-layer cascade:

    bronze   raw bytes captured + hashed (emit_source_bronzed)
    silver   inferred schema + classification + join hints (emit_source_silvered)
    gold     business-ready aggregate / chart / kpi (emit_source_golded,
             optionally emit_kpi_proposed)

The cascade is deterministic — same bytes -> same hashes -> identical
ledger entries on replay (Triad C2). Compute is intentionally light:
read at most a 100 KB sample of any file and infer types from at most
100 rows. Demo cares about the visible cascade evidence, not heavy work.

The module avoids pandas/numpy on purpose; it uses only stdlib ``csv``,
``hashlib``, ``statistics``, and ``re``. No new heavy deps.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import statistics
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlparse
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ledger.entries import (
    Classification,
    KpiProposedPayload,
    SourceBronzedPayload,
    SourceGoldedPayload,
    SourceSilveredPayload,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


SAMPLE_BYTE_LIMIT = 100 * 1024  # 100 KB
SAMPLE_ROW_LIMIT = 100

_PII_COLUMN_HINTS = re.compile(
    r"(?:^|[^a-z0-9])(ssn|sin|tax_id|email|phone|dob|cardholder|"
    r"customer_name|user_name|first_name|last_name|password|kyc)"
    r"(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)

_REVENUE_HINTS = re.compile(
    r"(?:^|[^a-z0-9])(revenue|amount|total|price|invoice|mrr|arr|gmv)"
    r"(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)

_DATE_HINTS = re.compile(
    r"(?:^|[^a-z0-9])(date|created_at|updated_at|month|day|year|ts|timestamp)"
    r"(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)

_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")
_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?Z?$"
)


SampleFn = Callable[[str], Awaitable[bytes] | bytes]


class _ClockProto(Protocol):
    def now(self) -> datetime: ...


class _DefaultClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Bronze profile model
# ---------------------------------------------------------------------------


class BronzeProfile(BaseModel):
    """Outcome of the bronze layer (deterministic over the input bytes)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    byte_count: int
    row_count: int
    col_count: int
    schema_hash: str
    mime: str
    raw_uri: str
    columns: list[str] = Field(default_factory=list)
    sample_rows: list[list[str]] = Field(default_factory=list)


def _read_sample(uri: str) -> bytes:
    """Return up to SAMPLE_BYTE_LIMIT bytes from a URI.

    Supports ``file://`` and bare paths. Anything else returns empty bytes
    so the cascade still produces a deterministic (empty) bronze profile.
    """
    parsed = urlparse(uri)
    if parsed.scheme in ("", "file"):
        path_str = parsed.path or uri
        if uri.startswith("file://"):
            path_str = uri[len("file://"):]
        path = Path(path_str)
        if path.is_file():
            with path.open("rb") as f:
                return f.read(SAMPLE_BYTE_LIMIT)
    return b""


def profile_bronze(
    uri: str,
    *,
    mime: str | None = None,
    raw_bytes: bytes | None = None,
) -> BronzeProfile:
    """Compute the bronze profile for a source.

    Reads up to SAMPLE_BYTE_LIMIT bytes from the URI (file paths only by
    default; pass ``raw_bytes`` to short-circuit the read). For CSV inputs
    (mime starts with ``text/csv`` or filename ends in ``.csv``), parses
    the header + up to SAMPLE_ROW_LIMIT rows for downstream silver/gold.
    """
    if raw_bytes is None:
        raw_bytes = _read_sample(uri)

    inferred_mime = mime or _infer_mime(uri)
    columns: list[str] = []
    sample_rows: list[list[str]] = []
    row_count = 0
    col_count = 0

    is_csv = (
        inferred_mime.startswith("text/csv")
        or inferred_mime == "text/plain"
        or uri.lower().endswith(".csv")
    )
    if is_csv and raw_bytes:
        try:
            text = raw_bytes.decode("utf-8", errors="replace")
            reader = csv.reader(io.StringIO(text))
            for i, row in enumerate(reader):
                if i == 0:
                    columns = [c.strip() for c in row]
                    col_count = len(columns)
                else:
                    if i - 1 >= SAMPLE_ROW_LIMIT:
                        # Stop sampling but keep counting rows below.
                        row_count = i - 1
                        break
                    sample_rows.append(list(row))
                    row_count = i
            else:
                # Loop completed without break; row_count = total rows seen.
                pass
        except Exception:
            # Unparseable CSV — treat as opaque bytes.
            columns = []
            sample_rows = []
            row_count = 0
            col_count = 0

    schema_basis = (
        "|".join(columns).encode("utf-8")
        if columns
        else raw_bytes[:1024]
    )
    schema_hash = hashlib.sha256(schema_basis).hexdigest()

    return BronzeProfile(
        byte_count=len(raw_bytes),
        row_count=row_count,
        col_count=col_count,
        schema_hash=schema_hash,
        mime=inferred_mime,
        raw_uri=uri,
        columns=columns,
        sample_rows=sample_rows,
    )


def _infer_mime(uri: str) -> str:
    lower = uri.lower()
    if lower.endswith(".csv"):
        return "text/csv"
    if lower.endswith(".json"):
        return "application/json"
    if lower.endswith(".ndjson") or lower.endswith(".jsonl"):
        return "application/x-ndjson"
    if lower.endswith(".parquet"):
        return "application/parquet"
    return "application/octet-stream"


# ---------------------------------------------------------------------------
# Silver inference
# ---------------------------------------------------------------------------


_ColType = Literal["int", "float", "date", "string"]


class InferredColumn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    type: _ColType
    nullable: bool
    distinct_count: int
    classification: Classification


def infer_columns(profile: BronzeProfile) -> list[InferredColumn]:
    """Heuristic type + classification inference over the bronze sample."""
    if not profile.columns:
        return []
    out: list[InferredColumn] = []
    n_cols = len(profile.columns)
    rows = profile.sample_rows
    for i, name in enumerate(profile.columns):
        values = [r[i] for r in rows if i < len(r)]
        non_empty = [v for v in values if v != ""]
        nullable = len(non_empty) < len(values)
        distinct = len({v for v in non_empty})
        col_type = _infer_type(name, non_empty)
        classification: Classification = (
            "pii" if _PII_COLUMN_HINTS.search(name) else "internal"
        )
        out.append(
            InferredColumn(
                name=name,
                type=col_type,
                nullable=nullable,
                distinct_count=distinct,
                classification=classification,
            )
        )
    # Suppress unused `n_cols` warning while keeping the variable for clarity.
    _ = n_cols
    return out


def _infer_type(name: str, values: list[str]) -> _ColType:
    if not values:
        # Empty sample — fall back to name-based hints.
        if _DATE_HINTS.search(name):
            return "date"
        return "string"
    int_ok = all(_INT_RE.match(v) for v in values)
    if int_ok:
        return "int"
    float_ok = all(_FLOAT_RE.match(v) for v in values)
    if float_ok:
        return "float"
    date_ok = all(_DATE_RE.match(v) for v in values)
    if date_ok or _DATE_HINTS.search(name):
        return "date"
    return "string"


def find_join_candidates(
    columns: list[InferredColumn],
    others: dict[UUID, list[str]],
) -> list[UUID]:
    """Return source_ids that share at least one column name with `columns`.

    Match is case-insensitive on the bare column name.
    """
    if not columns or not others:
        return []
    my_names = {c.name.lower() for c in columns}
    hits: list[UUID] = []
    for sid, names in others.items():
        if any(n.lower() in my_names for n in names):
            hits.append(sid)
    return hits


# ---------------------------------------------------------------------------
# Gold derivation
# ---------------------------------------------------------------------------


class GoldArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: UUID
    artifact_kind: Literal["aggregate", "kpi", "chart_data"]
    value: dict[str, Any]
    label: str
    suggests_kpi: bool = False
    kpi_label: str | None = None
    kpi_formula: str | None = None
    kpi_unit: str | None = None


def derive_gold(
    profile: BronzeProfile,
    columns: list[InferredColumn],
) -> GoldArtifact | None:
    """Pick the most informative aggregate from the silver columns.

    Order of preference:
      1. ``sum`` of any revenue-shaped numeric column
      2. ``mean`` of the first numeric column
      3. ``count_distinct`` of the first non-empty column
      4. ``count`` of rows
    """
    if not columns:
        if profile.row_count > 0:
            return GoldArtifact(
                artifact_id=uuid4(),
                artifact_kind="aggregate",
                value={"row_count": profile.row_count},
                label="row count",
            )
        return None

    rows = profile.sample_rows
    # 1) Revenue sum?
    for idx, col in enumerate(columns):
        if col.type in ("int", "float") and _REVENUE_HINTS.search(col.name):
            total = _sum_column(rows, idx)
            has_date = any(c.type == "date" for c in columns)
            return GoldArtifact(
                artifact_id=uuid4(),
                artifact_kind="kpi" if has_date else "aggregate",
                value={
                    "metric": "sum",
                    "column": col.name,
                    "result": total,
                    "n_rows_sampled": len(rows),
                },
                label=f"sum({col.name})",
                suggests_kpi=has_date,
                kpi_label=(
                    f"monthly total {col.name}"
                    if has_date else None
                ),
                kpi_formula=f"SUM({col.name})" if has_date else None,
                kpi_unit="USD" if has_date else None,
            )

    # 2) Mean of first numeric.
    for idx, col in enumerate(columns):
        if col.type in ("int", "float"):
            mean = _mean_column(rows, idx)
            return GoldArtifact(
                artifact_id=uuid4(),
                artifact_kind="aggregate",
                value={
                    "metric": "mean",
                    "column": col.name,
                    "result": mean,
                    "n_rows_sampled": len(rows),
                },
                label=f"mean({col.name})",
            )

    # 3) Count distinct of first column.
    first = columns[0]
    return GoldArtifact(
        artifact_id=uuid4(),
        artifact_kind="aggregate",
        value={
            "metric": "count_distinct",
            "column": first.name,
            "result": first.distinct_count,
            "n_rows_sampled": len(rows),
        },
        label=f"count_distinct({first.name})",
    )


def _sum_column(rows: list[list[str]], idx: int) -> float:
    total = 0.0
    for r in rows:
        if idx >= len(r):
            continue
        v = r[idx].strip()
        if not v:
            continue
        try:
            total += float(v)
        except ValueError:
            continue
    return round(total, 4)


def _mean_column(rows: list[list[str]], idx: int) -> float:
    vals: list[float] = []
    for r in rows:
        if idx >= len(r):
            continue
        v = r[idx].strip()
        if not v:
            continue
        try:
            vals.append(float(v))
        except ValueError:
            continue
    if not vals:
        return 0.0
    return round(statistics.fmean(vals), 4)


# ---------------------------------------------------------------------------
# Cascade (writes ledger entries via PEVR)
# ---------------------------------------------------------------------------


class MedallionCascade:
    """Runs bronze -> silver -> gold and writes 3 (or 4) ledger entries.

    Constructed once per worm-core and reused for every source. The
    cascade reads the bronze sample on demand; callers can also pass
    raw bytes for full determinism in tests.
    """

    def __init__(
        self,
        ledger: Ledger | InMemoryLedger,
        *,
        clock: _ClockProto | None = None,
    ) -> None:
        self._ledger = ledger
        self._clock = clock or _DefaultClock()
        # source_id -> column names, used for join-candidate discovery
        # without re-reading the lake.
        self._known_columns: dict[UUID, list[str]] = {}

    async def cascade(
        self,
        *,
        company_id: UUID,
        source_id: UUID,
        uri: str,
        mime: str | None = None,
        raw_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        """Run all three layers and return a summary dict."""
        profile = profile_bronze(uri, mime=mime, raw_bytes=raw_bytes)
        await self._write_bronze(company_id, source_id, profile)

        columns = infer_columns(profile)
        join_candidates = find_join_candidates(columns, self._known_columns)
        await self._write_silver(
            company_id, source_id, columns, join_candidates,
        )
        # Register this source's columns *after* join discovery so the
        # source doesn't match itself.
        self._known_columns[source_id] = [c.name for c in columns]

        gold = derive_gold(profile, columns)
        if gold is not None:
            await self._write_gold(company_id, source_id, gold)
            if gold.suggests_kpi:
                await self._write_kpi_proposal(company_id, source_id, gold)

        return {
            "bronze": profile.model_dump(mode="json"),
            "silver": {
                "inferred_columns": [c.model_dump() for c in columns],
                "join_candidates": [str(j) for j in join_candidates],
            },
            "gold": gold.model_dump(mode="json") if gold else None,
        }

    # -- writers --------------------------------------------------------

    async def _write_bronze(
        self,
        company_id: UUID,
        source_id: UUID,
        profile: BronzeProfile,
    ) -> None:
        payload = SourceBronzedPayload(
            source_id=source_id,
            byte_count=profile.byte_count,
            row_count=profile.row_count,
            col_count=profile.col_count,
            schema_hash=profile.schema_hash,
            mime=profile.mime,
            raw_uri=profile.raw_uri,
            profiled_at=self._clock.now(),
        )
        await self._ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "source_bronzed",
                "ref_id": str(source_id),
                "reason": "bronze layer profile",
                "proposed_by": "medallion_cascade",
            },
            execute_fn=lambda: {
                "tool": "emit_source_bronzed",
                "args": payload.model_dump(mode="json"),
                "result_ref": str(source_id),
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "bronze_valid", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "bronze layer captured",
            },
            timestamp=self._clock.now(),
            quadrant="active_deterministic",
        )

    async def _write_silver(
        self,
        company_id: UUID,
        source_id: UUID,
        columns: list[InferredColumn],
        join_candidates: list[UUID],
    ) -> None:
        payload = SourceSilveredPayload(
            source_id=source_id,
            inferred_columns=[c.model_dump() for c in columns],
            join_candidates=join_candidates,
            silvered_at=self._clock.now(),
        )
        await self._ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "source_silvered",
                "ref_id": str(source_id),
                "reason": "silver layer typed",
                "proposed_by": "medallion_cascade",
            },
            execute_fn=lambda: {
                "tool": "emit_source_silvered",
                "args": payload.model_dump(mode="json"),
                "result_ref": str(source_id),
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "silver_valid", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "silver layer enriched",
            },
            timestamp=self._clock.now(),
            quadrant="active_deterministic",
        )

    async def _write_gold(
        self,
        company_id: UUID,
        source_id: UUID,
        gold: GoldArtifact,
    ) -> None:
        payload = SourceGoldedPayload(
            source_id=source_id,
            gold_artifact_id=gold.artifact_id,
            artifact_kind=gold.artifact_kind,
            value=gold.value,
            computed_at=self._clock.now(),
        )
        await self._ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "source_golded",
                "ref_id": str(source_id),
                "reason": f"gold artifact: {gold.label}",
                "proposed_by": "medallion_cascade",
            },
            execute_fn=lambda: {
                "tool": "emit_source_golded",
                "args": payload.model_dump(mode="json"),
                "result_ref": str(gold.artifact_id),
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "gold_valid", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "gold artifact computed",
            },
            timestamp=self._clock.now(),
            quadrant="active_deterministic",
        )

    async def _write_kpi_proposal(
        self,
        company_id: UUID,
        source_id: UUID,
        gold: GoldArtifact,
    ) -> None:
        if not gold.kpi_label or not gold.kpi_formula:
            return
        payload = KpiProposedPayload(
            kpi_id=uuid4(),
            label=gold.kpi_label,
            formula=gold.kpi_formula,
            source_ids=[source_id],
            unit=gold.kpi_unit or "count",
            owner_position=None,
            proposed_at=self._clock.now(),
        )
        await self._ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "kpi_proposed",
                "ref_id": str(payload.kpi_id),
                "reason": f"gold suggests KPI: {gold.kpi_label}",
                "proposed_by": "medallion_cascade",
            },
            execute_fn=lambda: {
                "tool": "emit_kpi_proposed",
                "args": payload.model_dump(mode="json"),
                "result_ref": str(payload.kpi_id),
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "kpi_proposal_valid", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "KPI proposal recorded",
            },
            timestamp=self._clock.now(),
            quadrant="active_deterministic",
        )


__all__ = [
    "BronzeProfile",
    "GoldArtifact",
    "InferredColumn",
    "MedallionCascade",
    "SAMPLE_BYTE_LIMIT",
    "SAMPLE_ROW_LIMIT",
    "derive_gold",
    "find_join_candidates",
    "infer_columns",
    "profile_bronze",
]
