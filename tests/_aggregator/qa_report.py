"""Aggregate per-layer pytest junitxml outputs into a markdown table.

Usage:

    python -m tests._aggregator.qa_report \
        --junit packages/ledger/.junit.xml \
        --junit packages/ontology-seed/.junit.xml \
        ... etc.

Or, more commonly, called from the Makefile target `make qa-report`,
which runs every layer with --junitxml=<file> and pipes the resulting
files in here.

The script knows about 6 layers and infers each from the directory of
the test file in the junit XML:

    L1 unit         — apps/*/tests/test_* + packages/*/tests/test_*
    L2 component    — apps/dashboard/tests/* (TS — counted via vitest junit)
    L3 contract     — tests/contract/test_*
    L4 service      — pytest -m service (currently empty)
    L5 integration  — tests/integration/test_*
    L6 demo gates   — tests/demo/test_*
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

LAYER_ORDER = [
    ("L1 unit", "L1"),
    ("L2 component", "L2"),
    ("L3 contract", "L3"),
    ("L4 service", "L4"),
    ("L5 integration", "L5"),
    ("L6 demo gates", "L6"),
]


@dataclass
class LayerStats:
    count: int = 0
    pass_: int = 0
    fail: int = 0
    skipped: int = 0


def _classify(file_attr: str, classname: str) -> str:
    """Return a layer key (L1..L6) for a test based on its location.

    pytest-junit emits classname using dots (tests.contract.foo) and
    file as a path (tests/contract/foo.py). vitest's junit reporter
    uses similar conventions. We normalize both by replacing dots and
    backslashes so a single substring match works.
    """
    needle = (file_attr or "") + "|" + (classname or "")
    # Normalize separators: turn dotted classnames into slashes too.
    norm = needle.replace("\\", "/").replace(".", "/")
    if "tests/contract/" in norm or norm.startswith("tests/contract/"):
        return "L3"
    if "tests/integration/" in norm or norm.startswith("tests/integration/"):
        return "L5"
    if "tests/demo/" in norm or norm.startswith("tests/demo/"):
        return "L6"
    # L2 component tests — Vitest junit comes from dashboard + design.
    if "apps/dashboard/tests/" in norm or "packages/design/tests/" in norm:
        return "L2"
    if "apps/" in norm or "packages/" in norm:
        return "L1"
    # Fallback heuristic: treat unknown as L1 (unit) so we don't lose tests.
    return "L1"


def _parse_junit(path: Path, stats: dict[str, LayerStats]) -> None:
    if not path.exists():
        return
    try:
        tree = ET.parse(str(path))
    except ET.ParseError:
        return
    root = tree.getroot()
    suites = (
        list(root.iter("testsuite")) if root.tag == "testsuites" else [root]
    )
    for suite in suites:
        for case in suite.iter("testcase"):
            file_attr = case.get("file") or ""
            classname = case.get("classname") or ""
            layer = _classify(file_attr, classname)
            s = stats[layer]
            s.count += 1
            if case.find("failure") is not None or case.find("error") is not None:
                s.fail += 1
            elif case.find("skipped") is not None:
                s.skipped += 1
            else:
                s.pass_ += 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--junit", action="append", default=[],
        help="Path to a junitxml file; can be passed multiple times.",
    )
    p.add_argument(
        "--also-vitest", action="append", default=[],
        help="Path to a vitest junit.xml. Repeatable. All cases fold into L2 "
             "regardless of vitest's relative file paths.",
    )
    args = p.parse_args(argv)

    stats: dict[str, LayerStats] = defaultdict(LayerStats)
    for f in args.junit:
        _parse_junit(Path(f), stats)
    for vf in args.also_vitest:
        # vitest junit reporter uses package-relative paths (e.g.
        # tests/unit/Button.test.tsx) so our _classify substring rules
        # would land them in L1. Force them into L2 by parsing into a
        # scratch dict and folding everything we find into L2.
        vstats: dict[str, LayerStats] = defaultdict(LayerStats)
        _parse_junit(Path(vf), vstats)
        for v in vstats.values():
            target = stats["L2"]
            target.count += v.count
            target.pass_ += v.pass_
            target.fail += v.fail
            target.skipped += v.skipped

    # Emit a compact markdown-style table.
    print()
    print(f"{'LAYER':<16}{'COUNT':>7}{'PASS':>7}{'FAIL':>7}{'SKIPPED':>9}")
    print("-" * 46)
    for label, key in LAYER_ORDER:
        s = stats.get(key, LayerStats())
        print(
            f"{label:<16}{s.count:>7}{s.pass_:>7}{s.fail:>7}{s.skipped:>9}"
        )
    print()
    total = LayerStats()
    for s in stats.values():
        total.count += s.count
        total.pass_ += s.pass_
        total.fail += s.fail
        total.skipped += s.skipped
    print(
        f"{'TOTAL':<16}{total.count:>7}{total.pass_:>7}{total.fail:>7}"
        f"{total.skipped:>9}"
    )
    print()
    return 0 if total.fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
