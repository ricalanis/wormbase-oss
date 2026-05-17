"""Default local source — wires the cursed CSV into the install arc.

Per Demo-Day PRD §7 P4, every fresh tenant gets a default local source
auto-provisioned at install. The source is the
``fixtures/cursed_finance_export.csv`` fixture: a Windows-1252-encoded
finance export with duplicate header rows, Excel-error strings, a
``-9999`` sentinel column, two adjacent datetime columns, and a PII
column name (``customer_email``) — a realistic-feeling Tuesday-morning
problem, not a contrived toy.

This module is the integration hook between the install flow and the
medallion cascade for that fixture. The companion ``provision_local_lake``
in :mod:`wormbase_core.write_actions` is responsible for the
``LocalLakeConnector`` (the always-on medallion shell); this module is
responsible for the *content* of the lake's bronze tier — the cursed
CSV, profiled and cascaded into bronze + silver + gold ledger entries.

The split exists so other workstreams (P2 ramp gauges, P9 lessons) can
extend ``LocalLakeConnector`` independently from the cursed-CSV content
question. Calling :func:`run_default_local_cascade` after
``provision_local_lake`` produces an additional bronze→silver→gold
cascade rooted at the cursed CSV.

Resolution order for the fixture path:

1. ``WORMBASE_DEFAULT_LOCAL_CSV`` env var (CI / pilot escape hatch)
2. Repo-rooted ``fixtures/cursed_finance_export.csv`` (the canonical path)
3. ``ImportError``-style ``FileNotFoundError`` if neither resolves —
   the install flow is supposed to bail loudly, not silently.
"""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from wormbase_connectors.csv_local import detect_encoding

if TYPE_CHECKING:
    from wormbase_ledger import InMemoryLedger, Ledger


# Filename is exported so other modules don't have to spell it.
CURSED_CSV_FIXTURE_FILENAME = "cursed_finance_export.csv"


def _repo_root() -> Path:
    """Resolve the WormBase repo root from this module's location.

    The module sits at
    ``apps/worm-core/src/wormbase_core/onboarding/default_local_source.py``;
    walking up four parents lands at the repo root containing
    ``fixtures/`` + ``apps/`` + ``packages/``.
    """
    return Path(__file__).resolve().parents[5]


CURSED_CSV_PATH: Path = _repo_root() / "fixtures" / CURSED_CSV_FIXTURE_FILENAME


def cursed_csv_path() -> Path:
    """Return the resolved path to the cursed CSV fixture.

    Honors ``WORMBASE_DEFAULT_LOCAL_CSV`` if set so CI / pilot deploys
    can swap in their own copy of the fixture without touching code.
    Raises ``FileNotFoundError`` if the path doesn't resolve to a real
    file — the install flow expects to fail loudly here.
    """
    override = os.environ.get("WORMBASE_DEFAULT_LOCAL_CSV")
    candidate = Path(override) if override else CURSED_CSV_PATH
    if not candidate.is_file():
        raise FileNotFoundError(
            f"Default local CSV fixture not found at {candidate}. "
            f"Run `python scripts/generate_cursed_csv.py` to regenerate, "
            f"or set WORMBASE_DEFAULT_LOCAL_CSV to a custom path."
        )
    return candidate


# ---------------------------------------------------------------------------
# Silver normalization — the bronze→silver boundary for the cursed CSV
# ---------------------------------------------------------------------------


_EXCEL_ERROR_TOKENS: frozenset[str] = frozenset(
    {
        "#REF!",
        "#N/A",
        "#VALUE!",
        "#DIV/0!",
        "#NAME?",
        "#NULL!",
    }
)


