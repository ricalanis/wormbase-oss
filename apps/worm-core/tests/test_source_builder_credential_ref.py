"""Source-builder credential_ref threading — opaque-secret production path.

Closes carry-forward #1 from the 2026-06-10 CredentialBroker integration
close-out (``2026-06-10-credential-broker-integration-shipped.md``).
Before this bundle the only way ``credential_ref`` reached the ledger
was via direct ledger writes (ASML demo seeds, integration tests). This
test pins the production flow:

  * ``SourceBuilder.connect()`` accepts an additive ``credential_ref``
    kwarg (default None preserves byte-identical behavior).
  * ``build_full_sequence()`` forwards the same kwarg.
  * The ledger entry's ``emit_source_connected.args`` carries the
    ``credential_ref`` payload field for downstream provider folds.
  * Opaque-secret URIs (stripe / salesforce / hubspot / gsheets)
    without a credential_ref log a warning at connect()-time (visible
    in the harness logs; auditable post-hoc).
  * URI-shaped kinds (csv_local / postgres / etc.) connect cleanly
    with or without credential_ref — the field is ignored at sampling
    time for them.
  * End-to-end: builder.connect(credential_ref=...) → ledger fold →
    LedgerSourceHandleProvider.get_handle → broker.hold_data_account
    → AuthHandle assembled; default OFF when broker is None.

The drift test pins the local opaque-URI scheme set in source_builder
against the registry in source_handle_provider so the two never
silently diverge.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import (
    SourceConnectedPayload,
    SourceProposedPayload,
)

from wormbase_core.source_builder import (
    SourceBuilder,
    SourceProposal,
    _looks_opaque_secret,
    _OPAQUE_URI_SCHEMES,
    build_full_sequence,
)
from wormbase_core.source_handle_provider import (
    OPAQUE_AUTH_HANDLE_ASSEMBLERS,
    LedgerSourceHandleProvider,
    SourceHandleRecord,
)


_TENANT = UUID("00000000-0000-0000-0000-0000000ccc01")


def _make_proposal(
    company_id: UUID,
    *,
    uri: str = "s3://bucket/data.csv",
    proposed_type: str = "file",
    correlation_id: str | None = None,
) -> SourceProposal:
    return SourceProposal(
        proposed_uri=uri,
        proposed_type=proposed_type,  # type: ignore[arg-type]
        proposed_domain="finance",
        proposed_classification="internal",
        proposed_owner_person_id=uuid4(),
        added_by_person_id=uuid4(),
        added_via_flow="drop_and_profile",
        added_in_response_to="msg:test",
        correlation_id=correlation_id or str(uuid4()),
        company_id=company_id,
    )


# ---------------------------------------------------------------------------
# A. Default-None preserves byte-identical behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_without_credential_ref_writes_none_field(
    ledger: Any, company_id: UUID, clock: Any,
) -> None:
    """Default-None preserves byte-identical pre-2026-06-10 behavior.

    The ledger entry must carry ``credential_ref: None`` (or absent —
    accepting both forms is the back-compat contract per
    ``SourceConnectedPayload.credential_ref = None`` default).
    """
    builder = SourceBuilder(ledger, clock)
    cid = await builder.propose(_make_proposal(company_id))
    await builder.confirm(str(cid), uuid4(), uuid4(), "internal")
    # Call with the existing 2-arg form — must keep working.
    await builder.connect(str(cid), "handle-1")

    rows = await ledger.fetch(company_id)
    connected = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_connected"
    ]
    assert len(connected) == 1
    args = connected[0]["payload"]["args"]
    # SourceConnectedPayload.model_dump emits credential_ref=None when
    # the field is unset; the provider treats None as "no broker path".
    assert args.get("credential_ref") is None


# ---------------------------------------------------------------------------
# B. credential_ref kwarg is threaded into the ledger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_with_credential_ref_writes_it_to_ledger(
    ledger: Any, company_id: UUID, clock: Any,
) -> None:
    """credential_ref kwarg must land in the emit_source_connected args."""
    builder = SourceBuilder(ledger, clock)
    cid = await builder.propose(_make_proposal(company_id))
    await builder.confirm(str(cid), uuid4(), uuid4(), "internal")
    await builder.connect(
        str(cid), "handle-1", credential_ref="vault://stripe-prod",
    )

    rows = await ledger.fetch(company_id)
    connected = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_connected"
    ]
    assert len(connected) == 1
    args = connected[0]["payload"]["args"]
    assert args["credential_ref"] == "vault://stripe-prod"
    # Other fields preserved.
    assert args["connection_ref"] == "handle-1"
    assert args["correlation_id"] == str(cid)


# ---------------------------------------------------------------------------
# C. build_full_sequence forwards credential_ref
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_full_sequence_threads_credential_ref(
    ledger: Any, company_id: UUID, clock: Any,
) -> None:
    """build_full_sequence's new credential_ref kwarg lands on the ledger."""
    builder = SourceBuilder(ledger, clock)
    proposal = _make_proposal(company_id)
    cid = await build_full_sequence(
        builder, proposal,
        confirmer_id=uuid4(),
        domain_id=uuid4(),
        classification="internal",
        connection_fn=lambda: "conn-x",
        profile_fn=lambda: {
            "row_count": 1,
            "column_count": 1,
            "schema_hash": "h",
            "profile_ref": "p",
        },
        credential_ref="env://STRIPE_PROD",
    )
    rows = await ledger.fetch(company_id)
    connected = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_connected"
    ]
    assert connected[0]["payload"]["args"]["credential_ref"] == (
        "env://STRIPE_PROD"
    )
    assert str(cid)


