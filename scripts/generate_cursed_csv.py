"""Regenerate ``fixtures/cursed_finance_export.csv`` deterministically.

This is the demo's worst-case-realistic CSV: a finance export that survived
two trips through Excel, a network-stitch of timezones, and a
classification-naive author. It exists so the bronze→silver→gold cascade
is exercised on data that smells like a real practitioner's Tuesday-morning
problem, not a clean toy.

Curses (each is intentional and tested for in
``apps/worm-core/tests/test_cursed_csv_connector.py``):

* Encoding: Windows-1252 (NOT UTF-8). Connectors must detect.
* Two duplicate header rows at the top (Excel-export sin).
* Column literally named ``Q3 Rev (final)(USE THIS)`` — parens and
  capitalization preserved (Seed-S1 chatter references this exact label).
* ``net_revenue`` column contains both ``#REF!`` and ``#N/A`` strings
  scattered through an otherwise-numeric series.
* ``customer_count`` uses ``-9999`` as a missing-value sentinel.
* Two datetime columns for the same logical event:
  ``recorded_at`` (timezone-naïve, ``%Y-%m-%d %H:%M:%S``) adjacent to
  ``recorded_at_utc`` (tz-aware ISO-8601 with ``Z`` suffix).
* ``customer_email`` column with PII in the column name —
  classification heuristic must flag it.
* 220 data rows so silver has enough mass for a KPI proposal.

Run ``python scripts/generate_cursed_csv.py`` from the repo root to
regenerate the file. The output is byte-identical across runs.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Deterministic seed — the file must be byte-identical across runs so
# wire-replay determinism (Q8) extends to the fixture itself.
SEED = 20260429

ROW_COUNT = 220

REGIONS = ("NA", "EMEA", "APAC", "LATAM")
DEPARTMENTS = ("Sales", "Marketing", "Finance", "Customer Success", "Product")
PRODUCTS = (
    "Worm Core",
    "Worm Pro",
    "Worm Enterprise",
    "Worm Lite",
    "Worm Audit",
)
SALES_REPS = (
    # Names with mild Latin-1-only characters force the file to be
    # genuinely Windows-1252-encoded — a real bilingual finance export.
    "Sofía Martínez",
    "François Dubois",
    "Jürgen Müller",
    "André Chen",
    "Chloé O'Brien",
    "Renée García",
    "José Álvarez",
    "Élise Dupont",
    "Mario Rossi",
    "Fátima Hassan",
)
EMAIL_DOMAINS = (
    "acme.example",
    "globex.example",
    "initech.example",
    "umbrella.example",
    "stark.example",
)


# Header — note the duplicate row + Excel-style column with parens.
HEADER = [
    "row_id",
    "deal_id",
    "customer_name",
    "customer_email",        # PII column name — classification heuristic
    "region",
    "department",
    "product",
    "sales_rep",
    "Q3 Rev (final)(USE THIS)",  # exact label referenced by Seed-S1
    "net_revenue",           # carries #REF!, #N/A among numeric strings
    "customer_count",        # uses -9999 sentinel for missing
    "recorded_at",           # tz-naïve "%Y-%m-%d %H:%M:%S"
    "recorded_at_utc",       # tz-aware ISO-8601 with Z
    "notes",
]


def _build_rows(rng: random.Random) -> list[list[str]]:
    """Produce ROW_COUNT rows under deterministic RNG."""
    rows: list[list[str]] = []
    base_dt = datetime(2026, 7, 1, 9, 0, 0)  # Q3 2026 kickoff, naïve
    for i in range(ROW_COUNT):
        deal_id = f"D-2026Q3-{i + 1001:05d}"
        customer = f"Customer {i + 1:03d} Inc."
        # PII email — heuristic should flag the COLUMN, not the values.
        email = (
            f"contact{i + 1:03d}@" + rng.choice(EMAIL_DOMAINS)
        )
        region = rng.choice(REGIONS)
        dept = rng.choice(DEPARTMENTS)
        product = rng.choice(PRODUCTS)
        rep = rng.choice(SALES_REPS)

        # Q3 revenue: realistic SaaS deal sizes, mostly numeric, with a
        # sprinkling of Excel-formula errors (#REF!) the connector must
        # tolerate as strings rather than truncate the file at.
        if i % 37 == 0:
            q3_rev = "#REF!"
        else:
            # 1.2k → 480k range, 2dp.
            q3_rev = f"{round(rng.uniform(1200.0, 480_000.0), 2)}"

        # net_revenue: mostly numeric, occasionally #N/A (missing value
        # that Excel emits when a VLOOKUP whiffed).
        if i % 41 == 0:
            net_rev = "#N/A"
        elif i % 53 == 0:
            net_rev = "#REF!"
        else:
            # Net is typically 80-95% of gross — use a noisy multiplier.
            try:
                gross = float(q3_rev)
                net = gross * rng.uniform(0.78, 0.95)
                net_rev = f"{round(net, 2)}"
            except ValueError:
                net_rev = "#N/A"

        # customer_count: -9999 sentinel means "we lost the row in the
        # CRM merge"; otherwise a small integer.
        if i % 23 == 0:
            count = "-9999"
        else:
            count = str(rng.randint(1, 240))

        # Two datetime representations of the same logical event. The
        # naïve form is what Excel exports when the user forgot to set
        # locale; the UTC form is what the API returned. The pair is
        # adjacent on purpose so the connector can spot the redundancy.
        offset_minutes = rng.randint(0, 60 * 24 * 90)  # within Q3 window
        local_dt = base_dt + timedelta(minutes=offset_minutes)
        utc_dt = local_dt.replace(tzinfo=timezone.utc)
        recorded_at = local_dt.strftime("%Y-%m-%d %H:%M:%S")
        recorded_at_utc = utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Notes — occasionally include a Latin-1 character so the file
        # genuinely needs Windows-1252 to round-trip cleanly.
        notes_pool = (
            "renewal",
            "upsell",
            "new logo",
            "expansion — multi-year",
            "pilot — eval phase",
            "churn risk",
            "réquête en cours",  # forces Latin-1
            "—",
        )
        notes = rng.choice(notes_pool)

        rows.append(
            [
                str(i + 1),
                deal_id,
                customer,
                email,
                region,
                dept,
                product,
                rep,
                q3_rev,
                net_rev,
                count,
                recorded_at,
                recorded_at_utc,
                notes,
            ]
        )
    return rows


def _csv_quote(field: str) -> str:
    """Minimal csv quoting compatible with Windows-1252 output."""
    needs_quote = any(c in field for c in (",", '"', "\n", "\r"))
    if needs_quote:
        escaped = field.replace('"', '""')
        return f'"{escaped}"'
    return field


def _format_row(row: list[str]) -> str:
    return ",".join(_csv_quote(c) for c in row)


def render_csv() -> bytes:
    """Return the cursed CSV as Windows-1252-encoded bytes."""
    rng = random.Random(SEED)
    rows = _build_rows(rng)

    header_line = _format_row(HEADER)

    lines: list[str] = []
    # Two duplicate header rows — frequent Excel-export sin where the
    # user copied the header band twice while merging sheets. Silver
    # must dedupe; bronze must surface both.
    lines.append(header_line)
    lines.append(header_line)
    for r in rows:
        lines.append(_format_row(r))

    text = "\r\n".join(lines) + "\r\n"
    # Encode as Windows-1252 — the headline curse. ``replace`` is a
    # safety belt; the inputs are crafted to be cp1252-clean.
    return text.encode("cp1252", errors="replace")


def main() -> None:
    target = Path(__file__).resolve().parent.parent / "fixtures" / "cursed_finance_export.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(render_csv())
    print(f"wrote {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
