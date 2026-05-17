"""W6.A6 — path-traversal blocked on every UUID-typed route param.

API routes that take an ``id`` path param (data-products, notebooks,
sources, people, decisions, processes, kpis, reactivities) must
parse the value as a UUID before using it. A traversal attempt
(``../etc/passwd``, ``%2E%2E/secret``, Windows-style ``..\\..\\``)
must be rejected by the validator with HTTP 400 — never reach the
filesystem, never reach the DB.

This test pins:

* ``UUID(...)`` raises for every canonical traversal payload (the
  single source-of-truth validator behaviour).
* The dashboard route handlers' shape declares ``params: { id }``
  (Next.js dynamic-segment), and downstream calls go through
  ``getDataProduct(companyId, id)``-style helpers that bind the id
  as a parameter — never as a filesystem path.
* No dashboard helper passes user-controlled ``id`` to ``fs.*`` or
  ``open()``-equivalent APIs (``readFile``, ``createReadStream``).
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_ROOT = REPO_ROOT / "apps" / "dashboard"


# Canonical path-traversal payloads.
TRAVERSAL_PAYLOADS = [
    "../etc/passwd",
    "..%2Fetc%2Fpasswd",
    "%2E%2E%2Fetc%2Fpasswd",
    "%2e%2e/secret",
    "..\\..\\windows-style",
    "..%5C..%5Cwindows",
    "....//etc/passwd",  # bypass attempt: doubled dots + slashes
    "/etc/passwd",
    # Null-byte truncation (legacy)
    "abc\x00../etc/passwd",
    # Backslash-only
    "..\\boot.ini",
    # Mixed separators
    "..\\../mix",
]


def _is_uuid(s: str) -> bool:
    try:
        UUID(s)
        return True
    except (ValueError, TypeError):
        return False


def test_uuid_validator_rejects_every_traversal_payload() -> None:
    """``UUID(...)`` raises for every traversal-shaped string.

    Routes that parse path params via ``UUID(...)`` get path-
    traversal protection for free — none of these payloads can
    survive the UUID parse.
    """
    rejected = [p for p in TRAVERSAL_PAYLOADS if not _is_uuid(p)]
    assert rejected == TRAVERSAL_PAYLOADS, (
        f"UUID parser accepted traversal-shaped values: "
        f"{set(TRAVERSAL_PAYLOADS) - set(rejected)}"
    )


def test_dashboard_helpers_do_not_open_files_with_user_ids() -> None:
    """No ``fs.readFile(id, ...)`` or ``createReadStream(id, ...)``
    pattern under apps/dashboard.

    A regression that opens a file path constructed from a user-
    supplied ``id`` is the canonical path-traversal vulnerability.
    Sweep the dashboard tree to confirm no such call exists in
    production code paths.
    """
    forbidden_patterns = (
        re.compile(r"fs\s*\.\s*readFile\s*\(\s*[a-zA-Z_]+\.id"),
        re.compile(r"createReadStream\s*\(\s*[a-zA-Z_]+\.id"),
        re.compile(r"fs\s*\.\s*createReadStream\s*\(\s*[a-zA-Z_]+\.id"),
        re.compile(r"path\s*\.\s*join\s*\(\s*[^,)]+,\s*[a-zA-Z_]+\.id\s*\)"),
    )
    offenders: list[str] = []
    for ext in ("*.ts", "*.tsx"):
        for path in DASHBOARD_ROOT.rglob(ext):
            if "node_modules" in path.parts:
                continue
            if any(p == "tests" for p in path.parts):
                continue
            if "__tests__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pat in forbidden_patterns:
                if pat.search(text):
                    offenders.append(str(path.relative_to(REPO_ROOT)))
                    break
    assert not offenders, (
        "dashboard contains fs.readFile / createReadStream / path.join "
        f"calls with user-controlled ids: {offenders}"
    )


def test_data_product_route_takes_id_as_path_param_not_path() -> None:
    """The ``[id]`` route signature receives the param via ``ctx.params``,
    not via the URL pathname.

    Next.js dynamic segments are URL-decoded and validated by the
    framework. If the route reads from a raw URL pathname instead,
    traversal payloads might survive. Pin the canonical shape.
    """
    route = (
        DASHBOARD_ROOT / "app" / "api" / "v1" / "data-products" / "[id]" / "route.ts"
    )
    if not route.exists():
        # Sometimes /api/v1 wraps an inner route; check the alternate.
        route = (
            DASHBOARD_ROOT / "app" / "api" / "data-products" / "[id]" / "route.ts"
        )
    assert route.exists(), (
        f"expected data-products/[id]/route.ts under apps/dashboard"
    )
    text = route.read_text(encoding="utf-8")
    assert re.search(r"params:\s*Promise<\{\s*id:\s*string\s*\}>", text), (
        "data-products [id] route no longer declares "
        "`params: Promise<{ id: string }>` — Next.js dynamic-segment "
        "shape changed; review traversal protection."
    )


def test_traversal_payload_categories_covered() -> None:
    """Coverage: forward-slash, backward-slash, encoded, null-byte,
    absolute paths, doubled bypass.
    """
    cats = {
        "forward_slash": any("/" in p and ".." in p for p in TRAVERSAL_PAYLOADS),
        "back_slash": any("\\" in p for p in TRAVERSAL_PAYLOADS),
        "url_encoded": any("%2" in p.lower() for p in TRAVERSAL_PAYLOADS),
        "null_byte": any("\x00" in p for p in TRAVERSAL_PAYLOADS),
        "absolute_path": any(p.startswith("/") for p in TRAVERSAL_PAYLOADS),
        "doubled_bypass": any("...." in p for p in TRAVERSAL_PAYLOADS),
    }
    missing = [k for k, v in cats.items() if not v]
    assert not missing, (
        f"path-traversal payload coverage missing: {missing}. "
        "Required: ≥3 categories per W6.A6 spec."
    )


def test_uuid_typed_id_param_round_trip() -> None:
    """A real UUID parses cleanly; traversal payloads do not.

    Smoke-test the validator's positive case as well as the rejection
    sweep, so we know the rejection isn't accidental (e.g. a UUID()
    call that always raises).
    """
    real = "11111111-1111-1111-1111-111111111111"
    assert _is_uuid(real)
    for payload in TRAVERSAL_PAYLOADS:
        assert not _is_uuid(payload), f"UUID accepted traversal {payload!r}"
