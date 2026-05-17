"""Pinned-mirror: TS dashboard PlatformDescriptor matches Python adapter declarations.

Per Schema-Evolution Doctrine Rule 2 spirit (and the canonical pinned-mirror
pattern set by ``test_canonical_infra_event_fields_locked`` and
``test_chat_received_field_set_is_locked``): when the canonical Python
``ChannelAdapter`` subclass changes its ``status`` or ``capability`` attributes,
the TS sibling at ``apps/dashboard/lib/platform-status.ts`` must move in
lockstep. This test fails loudly when the two diverge so the agent is forced to
consciously update both sides.

Cross-language parsing approach: regex-extract the WhatsApp PlatformDescriptor
object literal from the TS source. The dashboard's TS file is hand-written,
well-formatted, and has predictable structure — but regex parsing of TS IS
fragile. If this test starts producing false negatives because the TS file's
formatting evolves, swap to a JSON-export shim:

    1. Add a ``platform-status.json`` build-step output (small node script)
    2. Have this test read the JSON instead of regex-parsing TS

Today the regex path is good enough — the TS surface only changes when an
adapter is promoted/demoted (rare).

The test treats ``capabilities`` as opt-in:
- When the TS descriptor has ``capabilities``, it MUST match the Python
  adapter's ``capability`` set exactly (sorted comparison).
- When the TS descriptor omits ``capabilities``, the test only verifies
  ``(platform, status)`` agree. This lets older descriptors migrate to
  capability-honesty gradually without forcing the whole table to change at
  once.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLATFORM_STATUS_TS = REPO_ROOT / "apps" / "dashboard" / "lib" / "platform-status.ts"


def _extract_ts_descriptor(slug: str) -> dict:
    """Regex-extract a PlatformDescriptor object literal from platform-status.ts.

    Returns a dict with keys: platform, status, statusNote, capabilities (if
    present), envHint (if present). Fields are returned as Python types
    (strings, list[str]).

    Raises if the TS file cannot be parsed — a hard failure flag for the next
    agent to repair the parser.
    """
    src = PLATFORM_STATUS_TS.read_text(encoding="utf-8")

    # Find the descriptor block whose first line declares `platform: "<slug>"`.
    # Brace-balanced extraction: walk forward from the platform line until the
    # next standalone `},` at indent.
    lines = src.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.search(rf'platform:\s*"{re.escape(slug)}"', line):
            start = i
            break
    if start is None:
        raise AssertionError(
            f"platform-status.ts: descriptor for slug={slug!r} not found"
        )

    # Walk back to the opening `{` (one or two lines above).
    open_line = start
    while open_line > 0 and not lines[open_line].rstrip().endswith("{"):
        open_line -= 1
    # Walk forward to the matching `},`.
    close_line = start
    depth = 1
    for j in range(start, len(lines)):
        depth += lines[j].count("{") - lines[j].count("}")
        if depth == 0:
            close_line = j
            break
    block = "\n".join(lines[open_line : close_line + 1])

    out: dict = {}
    if m := re.search(r'platform:\s*"([^"]+)"', block):
        out["platform"] = m.group(1)
    if m := re.search(r'status:\s*"([^"]+)"', block):
        out["status"] = m.group(1)
    # statusNote may span multiple lines as concatenated strings — match any
    # form ``statusNote: <stuff>,`` and strip TS string concatenation.
    if m := re.search(r"statusNote:\s*([^,]+(?:,(?!\s*\w+:)[^,]*)*),", block, re.DOTALL):
        raw = m.group(1)
        parts = re.findall(r'"([^"]*)"', raw)
        out["statusNote"] = "".join(parts)
    if m := re.search(r'envHint:\s*"([^"]+)"', block):
        out["envHint"] = m.group(1)
    if m := re.search(r"capabilities:\s*\[([^\]]+)\]", block):
        caps = re.findall(r'"([^"]+)"', m.group(1))
        out["capabilities"] = caps
    return out


def test_whatsapp_descriptor_mirrors_python_adapter():
    """WhatsApp's TS descriptor matches the Python adapter declaration."""
    from wormbase_channel_adapters.whatsapp import WhatsAppChannelAdapter

    ts = _extract_ts_descriptor("whatsapp")
    py_status = WhatsAppChannelAdapter.status
    py_capability = set(WhatsAppChannelAdapter.capability)
    py_status_note = WhatsAppChannelAdapter.status_note

    assert ts["platform"] == "whatsapp"
    assert ts["status"] == py_status, (
        f"TS status={ts['status']!r} but Python adapter status={py_status!r}. "
        f"Update apps/dashboard/lib/platform-status.ts WhatsApp descriptor."
    )
    assert "capabilities" in ts, (
        "TS descriptor opted into the capabilities mirror; field must be present "
        "(see W1 plan §4 — opt-in pattern requires the field once added)."
    )
    assert set(ts["capabilities"]) == py_capability, (
        f"TS capabilities={sorted(ts['capabilities'])!r} but Python "
        f"capability={sorted(py_capability)!r}. Adapter and dashboard mirror "
        f"have drifted. Sync apps/dashboard/lib/platform-status.ts WhatsApp "
        f"capabilities array OR update the Python adapter's capability set, "
        f"then rerun this test."
    )

    # statusNote is a paraphrase — assert it carries the canonical signal
    # words rather than exact-match (the TS may collapse whitespace).
    ts_note = ts["statusNote"]
    for keyword in ["Preview", "Baileys", "ToS", "CLI"]:
        assert keyword.lower() in ts_note.lower(), (
            f"TS statusNote missing keyword {keyword!r}. Got: {ts_note!r}. "
            f"Python status_note: {py_status_note!r}"
        )


def test_slack_descriptor_status_matches_python_adapter():
    """Slack's TS descriptor status matches Python (capabilities opt-in deferred)."""
    from wormbase_channel_adapters.slack import SlackChannelAdapter

    ts = _extract_ts_descriptor("slack")
    py_status = SlackChannelAdapter.status

    assert ts["platform"] == "slack"
    assert ts["status"] == py_status

    # Slack hasn't opted into the capabilities mirror yet (see W1 plan §4).
    # When it does, this test will additionally assert the array matches.
    if "capabilities" in ts:
        py_capability = set(SlackChannelAdapter.capability)
        assert set(ts["capabilities"]) == py_capability, (
            f"Slack TS capabilities={sorted(ts['capabilities'])!r} but Python "
            f"capability={sorted(py_capability)!r}. Sync the mirror."
        )


@pytest.mark.parametrize(
    "slug,expected_status",
    [
        ("discord", "preview"),
        ("teams", "preview"),
        ("signal", "coming_soon"),
    ],
)
def test_other_platform_descriptors_have_expected_status(slug, expected_status):
    """Discord/Teams/Signal stay at the documented status grades.

    Pinned for byte-identical no-change posture in W1; if any of these flip
    status (production rollout, etc.) the dispatcher will need to update
    both this test and the Python adapter's declaration.
    """
    ts = _extract_ts_descriptor(slug)
    assert ts["status"] == expected_status


def test_capabilities_field_uses_known_literals():
    """Any capabilities array in the TS must use literals from the type alias."""
    valid = {"ingest", "send", "file_upload", "dm", "voice"}
    for slug in ("slack", "discord", "teams", "signal", "whatsapp"):
        ts = _extract_ts_descriptor(slug)
        if "capabilities" not in ts:
            continue
        unknown = set(ts["capabilities"]) - valid
        assert not unknown, (
            f"{slug} TS capabilities contains unknown literals: {sorted(unknown)!r}. "
            f"Either expand Capability type in platform-status.ts OR fix the typo."
        )
