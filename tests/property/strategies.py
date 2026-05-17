"""Reusable Hypothesis strategies for the WormBase ledger property tests.

The strategies here drive every property-based test in ``tests/property/``.
The leverage point of W6.A1 is *strategy quality* — a precisely typed
strategy hits the UTF-8 / int / datetime / UUID boundary cases hand-written
tests miss.

Design notes
------------
* Every datetime is **timezone-aware** (UTC by default). The ledger
  envelope's ``ts`` validator rejects naive datetimes; producing them
  here would be wasted shrinking effort.
* Strings include the BOM (``\\ufeff``), RTL marks (``\\u200f``), and
  emoji combos so canonical-JSON encoding is exercised across the
  Unicode surface that's known-hostile.
* UUIDs use ``hypothesis.strategies.uuids`` which emits v4 by default;
  the budget-rollover test pins explicit v4 vs v7 strategies separately.
* Integer ranges respect the SQLAlchemy BigInteger column boundaries
  the ledger uses, so payloads survive a round-trip through Postgres.

These strategies are imported by every test module under
``tests/property/``. Keep them pure — no I/O, no clock reads.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Primitive strategies
# ---------------------------------------------------------------------------

# Bounded BigInteger range — matches ledger's BigInteger columns. We avoid
# negatives where the payload models constrain to ge=0; per-payload
# strategies tighten this where needed.
_BIGINT_MIN = -(2**62)
_BIGINT_MAX = 2**62 - 1

bounded_int = st.integers(min_value=_BIGINT_MIN, max_value=_BIGINT_MAX)
nonneg_int = st.integers(min_value=0, max_value=_BIGINT_MAX)
short_text = st.text(min_size=0, max_size=64)
medium_text = st.text(min_size=0, max_size=512)


def utf8_text(min_size: int = 0, max_size: int = 64) -> st.SearchStrategy[str]:
    """Text including UTF-8 boundary characters known to break encoders.

    Yields a mix of ASCII, BOMs (``\\ufeff``), RTL marks (``\\u200f``),
    emoji combiners, and astral-plane code points. Canonical-JSON
    encoding must survive these without re-escape drift.
    """
    boundary_chars = st.sampled_from(
        [
            "﻿",  # BOM — invisible-but-corrupting
            "‏",  # right-to-left mark
            "‎",  # left-to-right mark
            "\U0001f47b",  # ghost emoji (astral)
            "\U0001f44d\U0001f3fd",  # thumbs-up + skin tone modifier
            "ñ",
            "中",
            "\x00",  # NUL
        ]
    )
    base = st.text(min_size=min_size, max_size=max_size)
    return st.one_of(
        base,
        st.lists(
            st.one_of(base, boundary_chars),
            min_size=min_size,
            max_size=max(min_size, max_size // 4 + 1),
        ).map("".join),
    )


def tz_aware_datetimes(
    min_year: int = 2000, max_year: int = 2099,
) -> st.SearchStrategy[datetime]:
    """Tz-aware UTC datetimes within a sensible epoch.

    Ledger validators require ``tzinfo`` non-None; serialization uses UTC
    + RFC3339 ``Z`` suffix. Returning UTC-anchored datetimes matches the
    serialized form exactly.
    """
    return st.datetimes(
        min_value=datetime(min_year, 1, 1),
        max_value=datetime(max_year, 12, 31, 23, 59, 59),
        timezones=st.just(UTC),
    )


def hex_str(length: int = 64) -> st.SearchStrategy[str]:
    """Lowercase hex string of fixed length (e.g. sha256 digests)."""
    return st.text(
        alphabet="0123456789abcdef", min_size=length, max_size=length,
    )


# ---------------------------------------------------------------------------
# Stable namespace UUID for v5 derivation in budget-rollover tests
# ---------------------------------------------------------------------------

_RNS = UUID("9c1f7a6e-3b4d-5c2e-8a9f-2b3c4d5e6f70")


def uuids_v4() -> st.SearchStrategy[UUID]:
    return st.uuids(version=4)


def uuids_v7_like() -> st.SearchStrategy[UUID]:
    """Approximate UUID v7: timestamp-prefixed, sortable.

    Hypothesis doesn't expose v7 directly. This synthesizes a deterministic
    "v7-like" UUID by taking a millisecond timestamp + random suffix; it's
    enough to verify that the budget-rollover code is agnostic to the UUID
    layout.
    """

    def _build(t: int, r: int) -> UUID:
        # 48 bits of unix-ms timestamp + 80 bits of random — packed into 128.
        ts_part = (t & ((1 << 48) - 1)) << 80
        ver_part = 0x7 << 76  # version 7 nibble
        rand_part = r & ((1 << 76) - 1)
        return UUID(int=ts_part | ver_part | rand_part)

    return st.builds(
        _build,
        st.integers(min_value=0, max_value=(1 << 48) - 1),
        st.integers(min_value=0, max_value=(1 << 76) - 1),
    )


# ---------------------------------------------------------------------------
# Payload-shape strategies for every kind in KIND_REGISTRY
# ---------------------------------------------------------------------------
#
# These intentionally reproduce the on-the-wire dict shape (model_dump
# output), not the constructor kwargs. The roundtrip test consumes
# ``model_validate(model_dump(...)) == original`` so we feed the validator
# exactly what model_dump would emit.

# Reusable enums.
_QUADRANTS = st.sampled_from(
    [
        "passive_deterministic",
        "passive_probabilistic",
        "active_deterministic",
        "active_probabilistic",
    ]
)
_CLASSIFICATIONS = st.sampled_from(
    ["public", "internal", "confidential", "pii", "regulated"]
)
_FLOWS = st.sampled_from(
    [
        "drop_and_profile",
        "credential_offered_in_dm",
        "mentioned_in_conversation",
        "dashboard_form",
        "kpi_gap_triggered",
        "lake_discovery",
        "provisioned_at_install",
    ]
)
_SPEECH_ACTS = st.sampled_from(
    ["introduction", "clarification", "proposal", "answer", "digest"]
)


def propose_payload() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "target_kind": short_text,
            "ref_id": uuids_v4(),
            "reason": utf8_text(),
            "proposed_by": utf8_text(),
        }
    )


def execute_payload() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "propose_entry_id": uuids_v4(),
            "tool": short_text,
            "args": st.dictionaries(short_text, utf8_text(), max_size=4),
            "result_ref": short_text,
        }
    )


def verify_payload() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "execute_entry_id": uuids_v4(),
            "checks": st.lists(
                st.fixed_dictionaries(
                    {"name": short_text, "passed": st.booleans()}
                ),
                max_size=4,
            ),
            "passed": st.booleans(),
        }
    )


def resolve_payload() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "verify_entry_id": uuids_v4(),
            "outcome": st.sampled_from(["keep", "discard"]),
            "rationale": utf8_text(),
        }
    )


def chat_received_payload() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "channel_id": short_text,
            "message_id": short_text,
            "sender_person": uuids_v4(),
            "text": utf8_text(0, 256),
            "classification": _CLASSIFICATIONS,
        }
    )


def chat_sent_payload() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "channel_id": short_text,
            "message_id": short_text,
            "text": utf8_text(0, 256),
            "in_reply_to": st.one_of(st.none(), short_text),
            "attribution": st.dictionaries(short_text, utf8_text(), max_size=3),
            "speech_act": _SPEECH_ACTS,
        }
    )


def memory_written_payload() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "memory_id": uuids_v4(),
            "content": utf8_text(0, 256),
            "tags": st.lists(short_text, max_size=4),
        }
    )


def source_proposed_payload() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "source_id": uuids_v4(),
            "source_kind": st.sampled_from(["file", "database", "blob"]),
            "uri": utf8_text(1, 64),
            "added_via_flow": _FLOWS,
            "suggested_domain": short_text,
            "suggested_classification": _CLASSIFICATIONS,
        }
    )


def source_confirmed_payload() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "source_id": uuids_v4(),
            "confirmed_by_person": uuids_v4(),
            "domain_id": uuids_v4(),
            "classification": _CLASSIFICATIONS,
        }
    )


def source_connected_payload() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "source_id": uuids_v4(),
            "connection_ref": short_text,
            "connected_at": tz_aware_datetimes(),
        }
    )


def source_profiled_payload() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "source_id": uuids_v4(),
            "row_count": nonneg_int,
            "column_count": nonneg_int,
            "schema_hash": hex_str(64),
            "profile_ref": short_text,
        }
    )


def ingest_landed_payload() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "source_id": uuids_v4(),
            "object_uri": short_text,
            "bytes": nonneg_int,
            "row_count": nonneg_int,
        }
    )


def gate_fired_payload() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "gate": short_text,
            "outcome": st.sampled_from(["allowed", "blocked", "warned"]),
            "subject_ref": short_text,
            "reason": utf8_text(),
        }
    )


def kpi_answered_payload() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "question": utf8_text(),
            "answer": utf8_text(),
            "sql_ref": short_text,
            "answer_hash": hex_str(64),
            "sources": st.lists(uuids_v4(), max_size=3),
        }
    )


def metric_observed_payload() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "metric_id": short_text,
            "position": short_text,
            "value": st.floats(
                allow_nan=False, allow_infinity=False, min_value=-1e9, max_value=1e9,
            ),
            "observed_at": tz_aware_datetimes(),
            "source_id": st.one_of(st.none(), uuids_v4()),
        }
    )


def reactivity_fired_payload() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "reactivity_id": short_text.filter(lambda s: bool(s)),
            "source_seq": nonneg_int,
            "novelty_key": short_text,
            "action_seqs": st.lists(nonneg_int, max_size=4),
            "budget_used": st.dictionaries(short_text, nonneg_int, max_size=3),
        }
    )


# ---------------------------------------------------------------------------
# Map kind → (payload_factory, model_class) for the roundtrip sweep.
# ---------------------------------------------------------------------------
#
# We don't sweep ALL_KINDS — many kinds have bespoke validators (UUID
# audience suffixes, opaque oauth_grant_ref prefixes, hand-rolled enums)
# that would explode the strategy surface. The set below is the
# representative slice covering: every primitive shape (Propose / Execute
# / Verify / Resolve), every datetime field, every Literal enum, every
# UTF-8-loaded text field, every BigInteger field. New kinds added later
# are validated by the targeted entry tests in
# ``packages/ledger/tests/test_entries_*.py``.

ROUNDTRIP_KINDS: dict[str, str] = {
    # mapping kind → factory function name (looked up at call time so
    # the strategies module can import without ``entries`` having been
    # imported first).
    "propose": "propose_payload",
    "execute": "execute_payload",
    "verify": "verify_payload",
    "resolve": "resolve_payload",
    "chat_received": "chat_received_payload",
    "chat_sent": "chat_sent_payload",
    "memory_written": "memory_written_payload",
    "source_proposed": "source_proposed_payload",
    "source_confirmed": "source_confirmed_payload",
    "source_connected": "source_connected_payload",
    "source_profiled": "source_profiled_payload",
    "ingest_landed": "ingest_landed_payload",
    "gate_fired": "gate_fired_payload",
    "kpi_answered": "kpi_answered_payload",
    "metric_observed": "metric_observed_payload",
    "reactivity_fired": "reactivity_fired_payload",
}


# ---------------------------------------------------------------------------
# Ledger-row strategy used by hash-chain + projection-determinism tests.
# ---------------------------------------------------------------------------


def _entry_envelope_for(
    company_id: UUID,
    seq: int,
    prev_hash: bytes,
    kind: str,
    quadrant: str,
    payload: dict[str, Any],
    ts: datetime,
) -> dict[str, Any]:
    """Build a hash-chained envelope around an arbitrary payload.

    Used by hash-chain property tests to produce well-formed, contiguous
    chains. The hash field is computed via the canonical encoder so the
    test's assertion (``compute_entry_hash(entry) == entry["hash"]``)
    holds end-to-end.
    """
    from wormbase_ledger.hash_chain import compute_entry_hash

    entry = {
        "entry_id": uuid4(),
        "company_id": company_id,
        "seq": seq,
        "ts": ts,
        "kind": kind,
        "quadrant": quadrant,
        "payload": payload,
        "prev_hash": prev_hash,
    }
    entry["hash"] = compute_entry_hash(entry)
    return entry


def chained_ledger_rows(
    *, company_id: UUID, n_min: int = 1, n_max: int = 50,
) -> st.SearchStrategy[list[dict[str, Any]]]:
    """Hypothesis strategy producing a chain of N hash-linked ledger rows.

    Rows are seq-contiguous from 1..N, each ``prev_hash`` matches the
    prior entry's ``hash``, and ``hash == compute_entry_hash(entry)``.
    The chain is canonical so ``verify_chain`` returns ``(True, None)``
    without further work.
    """
    from wormbase_ledger.hash_chain import GENESIS_PREV_HASH

    @st.composite
    def _build(draw: st.DrawFn) -> list[dict[str, Any]]:
        n = draw(st.integers(min_value=n_min, max_value=n_max))
        rows: list[dict[str, Any]] = []
        prev = GENESIS_PREV_HASH
        # Use a single base ts and add increments so the chain is
        # monotonic in time; the hash chain doesn't require it but the
        # invariant is easier to reason about.
        base = draw(tz_aware_datetimes())
        for i in range(1, n + 1):
            kind = draw(
                st.sampled_from(
                    ["propose", "execute", "verify", "resolve",
                     "chat_received", "memory_written", "source_proposed"]
                )
            )
            quadrant = draw(_QUADRANTS)
            payload = draw(
                st.one_of(
                    propose_payload(),
                    execute_payload(),
                    verify_payload(),
                    resolve_payload(),
                    chat_received_payload(),
                    memory_written_payload(),
                    source_proposed_payload(),
                )
            )
            ts = base + timedelta(seconds=i)
            entry = _entry_envelope_for(
                company_id=company_id,
                seq=i,
                prev_hash=prev,
                kind=kind,
                quadrant=quadrant,
                payload=payload,
                ts=ts,
            )
            rows.append(entry)
            prev = entry["hash"]
        return rows

    return _build()


__all__ = [
    "ROUNDTRIP_KINDS",
    "bounded_int",
    "chained_ledger_rows",
    "chat_received_payload",
    "chat_sent_payload",
    "execute_payload",
    "gate_fired_payload",
    "hex_str",
    "ingest_landed_payload",
    "kpi_answered_payload",
    "memory_written_payload",
    "metric_observed_payload",
    "nonneg_int",
    "propose_payload",
    "reactivity_fired_payload",
    "resolve_payload",
    "short_text",
    "source_confirmed_payload",
    "source_connected_payload",
    "source_profiled_payload",
    "source_proposed_payload",
    "tz_aware_datetimes",
    "utf8_text",
    "uuids_v4",
    "uuids_v7_like",
    "verify_payload",
]