@pytest.mark.asyncio
async def test_build_full_sequence_default_credential_ref_is_none(
    ledger: Any, company_id: UUID, clock: Any,
) -> None:
    """Omitting credential_ref keeps existing callers byte-identical."""
    builder = SourceBuilder(ledger, clock)
    proposal = _make_proposal(company_id)
    await build_full_sequence(
        builder, proposal,
        confirmer_id=uuid4(),
        domain_id=uuid4(),
        classification="internal",
        connection_fn=lambda: "conn-y",
        profile_fn=lambda: {
            "row_count": 1,
            "column_count": 1,
            "schema_hash": "h",
            "profile_ref": "p",
        },
    )
    rows = await ledger.fetch(company_id)
    connected = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_connected"
    ]
    assert connected[0]["payload"]["args"].get("credential_ref") is None


# ---------------------------------------------------------------------------
# D. Opaque-secret warning posture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opaque_secret_connect_without_ref_logs_warning(
    ledger: Any, company_id: UUID, clock: Any, caplog: pytest.LogCaptureFixture,
) -> None:
    """Connecting an opaque-secret URI without credential_ref must warn.

    Honest-empty posture: the entry is still written (operator may
    paste the ref later), but the warning fires so the gap is
    auditable in the harness logs and post-hoc trace queries.
    """
    builder = SourceBuilder(ledger, clock)
    cid = await builder.propose(
        _make_proposal(
            company_id,
            uri="stripe://acct_test",
            proposed_type="rest_api",
        ),
    )
    await builder.confirm(str(cid), uuid4(), uuid4(), "internal")
    with caplog.at_level(logging.WARNING, logger="wormbase_core.source_builder"):
        await builder.connect(str(cid), "stripe-handle")
    # Warning must mention the URI and the missing-ref reason.
    warnings = [
        r for r in caplog.records
        if r.levelno >= logging.WARNING
        and r.name == "wormbase_core.source_builder"
    ]
    assert len(warnings) == 1
    msg = warnings[0].getMessage().lower()
    assert "credential_ref" in msg
    assert "stripe" in msg
    # Entry still written.
    rows = await ledger.fetch(company_id)
    connected = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_connected"
    ]
    assert len(connected) == 1


