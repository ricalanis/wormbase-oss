"""Drift detector for the helper duplications registered in
`docs/superpowers/specs/2026-05-04-helper-duplications-register.md` (O-B5).

Each intentional duplicate must stay byte-equivalent to its canonical site.
If a future change must legitimately diverge, hoist the helper to a shared
location and remove the row from the register + the corresponding assertion
here. Drifting in place is never sanctioned.
"""
from __future__ import annotations

import ast
import inspect
import textwrap


def _norm_source(fn) -> str:
    """Normalize a function source for behavior-equivalence comparison.

    Parses the function body with `ast`, strips the docstring (the prose
    legitimately differs between canonical and mirror sites — comments
    on context can describe each site's local role), and unparses the
    remaining body. This compares *behavior*, not prose.

    Falls back to a whitespace-and-comment-stripped string compare for
    any function whose source `ast.parse` cannot resolve.
    """
    src = inspect.getsource(fn)
    try:
        tree = ast.parse(textwrap.dedent(src))
    except SyntaxError:
        return "\n".join(
            line.strip()
            for line in src.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )

    fn_node = tree.body[0]
    if not isinstance(fn_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "\n".join(
            line.strip()
            for line in src.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )

    body = list(fn_node.body)
    # Strip leading docstring expression (Constant string at body[0]).
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]

    fn_node.body = body if body else [ast.Pass()]
    return ast.unparse(fn_node)


def test_pii_filename_hints_stay_equivalent() -> None:
    from wormbase_core.flows import _PII_FILENAME_HINTS as core
    from wormbase_chat_presence.chat_flows.kpi_gap_triggered import (
        _PII_FILENAME_HINTS as chat,
    )
    assert core.pattern == chat.pattern, (
        "_PII_FILENAME_HINTS drifted between wormbase_core.flows and "
        "wormbase_chat_presence.chat_flows.kpi_gap_triggered. "
        "See docs/superpowers/specs/2026-05-04-helper-duplications-register.md."
    )


def test_data_source_keywords_stay_equivalent() -> None:
    from wormbase_core.relevance import _DATA_SOURCE_KEYWORDS as core
    from wormbase_chat_presence.relevance import _DATA_SOURCE_KEYWORDS as chat
    assert set(core) == set(chat), (
        "_DATA_SOURCE_KEYWORDS drifted between worm-core and chat-presence "
        "re-export shims. Both must point at wormbase_governance.relevance."
    )


def test_scrub_credential_stays_equivalent() -> None:
    from wormbase_core.flows import _scrub_credential as core
    from wormbase_chat_presence.chat_flows.credential_in_dm import (
        _scrub_credential as chat,
    )
    assert _norm_source(core) == _norm_source(chat), (
        "_scrub_credential drifted between wormbase_core.flows and "
        "wormbase_chat_presence.chat_flows.credential_in_dm. "
        "See docs/superpowers/specs/2026-05-04-helper-duplications-register.md."
    )


def test_event_to_infra_stays_equivalent() -> None:
    from wormbase_core.service import _event_to_infra as core
    from wormbase_chat_presence.dispatcher import _event_to_infra as chat
    assert _norm_source(core) == _norm_source(chat), (
        "_event_to_infra drifted between wormbase_core.service and "
        "wormbase_chat_presence.dispatcher. The chat-presence copy is a "
        "pinned mirror; sync from the canonical worm-core site, or hoist "
        "the helper to a shared package. "
        "See docs/superpowers/specs/2026-05-04-helper-duplications-register.md."
    )
