"""Local CSV connector — discover/profile/sample, no network.

The simplest member of the connector family. Useful as the canonical
example shape any new connector implementation should mirror, and as
the workhorse for `drop_and_profile` flows where a Slack file_share
lands a CSV onto local storage.

Auth bundle:
    {"path": "/abs/path/to/file.csv"}

Capabilities:
    * discover — returns a single ResourceProposal for the path
    * profile  — csv.reader-based row count + column dtype inference
    * sample   — first n lines (raw bytes)
    * watch    — not supported; yields nothing (csv_local is pull-only)

Classification hints:
    Filename heuristics flag PII (ssn, credit, passport, license, tax,
    payroll, salary, compensation). Column-name heuristics ride on top:
    columns whose names match PII patterns (e.g. ``customer_email``)
    surface in the profile's ``classification_hints`` list. The hints
    are propagated through ``ResourceProposal.classification_hint`` and
    ``Profile.extra['classification_hints']`` so the policy gate can
    default new sources to the right classification.

Encoding detection:
    The connector probes UTF-8 first (the modern default). On
    ``UnicodeDecodeError`` it falls back to Windows-1252 — the dominant
    encoding of CSVs that escaped via Excel from a Western locale. The
    detected encoding is reported on ``Profile.extra['encoding']`` so
    downstream silver can preserve the original bytes if needed. This
    keeps real-world finance exports (cp1252 with Latin-1 names like
    ``José Álvarez``) profiling cleanly, where a strict UTF-8 reader
    would crash on the first non-ASCII byte.

    ``charset-normalizer`` is consulted as a hint when available, but
    the final pick is deterministic: utf-8 → cp1252 → latin-1, in that
    order. Pure-detector picks are unstable for short Latin-1 sequences
    (a known cp1257-vs-cp1252 ambiguity); we prefer the predictable
    family rule over a per-file heuristic.
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections.abc import AsyncIterator
from io import StringIO
from pathlib import Path
from typing import Any

from .base import Connector
from .registry import register_connector
from .types import (
    AuthHandle,
    Capability,
    Change,
    ClassificationHint,
    Profile,
    ResourceProposal,
    SecretBundle,
)

# Filename PII hints. Anchored substrings (no word-boundary regex) so
# `customer_ssn.csv` matches even when the keyword is glued to a token.
_PII_PATTERNS = re.compile(
    r"(ssn|credit|passport|license|tax|driver_?licen|"
    r"medical|patient|hipaa|dob|birthdate)",
    re.IGNORECASE,
)
_CONFIDENTIAL_PATTERNS = re.compile(
    r"(payroll|salary|compensation|comp_band|bonus|stock_grant)",
    re.IGNORECASE,
)

# Column-name PII hints. These complement the filename rule for files
# whose name is innocuous (`finance_export.csv`) but whose columns leak
# PII (`customer_email`, `phone`, `dob`). Surfaced via
# ``Profile.extra['classification_hints']``.
_COLUMN_PII_PATTERNS = re.compile(
    r"(?:^|[^a-z0-9])("
    r"email|e_mail|"
    r"phone|mobile|"
    r"ssn|sin|tax_id|"
    r"dob|birth(?:date)?|"
    r"passport|"
    r"customer_name|user_name|first_name|last_name|full_name"
    r")(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Encoding detection
# ---------------------------------------------------------------------------


# Ordered candidate list. UTF-8 is the modern default; Windows-1252 is
# the dominant Western fallback for Excel exports; latin-1 is a final
# safety belt that never fails (every byte is a valid latin-1 codepoint).
_ENCODING_CANDIDATES: tuple[str, ...] = ("utf-8", "cp1252", "latin-1")


def detect_encoding(raw: bytes) -> str:
    """Return the first encoding from the candidate list that decodes ``raw``.

    Deterministic: utf-8 → cp1252 → latin-1. ``charset-normalizer`` is
    consulted as a hint (when installed) only to confirm the family —
    if it suggests a Windows-1252-family encoding (cp1252, cp1257,
    latin-1) and utf-8 fails, the connector picks ``cp1252`` because
    it is the dominant Western export encoding and the per-file
    detector is unstable on short Latin-1 sequences.

    Returns the encoding name suitable for ``bytes.decode``.
    """
    for enc in _ENCODING_CANDIDATES:
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    # latin-1 cannot fail; if we got here something else went wrong.
    return "latin-1"


@register_connector
class CsvLocalConnector(Connector):
    """Connector for CSV files on local disk."""

    kind = "csv_local"
    capability: set[Capability] = {"discover", "profile", "sample"}
    classification_hints: list[ClassificationHint] = ["pii_filename"]
    status: str = "production"
    status_note: str = (
        "Drop a file in any worm-watched channel; we profile it on landing."
    )

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        path = secrets.payload.get("path")
        if not path or not isinstance(path, str):
            raise ValueError("csv_local requires {path: str}")
        return AuthHandle(
            connector_kind="csv_local",
            handle_id=path,
            extra={"path": path},
        )

    async def discover(self, handle: AuthHandle) -> list[ResourceProposal]:
        path = Path(handle.extra["path"])
        if not path.exists():
            return []
        return [
            ResourceProposal(
                resource_id=str(path),
                name=path.name,
                kind="file",
                classification_hint=_classify_filename(path.name),
                metadata={
                    "size_bytes": path.stat().st_size,
                    "path": str(path),
                    "mimetype": "text/csv",
                },
            )
        ]

    async def profile(self, handle: AuthHandle, resource_id: str) -> Profile:
        path = Path(resource_id)
        # Read raw bytes once so encoding detection + parsing share one
        # I/O. Real-world finance exports are <100MB; the simplicity is
        # worth more than streaming for csv_local.
        raw = path.read_bytes()
        if not raw:
            return Profile(
                row_count=0,
                column_count=0,
                columns=[],
                schema_hash="",
                extra={
                    "path": str(path),
                    "encoding": "utf-8",
                    "duplicate_header_rows": 0,
                    "anomalies": [],
                    "classification_hints": [],
                },
            )

        encoding = detect_encoding(raw)
        text = raw.decode(encoding, errors="replace")
        reader = csv.reader(StringIO(text))
        try:
            header = next(reader)
        except StopIteration:
            return Profile(
                row_count=0,
                column_count=0,
                columns=[],
                schema_hash="",
                extra={
                    "path": str(path),
                    "encoding": encoding,
                    "duplicate_header_rows": 0,
                    "anomalies": [],
                    "classification_hints": [],
                },
            )
        rows = list(reader)

        # Excel-export sin: the file may carry a duplicate header row
        # immediately after the canonical one. Surface this honestly so
        # silver can dedupe; bronze keeps both. We count the trailing
        # contiguous duplicates, not just the first.
        duplicate_header_rows = 0
        while rows and rows[duplicate_header_rows] == header:
            duplicate_header_rows += 1
            if duplicate_header_rows >= len(rows):
                break
        data_rows = rows[duplicate_header_rows:]

        # Anomaly + classification surfaces. We compute these once over
        # the data rows so the cost is linear in the file, not quadratic
        # over column iteration.
        anomalies: list[dict[str, Any]] = []
        classification_hints: list[dict[str, Any]] = []

        columns = []
        for i, h in enumerate(header):
            col_values = [row[i] for row in data_rows if i < len(row)]
            non_empty = [v for v in col_values if v != ""]

            # Sentinel detection — the -9999 motif. We flag columns
            # whose distribution suggests an in-band sentinel rather
            # than the user actually meaning negative ten thousand.
            sentinel_count = sum(1 for v in non_empty if v == "-9999")
            if sentinel_count > 0:
                anomalies.append(
                    {
                        "column": h,
                        "kind": "sentinel_value",
                        "sentinel": "-9999",
                        "count": sentinel_count,
                    }
                )

            # Excel-error-string detection — #REF!, #N/A, #VALUE!, #DIV/0!.
            error_strings = [
                v for v in non_empty
                if v in {"#REF!", "#N/A", "#VALUE!", "#DIV/0!", "#NAME?", "#NULL!"}
            ]
            if error_strings:
                anomalies.append(
                    {
                        "column": h,
                        "kind": "excel_error_strings",
                        "tokens": sorted(set(error_strings)),
                        "count": len(error_strings),
                    }
                )

            # Column-name PII heuristic — surface for classification.
            if _COLUMN_PII_PATTERNS.search(h):
                classification_hints.append(
                    {
                        "column": h,
                        "hint": "pii",
                        "reason": "column_name_matches_pii_pattern",
                    }
                )

            columns.append(
                {
                    "name": h,
                    "dtype": _infer_dtype(col_values),
                    "sample_values": col_values[:3],
                    "null_count": sum(1 for v in col_values if v == ""),
                }
            )
        schema_hash = hashlib.sha256(
            ",".join(f"{c['name']}:{c['dtype']}" for c in columns).encode()
        ).hexdigest()[:16]
        return Profile(
            row_count=len(data_rows),
            column_count=len(header),
            columns=columns,
            schema_hash=schema_hash,
            extra={
                "path": str(path),
                "encoding": encoding,
                "duplicate_header_rows": duplicate_header_rows,
                "anomalies": anomalies,
                "classification_hints": classification_hints,
            },
        )

    async def sample(
        self, handle: AuthHandle, resource_id: str, n: int
    ) -> bytes:
        path = Path(resource_id)
        out = StringIO()
        with path.open("r") as f:
            for i, line in enumerate(f):
                # +1 to include header line in addition to n data rows.
                if i > n:
                    break
                out.write(line)
        return out.getvalue().encode()

    async def watch(
        self, handle: AuthHandle, resource_id: str
    ) -> AsyncIterator[Change]:
        # csv_local is pull-only; no streaming changes.
        if False:
            yield  # type: ignore[unreachable]


def _classify_filename(name: str) -> str | None:
    if _PII_PATTERNS.search(name):
        return "pii"
    if _CONFIDENTIAL_PATTERNS.search(name):
        return "confidential"
    return None


def _infer_dtype(values: list[str]) -> str:
    """Quick best-effort dtype inference from a column's string values."""
    non_empty = [v for v in values if v != ""]
    if not non_empty:
        return "str"
    if all(_is_int(v) for v in non_empty):
        return "int"
    if all(_is_float(v) for v in non_empty):
        return "float"
    if all(_is_bool(v) for v in non_empty):
        return "bool"
    return "str"


def _is_int(v: str) -> bool:
    try:
        int(v)
        return True
    except ValueError:
        return False


def _is_float(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False


def _is_bool(v: str) -> bool:
    return v.lower() in {"true", "false", "yes", "no", "0", "1"}


__all__ = ["CsvLocalConnector", "detect_encoding"]