@pytest.mark.asyncio
async def test_opaque_secret_connect_with_ref_does_not_warn(
    ledger: Any, company_id: UUID, clock: Any, caplog: pytest.LogCaptureFixture,
) -> None:
    """Supplying credential_ref silences the opaque-secret warning."""
    builder = SourceBuilder(ledger, clock)
    cid = await builder.propose(
        _make_proposal(
            company_id,
            uri="stripe://acct_test",
            proposed_type="rest_api",
        ),
    )
    await builder.confirm(str(cid), uuid4(), uuid4(), "internal")
    with caplog.at_level(logging.WARNING, logger="wormbase_core.source_builder"):
        await builder.connect(
            str(cid), "stripe-handle", credential_ref="stripe-prod",
        )
    warnings = [
        r for r in caplog.records
        if r.levelno >= logging.WARNING
        and r.name == "wormbase_core.source_builder"
    ]
    assert warnings == []


@pytest.mark.asyncio
async def test_uri_shaped_connect_without_ref_does_not_warn(
    ledger: Any, company_id: UUID, clock: Any, caplog: pytest.LogCaptureFixture,
) -> None:
    """URI-shaped kinds (s3, csv) don't warn — they don't need broker."""
    builder = SourceBuilder(ledger, clock)
    cid = await builder.propose(
        _make_proposal(
            company_id,
            uri="s3://bucket/data.csv",
            proposed_type="file",
        ),
    )
    await builder.confirm(str(cid), uuid4(), uuid4(), "internal")
    with caplog.at_level(logging.WARNING, logger="wormbase_core.source_builder"):
        await builder.connect(str(cid), "s3-handle")
    warnings = [
        r for r in caplog.records
        if r.levelno >= logging.WARNING
        and r.name == "wormbase_core.source_builder"
    ]
    assert warnings == []


# ---------------------------------------------------------------------------
# E. Opaque-scheme set drift-pin against source_handle_provider registry
# ---------------------------------------------------------------------------


def test_opaque_uri_schemes_match_handle_provider_registry() -> None:
    """The local opaque-URI scheme set must mirror the provider registry.

    Drift here would mean the builder either:
      * Warns for kinds the sampler doesn't actually treat as opaque
        (false-positive warning noise).
      * Stays silent for kinds the sampler DOES treat as opaque
        (operator misses a real gap).

    Both are bad; keeping these in lockstep is the contract.
    """
    assert _OPAQUE_URI_SCHEMES == set(OPAQUE_AUTH_HANDLE_ASSEMBLERS.keys())


def test_looks_opaque_secret_predicate_covers_known_kinds() -> None:
    assert _looks_opaque_secret("stripe://acct_test") is True
    assert _looks_opaque_secret("salesforce://acme") is True
    assert _looks_opaque_secret("hubspot://acme") is True
    assert _looks_opaque_secret("gsheets://spreadsheet") is True


def test_looks_opaque_secret_predicate_rejects_uri_shaped() -> None:
    assert _looks_opaque_secret("postgres://localhost/db") is False
    assert _looks_opaque_secret("s3://bucket/data.csv") is False
    assert _looks_opaque_secret("file:///tmp/x.csv") is False
    assert _looks_opaque_secret("/tmp/x.csv") is False
    assert _looks_opaque_secret("") is False


def test_looks_opaque_secret_handles_uppercase_scheme() -> None:
    assert _looks_opaque_secret("STRIPE://acct") is True


# ---------------------------------------------------------------------------
# F. End-to-end production-flow roundtrip
# ---------------------------------------------------------------------------


class _FakeAccountHandle:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload


class _FakeBroker:
    """Minimal CredentialBroker stub keyed by (install_id, upstream_kind)."""

    def __init__(self, secrets: dict[tuple[str, str], dict[str, Any]]) -> None:
        self._secrets = secrets
        self.calls: list[tuple[str, str]] = []

    async def hold_data_account(
        self, install_id: str, *, upstream_kind: str,
    ) -> _FakeAccountHandle:
        self.calls.append((install_id, upstream_kind))
        payload = self._secrets[(install_id, upstream_kind)]
        return _FakeAccountHandle(payload=dict(payload))