def cursed_csv_silver_bytes(
    raw: bytes | None = None,
    *,
    path: Path | None = None,
) -> bytes:
    """Apply silver-layer normalization to the cursed CSV bytes.

    Three transformations the cursed export demands at the bronze→silver
    boundary:

    1. **Re-encode** cp1252 → utf-8 so the cascade's parser can read
       Latin-1 names without a custom decoder.
    2. **Dedup** the duplicate header row. Bronze surfaces both;
       silver keeps one.
    3. **Null Excel-error strings** (``#REF!``, ``#N/A``, …) so a column
       that is 99% numeric isn't downgraded to ``string`` dtype by a
       single bad cell.

    Caller passes either ``raw`` bytes (deterministic for tests) or a
    ``path`` to read from. Without arguments the canonical fixture
    path is resolved via :func:`cursed_csv_path`.

    Returns clean utf-8-encoded CSV bytes ready for ``MedallionCascade``.
    """
    if raw is None:
        target = path if path is not None else cursed_csv_path()
        raw = target.read_bytes()
    encoding = detect_encoding(raw)
    text = raw.decode(encoding)

    lines = text.replace("\r\n", "\n").split("\n")
    if len(lines) >= 2 and lines[0] == lines[1]:
        lines = [lines[0]] + lines[2:]
    deduped_text = "\n".join(lines)

    reader = csv.reader(io.StringIO(deduped_text))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for row in reader:
        cleaned = [
            "" if cell.strip() in _EXCEL_ERROR_TOKENS else cell
            for cell in row
        ]
        writer.writerow(cleaned)
    return out.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# Cascade entrypoint
# ---------------------------------------------------------------------------


async def run_default_local_cascade(
    ledger: "Ledger | InMemoryLedger",
    company_id: UUID,
    *,
    source_id: UUID | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Run bronze → silver → gold on the cursed CSV for ``company_id``.

    Intended to be invoked from the install flow once the
    ``LocalLakeConnector`` has been provisioned. Reads the fixture
    bytes, applies silver normalization, and pushes them through
    :class:`wormbase_core.medallion.MedallionCascade`. Returns the
    cascade's summary dict (bronze profile + silver columns + gold
    artifact) so the install flow can stamp the resulting source row
    with metadata.

    The function is idempotent over its inputs: same ``company_id`` +
    same ``source_id`` + same fixture bytes → same ledger entries on
    replay (Triad C2). Callers usually let ``source_id`` default to a
    fresh uuid; pass an explicit one for replay or test scenarios.
    """
    # Local imports keep import-time costs down for callers that only
    # want path resolution (e.g. CLI inspectors).
    from wormbase_core.medallion import MedallionCascade

    target_path = path if path is not None else cursed_csv_path()
    silver_bytes = cursed_csv_silver_bytes(path=target_path)

    cascade = MedallionCascade(ledger)
    sid = source_id if source_id is not None else uuid4()
    summary = await cascade.cascade(
        company_id=company_id,
        source_id=sid,
        uri=f"file://{target_path}",
        mime="text/csv",
        raw_bytes=silver_bytes,
    )
    summary["source_id"] = str(sid)
    summary["fixture_path"] = str(target_path)

    # Wave 2 Sub-wave B: emit per-table catalog_table_imported via the
    # csv_local extractor so the L2 TableSet / L8 SchemaShape lake-axis
    # strategies see populated columns for this source. The extractor
    # reads the CSV header row; resource_id == file path (the
    # CsvLocalConnector convention). The snapshot_hash leg uses the
    # silver bytes digest so the per-table row joins back to the
    # cascade's bronze profile across replays.
    import hashlib as _hashlib

    from wormbase_core.write_actions import (
        emit_catalog_table_imported_for_resource,
    )

    snapshot_hash = _hashlib.sha256(silver_bytes).hexdigest()
    catalog_result = await emit_catalog_table_imported_for_resource(
        ledger=ledger,  # type: ignore[arg-type]
        company_id=company_id,
        source_id=sid,
        snapshot_hash=snapshot_hash,
        table_id=str(target_path),
        connector_kind="csv_local",
        resource_id=str(target_path),
        proposed_by="default_local_cascade",
    )
    summary["catalog_table_snapshot_hash"] = snapshot_hash
    summary["catalog_table_entry_ids"] = [
        str(eid) for eid in catalog_result.entry_ids
    ]
    return summary


__all__ = [
    "CURSED_CSV_FIXTURE_FILENAME",
    "CURSED_CSV_PATH",
    "cursed_csv_path",
    "cursed_csv_silver_bytes",
    "run_default_local_cascade",
]
