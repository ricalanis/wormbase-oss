"""Q4 demo gate: full test suite passes (all layers green).

Currently skipped: this gate is implicitly the *result* of running
`make qa` (or `make qa-pre-demo`) — those targets aggregate every
other layer. A nested pytest-of-pytest invocation here would create
recursive overhead and confuse the qa-report aggregator.

Once we have a per-layer coverage threshold (currently zero — out of
scope for the demo), this test will instead assert layer counts hit
those thresholds.

For Thursday: humans run `make qa-pre-demo` and read the qa-report
table; the demo proceeds only if all rows are green.
"""

from __future__ import annotations

import pytest


def test_Q4_full_test_coverage() -> None:
    pytest.skip(
        "out of scope to nest a full pytest run inside another pytest run; "
        "see make qa-report for the layer aggregation"
    )
