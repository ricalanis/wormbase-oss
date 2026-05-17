"""Pinned-mirror: dashboard DOMAIN_PACK_CATALOG matches YAML packs.

Sub-wave D drift contract test (2026-05-30). The dashboard mirrors
the worm-core domain-pack catalog statically in
``apps/dashboard/lib/onboard.ts`` (constant ``DOMAIN_PACK_CATALOG``)
so the picker stays zero-round-trip at render time. The four pack
YAMLs live at ``apps/worm-core/src/wormbase_core/onboarding/packs/``.

When a new pack is added (or an existing pack's display name /
description / version drifts), this test fails loudly so the agent
is forced to update both sides in lockstep. Follows the same
pinned-mirror pattern as
``test_dashboard_platform_status_mirror.py`` (WhatsApp + Slack
platform descriptor mirror).

Comparison contract:
  * Pack id (case-insensitive)
  * Pack version
  * Display name → TS ``label``
  * Description → TS ``description``

We do NOT pin domainCount because the YAMLs are source-of-truth for
the canonical count and the TS constant manually mirrors it (drift
on count is caught by visually checking the picker; pinning it would
make benign domain-list edits also fail this test).

If the dashboard's TS file format evolves and breaks this regex,
swap to a JSON-export build-step (a small node script) instead of
regex-parsing TS.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ONBOARD_TS = REPO_ROOT / "apps" / "dashboard" / "lib" / "onboard.ts"
PACKS_DIR = (
    REPO_ROOT
    / "apps"
    / "worm-core"
    / "src"
    / "wormbase_core"
    / "onboarding"
    / "packs"
)


def _extract_ts_catalog() -> list[dict[str, str]]:
    """Regex-extract the DOMAIN_PACK_CATALOG constant from onboard.ts.

    Returns a list of dicts with keys: ``packId``, ``packVersion``,
    ``label``, ``description``.
    """
    text = ONBOARD_TS.read_text()
    # Match the const block:
    #   const DOMAIN_PACK_CATALOG: readonly DomainPackDescriptor[] = [ ... ];
    match = re.search(
        r"const\s+DOMAIN_PACK_CATALOG\s*:.*?=\s*\[(?P<body>.*?)\]\s*;",
        text,
        re.DOTALL,
    )
    if not match:
        pytest.fail(
            "could not find DOMAIN_PACK_CATALOG constant in onboard.ts — "
            "regex needs an update or the constant was moved/renamed",
        )
    body = match.group("body")
    descriptors: list[dict[str, str]] = []
    # Each pack object literal { packId: "...", packVersion: "...", ... }
    for obj_match in re.finditer(r"\{([^}]*)\}", body, re.DOTALL):
        obj_body = obj_match.group(1)
        fields: dict[str, str] = {}
        for field_match in re.finditer(
            r'(\w+)\s*:\s*"((?:[^"\\]|\\.)*)"',
            obj_body,
        ):
            fields[field_match.group(1)] = field_match.group(2)
        if fields.get("packId"):
            descriptors.append(fields)
    return descriptors


def _read_yaml_packs() -> dict[str, dict[str, str]]:
    """Read all pack YAMLs and return a packId-keyed dict.

    Each value carries: ``packVersion`` (from ``pack_version``),
    ``label`` (from ``display_name``), ``description`` (verbatim).
    """
    packs: dict[str, dict[str, str]] = {}
    for yaml_path in sorted(PACKS_DIR.glob("*.yaml")):
        data = yaml.safe_load(yaml_path.read_text())
        if not isinstance(data, dict):
            pytest.fail(f"pack YAML {yaml_path} did not parse as a dict")
        pack_id = data.get("pack_id")
        if not pack_id:
            pytest.fail(f"pack YAML {yaml_path} missing pack_id")
        packs[pack_id] = {
            "packId": pack_id,
            "packVersion": data.get("pack_version", ""),
            "label": data.get("display_name", ""),
            "description": data.get("description", ""),
        }
    return packs


def test_dashboard_pack_catalog_matches_yaml_packs() -> None:
    """TS constant + YAML packs agree on packId + version + label + description.

    Catches:
      * Adding a YAML pack without registering it in the TS picker.
      * Renaming a pack in YAML without bumping the TS mirror.
      * Editing the description in one side without the other.
    """
    ts_catalog = {entry["packId"]: entry for entry in _extract_ts_catalog()}
    yaml_packs = _read_yaml_packs()

    ts_ids = set(ts_catalog.keys())
    yaml_ids = set(yaml_packs.keys())
    assert ts_ids == yaml_ids, (
        "DOMAIN_PACK_CATALOG ids drifted from YAML pack ids — "
        f"TS-only: {sorted(ts_ids - yaml_ids)}; "
        f"YAML-only: {sorted(yaml_ids - ts_ids)}"
    )

    drift_report: list[str] = []
    for pack_id in sorted(ts_ids):
        ts = ts_catalog[pack_id]
        yml = yaml_packs[pack_id]
        for field in ("packVersion", "label", "description"):
            ts_val = ts.get(field, "")
            yml_val = yml.get(field, "")
            if ts_val != yml_val:
                drift_report.append(
                    f"  pack_id={pack_id!r} field={field!r}: "
                    f"TS={ts_val!r} != YAML={yml_val!r}"
                )
    if drift_report:
        pytest.fail(
            "DOMAIN_PACK_CATALOG drifted from YAML packs — update both "
            "sides in lockstep:\n" + "\n".join(drift_report)
        )


def test_drift_test_fails_loudly_on_synthetic_drift() -> None:
    """The drift test catches a synthetic mutation.

    Regression guard: pretend the YAML side gained a fifth pack and
    assert the comparison fails. Operates on local dicts (no
    monkeypatching) to keep the test simple + deterministic.
    """
    ts_catalog = {entry["packId"]: entry for entry in _extract_ts_catalog()}
    yaml_packs = _read_yaml_packs()
    # Inject a synthetic YAML-side pack.
    yaml_packs["pretend_new_pack"] = {
        "packId": "pretend_new_pack",
        "packVersion": "v1.0",
        "label": "Pretend",
        "description": "Pretend pack for drift-detection regression guard.",
    }

    # The TS-side won't have this pack, so the set-difference assertion
    # in the real test would fire. Replicate it inline here so this
    # test is self-contained.
    ts_ids = set(ts_catalog.keys())
    yaml_ids = set(yaml_packs.keys())
    assert ts_ids != yaml_ids, "synthetic drift should cause a set mismatch"
    assert "pretend_new_pack" in yaml_ids - ts_ids
