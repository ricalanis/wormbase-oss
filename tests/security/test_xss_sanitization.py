"""W6.A6 — XSS payload pass-through safety.

Two structural facts give the dashboard an XSS-resistant baseline:

1. Next.js + React JSX renders strings as text by default. Inserting
   ``<script>alert(1)</script>`` into a chat content variable shows
   up as the literal characters; the browser parses it as text, not
   markup.
2. The dashboard does not call ``dangerouslySetInnerHTML`` anywhere
   under ``apps/dashboard/`` (this test asserts it).

This test file pins both invariants:

* Round-trips ≥6 canonical XSS payloads through the wire-replay write
  primitive; the payloads land in the ledger byte-identical (no
  pre-render escaping that would distort the audit log).
* Greps the dashboard source tree to confirm zero
  ``dangerouslySetInnerHTML`` usage in production code (test files
  permitted).
* Sanity-checks the voice-agent answer envelope contract — the
  dashboard's voice route returns ``answer`` as a plain string
  (not HTML), so payload injection through voice answers is
  rendered as text.

If any of these regresses we have an XSS surface we didn't have
before. Test fails immediately; reviewer can audit.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import pytest

from wormbase_channel_adapter.wire_replay import WireReplayer
from wormbase_ledger import InMemoryLedger


REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_ROOT = REPO_ROOT / "apps" / "dashboard"
TENANT_NAMESPACE = UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f")


def _company_id_for(slug: str) -> UUID:
    return uuid5(TENANT_NAMESPACE, slug.strip().lower())


# Canonical XSS payloads. Each must round-trip unchanged through
# the ledger; rendering each must yield literal text in the
# dashboard. (Renderer behaviour is asserted via the
# "no-dangerouslySetInnerHTML" sweep below — JSX text rendering is
# safe by construction.)
XSS_PAYLOADS = [
    "<script>alert(1)</script>",
    "javascript:alert(1)",
    '<img src=x onerror=alert(1)>',
    "<svg onload=alert(1)></svg>",
    # SVG namespace bypass with inline JS
    '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    # Unicode bidi-override (right-to-left override)
    "Hello‮evil‬",
    # Event-handler bypass via uppercase
    "<IMG SRC=x ONERROR=alert(1)>",
    # Data-URL javascript scheme
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    # iframe srcdoc
    '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
]


def _wire_record_for(text: str, seq: int) -> dict:
    return {
        "seq": seq,
        "ts": "2026-04-28T00:00:00+00:00",
        "tool": "channel_adapter.emit_chat_received",
        "args": {
            "channel_id": "C-xss-test",
            "message_id": f"{seq:08d}.{seq:04d}",
            "sender_person": str(uuid4()),
            "text": text,
            "classification": "internal",
        },
    }


@pytest.fixture
def xss_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "xss.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for i, payload in enumerate(XSS_PAYLOADS, start=1):
            fh.write(json.dumps(_wire_record_for(payload, i)) + "\n")
    return path


async def test_xss_payloads_round_trip_unchanged_through_ledger(
    xss_fixture: Path,
) -> None:
    """Ledger writes XSS payloads byte-identical to input.

    The ledger is the audit substrate; rewriting payloads at write
    time would silently corrupt the audit trail. Sanitization is the
    renderer's job (and JSX does it correctly by default), not the
    ledger's.
    """
    ledger = InMemoryLedger()
    company_id = _company_id_for("xss-test")
    replayer = WireReplayer(
        ledger=ledger,
        company_id=company_id,
        jsonl_path=xss_fixture,
    )
    await replayer.run()

    rows = await ledger.fetch(company_id)
    execute_payloads = [
        r["payload"]
        for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "channel_adapter.emit_chat_received"
    ]
    texts = [p["args"]["text"] for p in execute_payloads]
    assert texts == XSS_PAYLOADS, (
        "XSS payload corrupted at write time. The ledger MUST preserve "
        f"input bytes; got {texts!r} vs expected {XSS_PAYLOADS!r}"
    )


def test_no_dangerously_set_inner_html_in_dashboard_source() -> None:
    """``dangerouslySetInnerHTML`` is not used anywhere under apps/dashboard.

    React's text-content rendering escapes by default, so XSS is
    structurally prevented as long as no component opts out via
    ``dangerouslySetInnerHTML``. We sweep the source tree to assert
    no opt-out exists. Test files are exempt — they may exercise
    HTML-injection edge cases.
    """
    assert DASHBOARD_ROOT.exists(), (
        "apps/dashboard tree missing — repo layout changed?"
    )
    offenders: list[str] = []
    for path in DASHBOARD_ROOT.rglob("*.tsx"):
        if "node_modules" in path.parts:
            continue
        if any(p == "tests" for p in path.parts):
            continue
        if "__tests__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "dangerouslySetInnerHTML" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    for path in DASHBOARD_ROOT.rglob("*.ts"):
        if "node_modules" in path.parts:
            continue
        if any(p == "tests" for p in path.parts):
            continue
        if "__tests__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "dangerouslySetInnerHTML" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "dangerouslySetInnerHTML is forbidden in production code; "
        f"found in: {offenders}"
    )


def test_voice_answer_envelope_is_plain_string_contract() -> None:
    """The voice-ask route's answer field is typed as a plain string.

    A regression that retypes ``answer`` to ``React.ReactNode`` or
    similar would invite XSS surface. Pin the envelope contract.
    """
    route_path = (
        DASHBOARD_ROOT / "app" / "api" / "v1" / "voice" / "ask" / "route.ts"
    )
    assert route_path.exists(), f"voice/ask route missing: {route_path}"
    text = route_path.read_text(encoding="utf-8")
    # Crude but stable: the response envelope must declare answer as
    # ``string``. Not present → contract has drifted.
    assert re.search(r"answer:\s*string", text), (
        "voice/ask response envelope no longer types `answer` as "
        "string — XSS surface introduced"
    )


def test_xss_payload_categories_covered() -> None:
    """The payload set covers the canonical XSS attack categories.

    Each category corresponds to a real-world bypass technique:
    raw script tags, JS URL schemes, image onerror, SVG onload,
    Unicode bidi, uppercase event-handler, data: URL, iframe srcdoc,
    namespace bypass.
    """
    categories = {
        "script_tag": any("<script>" in p.lower() for p in XSS_PAYLOADS),
        "js_url_scheme": any("javascript:" in p for p in XSS_PAYLOADS),
        "image_onerror": any(
            "onerror" in p.lower() for p in XSS_PAYLOADS
        ),
        "svg_onload": any(
            "svg" in p.lower() and "onload" in p.lower() for p in XSS_PAYLOADS
        ),
        "svg_namespace": any(
            "xmlns" in p.lower() and "svg" in p.lower()
            for p in XSS_PAYLOADS
        ),
        "unicode_bidi": any(
            "‮" in p or "‬" in p for p in XSS_PAYLOADS
        ),
    }
    missing = [k for k, v in categories.items() if not v]
    assert not missing, (
        f"XSS coverage missing categories: {missing}. "
        f"Expected ≥6 distinct categories per W6.A6 spec."
    )