async def _seed_source_proposed_with_connector_kind(
    ledger: Any,
    *,
    company_id: UUID,
    source_id: UUID,
    connector_kind: str,
    uri: str,
) -> None:
    """Seed a ``source_proposed`` ledger entry with an explicit connector_kind.

    Today's :class:`SourceBuilder.propose` writes the coarse
    ``SourceKind`` literal (``"file"`` / ``"database"`` / ``"blob"`` /
    ``"rest_api"``) into ``source_proposed.source_kind`` — the field
    type pre-dates the Sampler-activation Wave's connector-kind
    convention. The handle provider expects ``source_kind`` to carry
    the connector registry key (``"stripe"``, ``"csv_local"``, …); see
    :data:`OPAQUE_AUTH_HANDLE_ASSEMBLERS`. Bridging the SourceBuilder
    propose path to write connector-kind would broaden
    :class:`SourceKind`, which is out of scope for this bundle.

    For the closing-arc roundtrip we therefore seed the
    ``source_proposed`` directly with connector_kind (mirroring what
    the production onboarding endpoint will do once it lands — see
    carry-forward note in close-out), then drive the ``connect`` step
    through the builder so its new ``credential_ref`` kwarg gets a
    real run.
    """
    payload = SourceProposedPayload(
        source_id=source_id,
        source_kind=connector_kind,
        uri=uri,
        added_via_flow="drop_and_profile",
        suggested_domain="finance",
        suggested_classification="confidential",
    )
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "source_proposed",
            "ref_id": str(source_id),
            "reason": "test seed (connector_kind)",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_source_proposed",
            "args": payload.model_dump(mode="json"),
            "result_ref": str(source_id),
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}], "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test"},
    )


async def _seed_source_connected_via_builder(
    ledger: Any,
    clock: Any,
    *,
    company_id: UUID,
    source_id: UUID,
    connection_ref: str,
    credential_ref: str | None,
) -> str:
    """Drive ``SourceBuilder.connect`` for a pre-seeded source.

    Bootstraps the builder's in-memory state from a fake ``confirmed``
    stage so ``connect`` can be invoked directly — the connect path is
    the one carrying the new ``credential_ref`` kwarg, which is what
    this e2e test exercises.
    """
    builder = SourceBuilder(ledger, clock)
    correlation_id = str(uuid4())
    proposal = SourceProposal(
        proposed_uri="opaque://provider-bridge",
        proposed_type="rest_api",
        proposed_domain="finance",
        proposed_classification="confidential",
        proposed_owner_person_id=None,
        added_by_person_id=None,
        added_via_flow="drop_and_profile",
        added_in_response_to=None,
        correlation_id=correlation_id,
        company_id=company_id,
    )
    # Wire the builder's per-correlation state into "confirmed" with the
    # pre-seeded source_id so the connect() call lands on the right row.
    builder._state[correlation_id] = "confirmed"  # noqa: SLF001
    builder._proposals[correlation_id] = proposal  # noqa: SLF001
    builder._source_ids[correlation_id] = source_id  # noqa: SLF001
    await builder.connect(
        correlation_id, connection_ref, credential_ref=credential_ref,
    )
    return correlation_id


