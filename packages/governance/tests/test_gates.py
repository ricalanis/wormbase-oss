"""Block G tests: PII / warmup / interjection / knowledge gates."""

from __future__ import annotations

from wormbase_governance.gates import (
    InterjectionGate,
    KnowledgeGate,
    PIIGate,
    WarmupGate,
)


# ---- PII gate ------------------------------------------------------


async def test_pii_gate_redacts_email(ledger, company_id):
    gate = PIIGate(ledger, company_id)
    result = await gate.check("contact me at alice@example.com please")
    assert "[REDACTED:email]" in result.redacted_text
    assert result.changed
    assert result.classification_escalation == "pii"


async def test_pii_gate_returns_pydantic_pii_gate_result(ledger, company_id):
    """After Block C, PIIGate.check returns the Pydantic model, not the __slots__ shim."""
    from wormbase_governance.types import PIIGateResult as PydanticResult

    gate = PIIGate(ledger, company_id)
    result = await gate.check("contact me at alice@example.com", {"source": "test"})
    assert isinstance(result, PydanticResult)
    assert result.changed is True
    assert result.classification_escalation == "pii"


async def test_no_slots_pii_gate_result_in_gates_module():
    """The __slots__ class at gates.py:28-43 is gone after Block C."""
    import wormbase_governance.gates as gates_mod
    from wormbase_governance.types import PIIGateResult

    # PIIGateResult is still importable, but it must be the Pydantic one.
    assert gates_mod.PIIGateResult is PIIGateResult


async def test_pii_gate_redacts_postgres_uri(ledger, company_id):
    gate = PIIGate(ledger, company_id)
    result = await gate.check("postgres://user:secret@db/prod")
    assert "[REDACTED:db_uri_postgres]" in result.redacted_text
    assert result.classification_escalation == "regulated"


async def test_pii_gate_credit_card_luhn_check(ledger, company_id):
    gate = PIIGate(ledger, company_id)
    # 4111111111111111 is a valid Luhn test number.
    valid = await gate.check("card is 4111111111111111")
    assert valid.changed
    invalid = await gate.check("card is 4111111111111112")
    # The 16-digit string still hits the regex but Luhn fails -> not redacted.
    assert "4111111111111112" in invalid.redacted_text


async def test_pii_gate_leaves_clean_text_unchanged(ledger, company_id):
    gate = PIIGate(ledger, company_id)
    result = await gate.check("the team is happy this quarter")
    assert not result.changed
    assert result.redacted_text == "the team is happy this quarter"


async def test_pii_gate_writes_gate_fired_entry(ledger, company_id):
    gate = PIIGate(ledger, company_id)
    await gate.check("call alice@example.com asap")
    rows = await ledger.fetch(company_id)
    assert any(
        r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_gate_fired"
        and r["payload"]["args"]["gate"] == "pii"
        for r in rows
    )


async def test_pii_gate_match_carries_only_hash_not_raw(ledger, company_id):
    gate = PIIGate(ledger, company_id)
    result = await gate.check("alice@example.com")
    assert all("alice@example.com" not in str(m) for m in result.matches)
    for m in result.matches:
        assert "original_hash" in m
        assert len(m["original_hash"]) == 64  # SHA-256 hex


# ---- Warmup gate ---------------------------------------------------


class _StubRamp:
    def __init__(self, schema_value: float):
        self.schema = schema_value


async def test_warmup_gate_blocks_under_threshold(ledger, company_id):
    async def reader(_cid):
        return _StubRamp(25)

    gate = WarmupGate(reader, ledger, company_id, threshold_schema=50)
    decision = await gate.check("active")
    assert not decision.allow
    assert "warmup_schema_under" in decision.reason


async def test_warmup_gate_allows_passive_always(ledger, company_id):
    async def reader(_cid):
        return _StubRamp(0)

    gate = WarmupGate(reader, ledger, company_id, threshold_schema=50)
    decision = await gate.check("passive")
    assert decision.allow


async def test_warmup_gate_unblocks_above_threshold(ledger, company_id):
    async def reader(_cid):
        return _StubRamp(75)

    gate = WarmupGate(reader, ledger, company_id, threshold_schema=50)
    decision = await gate.check("active")
    assert decision.allow


# ---- Interjection gate ---------------------------------------------


async def test_interjection_gate_first_three_pass(ledger, company_id, clock):
    gate = InterjectionGate(ledger, company_id, clock=clock)
    for _ in range(3):
        assert await gate.allow("C1", "clarification")


async def test_interjection_gate_fourth_blocks(ledger, company_id, clock):
    gate = InterjectionGate(ledger, company_id, clock=clock)
    for _ in range(3):
        await gate.allow("C1", "clarification")
    assert not await gate.allow("C1", "clarification")


async def test_interjection_gate_separate_per_channel(ledger, company_id, clock):
    gate = InterjectionGate(ledger, company_id, clock=clock)
    for _ in range(3):
        await gate.allow("C1", "clarification")
    # C2 starts fresh.
    assert await gate.allow("C2", "clarification")


async def test_interjection_gate_statements_uncounted(ledger, company_id, clock):
    gate = InterjectionGate(ledger, company_id, clock=clock)
    for _ in range(5):
        assert await gate.allow("C1", "statement")


async def test_interjection_gate_resets_at_midnight_utc(ledger, company_id, clock):
    gate = InterjectionGate(ledger, company_id, clock=clock)
    for _ in range(3):
        await gate.allow("C1", "clarification")
    assert not await gate.allow("C1", "clarification")
    # Advance past midnight UTC.
    clock.tick(days=1)
    assert await gate.allow("C1", "clarification")


# ---- Knowledge gate ------------------------------------------------


async def test_knowledge_gate_allows_when_all_known_and_defined(ledger, company_id):
    gate = KnowledgeGate(["churn"], ["churn"], ledger, company_id)
    decision = await gate.check(["churn"])
    assert decision.allow


async def test_knowledge_gate_blocks_on_unknown_concept(ledger, company_id):
    gate = KnowledgeGate(["churn"], ["churn"], ledger, company_id)
    decision = await gate.check(["new_metric"])
    assert not decision.allow
    assert "missing_knowledge" in decision.reason
    assert "clarify:" in (decision.suggested_action or "")


async def test_knowledge_gate_blocks_on_undefined_concept(ledger, company_id):
    gate = KnowledgeGate(["churn"], [], ledger, company_id)
    decision = await gate.check(["churn"])
    assert not decision.allow


async def test_knowledge_gate_empty_query_allow(ledger, company_id):
    gate = KnowledgeGate(["churn"], ["churn"], ledger, company_id)
    decision = await gate.check([])
    assert decision.allow
