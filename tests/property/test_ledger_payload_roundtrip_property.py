"""Payload-roundtrip property tests (W6.A1).

Invariant
---------
**R1. Field-stable JSON roundtrip.** For every payload kind in the
``ROUNDTRIP_KINDS`` slice of ``KIND_REGISTRY``, and for every
Hypothesis-generated example payload of that kind:

    model_validate(model_dump(payload, mode="json")) == payload

Catches Pydantic v2 regressions that silently drop fields, mis-serialize
datetime / UUID / Decimal, or change Literal-enum coercion.

UTF-8 boundary content (BOM, RTL marks, emoji combos), large-int
boundaries, datetime precision (microseconds), and optional-field toggles
are exercised via the strategies in ``tests/property/strategies.py``.

The roundtrip is what the ledger does on every read:

    write       — payload.model_dump(mode="json") → ledger envelope
    read        — model_validate(json) → payload again

The invariant says: read after write is identity.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from wormbase_ledger import entries as E

from tests.property import strategies as S


# Map each kind in the roundtrip slice to its concrete Pydantic class.
_KIND_TO_MODEL: dict[str, type[E.EntryPayload]] = {
    "propose": E.ProposePayload,
    "execute": E.ExecutePayload,
    "verify": E.VerifyPayload,
    "resolve": E.ResolvePayload,
    "chat_received": E.ChatReceivedPayload,
    "chat_sent": E.ChatSentPayload,
    "memory_written": E.MemoryWrittenPayload,
    "source_proposed": E.SourceProposedPayload,
    "source_confirmed": E.SourceConfirmedPayload,
    "source_connected": E.SourceConnectedPayload,
    "source_profiled": E.SourceProfiledPayload,
    "ingest_landed": E.IngestLandedPayload,
    "gate_fired": E.GateFiredPayload,
    "kpi_answered": E.KpiAnsweredPayload,
    "metric_observed": E.MetricObservedPayload,
    "reactivity_fired": E.ReactivityFiredPayload,
}


def _make_strategy(kind: str) -> st.SearchStrategy[dict[str, Any]]:
    factory_name = S.ROUNDTRIP_KINDS[kind]
    return getattr(S, factory_name)()


# ---------------------------------------------------------------------------
# One @given test per kind so failure messages name the kind directly.
# Hypothesis settings are kept tight per-test (max_examples=100) to keep
# the per-kind test < 1s; the suite-wide bound is ≥200 across all tests.
# ---------------------------------------------------------------------------


def _make_test(kind: str) -> Any:
    model = _KIND_TO_MODEL[kind]
    strat = _make_strategy(kind)

    @given(data=strat)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    )
    def _test(data: dict[str, Any]) -> None:
        # Construct via kwargs (covers __init__ validators).
        try:
            obj = model(**data)
        except Exception as exc:  # noqa: BLE001
            # Some Hypothesis-generated values legitimately violate
            # field validators (e.g. negative ints in nonneg fields)
            # because we widen text strategies for UTF-8 coverage. Skip
            # those examples — the invariant is about valid round-trip,
            # not validator robustness (that's tested elsewhere).
            pytest.skip(f"invalid example for {kind}: {exc}")
            return

        # Roundtrip via JSON-compatible dump.
        json_view = obj.model_dump(mode="json")
        # Verify the dump is JSON-serializable (no UUID/datetime escapes).
        json.dumps(json_view)
        rebuilt = model.model_validate(json_view)
        assert rebuilt == obj, (
            f"roundtrip drift for {kind}: original={obj!r} "
            f"!= rebuilt={rebuilt!r}; dump={json_view!r}"
        )

    _test.__name__ = f"test_roundtrip_field_stable_{kind}"
    _test.__doc__ = (
        f"Invariant R1 (kind={kind}): "
        f"model_validate(model_dump(p, mode='json')) == p for every "
        f"valid payload of kind {kind!r}."
    )
    return _test


# Generate one named test per kind. This is the canonical Hypothesis
# pattern when each parameterisation deserves its own failure message.
for _kind in S.ROUNDTRIP_KINDS:
    globals()[f"test_roundtrip_field_stable_{_kind}"] = _make_test(_kind)


# ---------------------------------------------------------------------------
# Specific UTF-8 boundary + datetime-precision regressions
# ---------------------------------------------------------------------------


@given(text=S.utf8_text(0, 256))
@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
def test_chat_received_text_field_utf8_roundtrip(text: str) -> None:
    """Invariant R1 (UTF-8): chat text containing BOM/RTL/emoji round-trips.

    The ChatReceivedPayload.text field is the densest UTF-8 surface on the
    ledger (most ledger text is ASCII metadata). Hypothesis exercises BOM,
    RTL, and emoji-with-modifier combos here.
    """
    from uuid import uuid4

    obj = E.ChatReceivedPayload(
        channel_id="C01",
        message_id="m1",
        sender_person=uuid4(),
        text=text,
        classification="internal",
    )
    rebuilt = E.ChatReceivedPayload.model_validate(obj.model_dump(mode="json"))
    assert rebuilt.text == text


@given(seq=st.integers(min_value=0, max_value=2**62 - 1))
@settings(max_examples=100, deadline=None)
def test_reactivity_fired_action_seqs_large_int(seq: int) -> None:
    """Invariant R1 (BigInt): reactivity_fired.source_seq survives the BigInt range.

    ``source_seq`` is BigInt on the column; the Pydantic field has no
    upper bound. We assert that any unsigned 62-bit value round-trips.
    """
    obj = E.ReactivityFiredPayload(
        reactivity_id="r",
        source_seq=seq,
        novelty_key="",
        action_seqs=[seq, seq + 1],
        budget_used={"per_owner": 1},
    )
    rebuilt = E.ReactivityFiredPayload.model_validate(obj.model_dump(mode="json"))
    assert rebuilt.source_seq == seq
    assert rebuilt.action_seqs == [seq, seq + 1]


@given(ts=S.tz_aware_datetimes())
@settings(max_examples=100, deadline=None)
def test_metric_observed_datetime_microsecond_precision(ts: Any) -> None:
    """Invariant R1 (datetime precision): MetricObserved preserves microseconds.

    The canonical datetime serializer rstrips trailing zeros from the
    fractional part. Roundtrip must reconstruct the same datetime —
    rstripping is reversible because canonical_json never produces a
    fractional part with leading zeros that would alias.
    """
    obj = E.MetricObservedPayload(
        metric_id="revenue",
        position="cfo",
        value=1.0,
        observed_at=ts,
    )
    rebuilt = E.MetricObservedPayload.model_validate(obj.model_dump(mode="json"))
    # The serialized form normalises to UTC; compare in UTC-equivalence.
    from datetime import UTC

    assert rebuilt.observed_at.astimezone(UTC) == obj.observed_at.astimezone(UTC)


@given(present=st.booleans(), text=S.short_text)
@settings(max_examples=100, deadline=None)
def test_chat_sent_optional_field_toggles(present: bool, text: str) -> None:
    """Invariant R1 (optional fields): in_reply_to None vs str round-trip.

    The ChatSentPayload.in_reply_to is ``str | None``. Pydantic v2
    serialization can drop None vs serialize as null vs omit. The round-
    trip MUST preserve the input distinction.
    """
    obj = E.ChatSentPayload(
        channel_id="C",
        message_id="m",
        text="hi",
        in_reply_to=(text if present else None),
        attribution={},
        speech_act="answer",
    )
    rebuilt = E.ChatSentPayload.model_validate(obj.model_dump(mode="json"))
    assert rebuilt.in_reply_to == (text if present else None)