@pytest.mark.asyncio
async def test_e2e_connect_credential_ref_to_provider_handle(
    ledger: Any, company_id: UUID, clock: Any,
) -> None:
    """Full production roundtrip — builder writes ref, provider resolves it.

    Pins the path that closes carry-forward #1:
      1. SourceBuilder.connect(credential_ref="stripe-acme") writes the
         ledger entry with the field set.
      2. LedgerSourceHandleProvider folds the ledger.
      3. Broker is consulted with install_id=credential_ref.
      4. Per-kind assembler builds the AuthHandle.

    Before this bundle, step 1 wasn't possible from the source-builder
    surface — the field could only be set via direct emit_source_*
    writes from tests / ASML seeds. The proposal is seeded directly
    because today's SourceProposal.proposed_type literal doesn't yet
    carry connector-kind granularity (see the seed helper docstring).
    """
    source_id = UUID("00000000-0000-0000-0000-00000000f001")
    await _seed_source_proposed_with_connector_kind(
        ledger, company_id=company_id, source_id=source_id,
        connector_kind="stripe", uri="stripe://acct_acme",
    )
    await _seed_source_connected_via_builder(
        ledger, clock,
        company_id=company_id, source_id=source_id,
        connection_ref="stripe-handle", credential_ref="stripe-acme",
    )

    broker = _FakeBroker(secrets={
        ("stripe-acme", "stripe"): {
            "api_key": "sk_test_e2e",
            "api_version": "2023-10-16",
        },
    })
    provider = LedgerSourceHandleProvider(
        ledger=ledger, credential_broker=broker,
    )
    record = await provider.get_handle(
        company_id=company_id, source_id=str(source_id),
    )
    assert isinstance(record, SourceHandleRecord)
    assert record.connector_kind == "stripe"
    extra = getattr(record.auth_handle, "extra", {})
    assert extra.get("api_key") == "sk_test_e2e"
    # Verify the broker was actually called — the credential_ref the
    # builder wrote made it all the way to the broker lookup.
    assert broker.calls == [("stripe-acme", "stripe")]


@pytest.mark.asyncio
async def test_e2e_connect_without_credential_ref_yields_none_handle(
    ledger: Any, company_id: UUID, clock: Any,
) -> None:
    """No credential_ref + opaque kind → provider returns None (honest-empty).

    Pins the negative-arm of the same flow: even when a broker is wired,
    an opaque-kind source without credential_ref must surface None so
    the sampler falls back to empty.
    """
    source_id = UUID("00000000-0000-0000-0000-00000000f002")
    await _seed_source_proposed_with_connector_kind(
        ledger, company_id=company_id, source_id=source_id,
        connector_kind="stripe", uri="stripe://acct_acme",
    )
    # No credential_ref — fires the warning but writes the entry.
    await _seed_source_connected_via_builder(
        ledger, clock,
        company_id=company_id, source_id=source_id,
        connection_ref="stripe-handle", credential_ref=None,
    )

    broker = _FakeBroker(secrets={})
    provider = LedgerSourceHandleProvider(
        ledger=ledger, credential_broker=broker,
    )
    record = await provider.get_handle(
        company_id=company_id, source_id=str(source_id),
    )
    assert record is None
    # Broker NOT consulted — provider short-circuits on missing ref.
    assert broker.calls == []


# ---------------------------------------------------------------------------
# G. Existing connect() callers stay byte-identical
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_positional_two_arg_connect_still_works(
    ledger: Any, company_id: UUID, clock: Any,
) -> None:
    """Existing 2-arg ``connect(cid, connection_ref)`` callers unchanged."""
    builder = SourceBuilder(ledger, clock)
    cid = await builder.propose(_make_proposal(company_id))
    await builder.confirm(str(cid), uuid4(), uuid4(), "internal")
    # This is exactly the form drop_and_profile / write_actions use.
    await builder.connect(str(cid), "conn-x")
    rows = await ledger.fetch(company_id)
    connected = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_connected"
    ]
    assert len(connected) == 1
    assert connected[0]["payload"]["args"]["connection_ref"] == "conn-x"


@pytest.mark.asyncio
async def test_keyword_connection_ref_call_still_works(
    ledger: Any, company_id: UUID, clock: Any,
) -> None:
    """``connect(cid_str, connection_ref="...")`` call form (write_actions)."""
    builder = SourceBuilder(ledger, clock)
    cid = await builder.propose(_make_proposal(company_id))
    await builder.confirm(str(cid), uuid4(), uuid4(), "internal")
    await builder.connect(str(cid), connection_ref="local-lake://tenant")
    rows = await ledger.fetch(company_id)
    connected = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_connected"
    ]
    assert connected[0]["payload"]["args"]["connection_ref"] == (
        "local-lake://tenant"
    )
