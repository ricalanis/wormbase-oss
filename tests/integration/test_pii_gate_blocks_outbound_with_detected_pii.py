"""L5 integration: PII gate redacts text and writes a gate_fired entry.

Drives a fully-wired ``PIIGate`` with a synthetic message containing
SSN-shaped, email-shaped, and credit-card-shaped substrings.

Asserts:

1. The returned redacted text replaces every match with `[REDACTED:<id>]`.
2. The classification escalation is set (`pii` or `regulated`).
3. A `gate_fired` ledger entry is recorded with `gate: pii`.

The actual outbound-sending side is the worm-core's ChatSender (P3),
which on a real run consults the PIIGate result and either redacts or
blocks. We assert the gate's contract here; the contract test
(`test_governance_projection_matches_ledger_state.py`) plus the gate's
unit tests (`packages/governance/tests/test_gates.py`) cover the
downstream pipe.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_pii_gate_redacts_and_records_gate_fired(
    integration_ledger, integration_company_id,
) -> None:
    from wormbase_governance import PIIGate

    gate = PIIGate(integration_ledger, integration_company_id)

    sample = (
        "Hey, my SSN is 123-45-6789 and my work email is "
        "alice@example.com — also card 4242 4242 4242 4242 (test number)."
    )
    result = await gate.check(sample, context={"source": "outbound_chat"})

    assert result.changed is True, "PIIGate did not detect any PII"
    assert "[REDACTED:" in result.redacted_text
    # Original PII substrings must NOT survive in the redacted text.
    assert "123-45-6789" not in result.redacted_text
    assert "alice@example.com" not in result.redacted_text

    assert result.classification_escalation in {"pii", "regulated"}, (
        f"escalation should fire on PII match, got: "
        f"{result.classification_escalation}"
    )

    # gate_fired entry must land in the ledger.
    rows = await integration_ledger.fetch(integration_company_id)
    pii_gate_fires = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_gate_fired"
        and r["payload"]["args"].get("gate") == "pii"
    ]
    assert pii_gate_fires, "PIIGate should write a gate_fired entry"
