# > AUTHORED 2026-05-06 (Wave B2 — first-class WhatsApp identity discovery):
# > parallel-track tests mirroring test_unknown_platform_id_reactivity.py.
# > Every test exercises only the WhatsApp Reactivity unless it explicitly
# > pins the no-regression Slack contract.
"""WhatsAppOrganicDiscoveryReactivity tests.

Pin the contract that:

  1. New WhatsApp DM jids → ``emit_person_proposed`` PEVR cycle written;
     display_name is ``+<phone>``; ``proposed_by="worm:whatsapp_organic_discovery"``.
  2. Same jid second message → no double-propose (LRU cache hit).
  3. Cache cleared, jid already in ledger → no double-propose
     (ledger-fold safety net).
  4. Group message with ``key.participant=<phone>@s.whatsapp.net`` →
     person_proposed for the participant (the per-message extraction in
     :meth:`WhatsAppChannelAdapter._normalize_message` already substitutes
     the participant jid for the platform_user_id, so this test pins that
     contract from the channel-adapter side without coupling to it).
  5. Group jid alone (no participant — pure observation) → no Person
     proposed (defensive: ``@g.us`` jids never propose).
  6. Slack ``chat_received`` → still triggers Slack discovery path
     (no regression).
  7. Multi-tenant: same jid across two ``company_id``s → person_proposed
     per company (the cache is per-(company, jid) key; the ledger fold
     is company-scoped).

These tests intentionally use small, focused seeders rather than the
full WhatsAppChannelAdapter — the adapter is in a separate package,
and the contract this Reactivity guarantees is "given a chat_received
ledger entry shaped like X, write a person_proposed entry shaped like
Y." Coupling to the adapter would tangle the test surface.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import (
    ChatReceivedPayload,
    IdentityLinkedPayload,
    PersonProposedPayload,
)
from wormbase_reactivities import ReactivityRegistry, ReactivityRunner

from wormbase_identity_tracker.reactivities import UnknownPlatformIdReactivity
from wormbase_identity_tracker.whatsapp_discovery import (
    WhatsAppOrganicDiscoveryReactivity,
)


# ---------------------------------------------------------------------------
# Helpers — mirror test_unknown_platform_id_reactivity.py shape so future
# maintainers see the parallel and don't drift.
# ---------------------------------------------------------------------------


async def _seed_chat_received(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    platform: str,
    platform_user_id: str | None,
    channel_id: str = "120363000000000000@g.us",
    text: str = "hi",
) -> None:
    """Seed a ``channel_adapter.emit_chat_received`` row.

    Mirrors the ``platform`` + ``platform_user_id`` args the WhatsApp
    channel-adapter writes — including the case where ``platform_user_id``
    is None (pure-observation entry, e.g. group-jid with no participant).
    """
    payload = ChatReceivedPayload(
        channel_id=channel_id,
        message_id=str(uuid4()),
        sender_person=uuid4(),
        text=text,
        classification="internal",
    )
    args = payload.model_dump(mode="json")
    args["platform"] = platform
    args["platform_user_id"] = platform_user_id

    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "chat_received",
            "ref_id": args["message_id"],
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "channel_adapter.emit_chat_received",
            "args": args,
            "result_ref": args["message_id"],
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


async def _seed_person_proposed(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    platform: str,
    platform_user_id: str,
    name: str = "+5491100000000",
    email: str | None = None,
    proposed_by: str = "worm:whatsapp_organic_discovery",
) -> UUID:
    """Seed a pre-existing ``emit_person_proposed`` cycle.

    Used by the "ledger-fold safety net" test where the LRU is empty
    but the ledger already has a Person for this jid.
    """
    pid = uuid4()
    payload = PersonProposedPayload(
        person_id=pid,
        tenant_id=company_id,
        name=name,
        email=email,
        platform=platform,
        platform_user_id=platform_user_id,
        proposed_by=proposed_by,
    )
    args = payload.model_dump(mode="json")
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "person_proposed",
            "ref_id": str(pid),
            "reason": "test seed pre-existing",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_person_proposed",
            "args": args,
            "result_ref": str(pid),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )
    return pid


async def _seed_identity_linked(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    person_id: UUID,
    platform: str,
    platform_user_id: str,
) -> None:
    """Seed an ``emit_identity_linked`` for an existing Person."""
    payload = IdentityLinkedPayload(
        person_id=person_id,
        platform=platform,
        platform_user_id=platform_user_id,
        linked_by=uuid4(),
    )
    args = payload.model_dump(mode="json")
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "identity_linked",
            "ref_id": str(person_id),
            "reason": "test seed identity link",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_identity_linked",
            "args": args,
            "result_ref": str(person_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )


def _person_proposals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter the ledger to ``emit_person_proposed`` execute rows."""
    out: list[dict[str, Any]] = []
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") == "emit_person_proposed":
            out.append(r)
    return out


async def _drive_via_whatsapp_reactivity(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    reactivity: WhatsAppOrganicDiscoveryReactivity | None = None,
) -> WhatsAppOrganicDiscoveryReactivity:
    """Drive the WhatsApp Reactivity once over the current ledger state.

    Optionally accepts a pre-constructed Reactivity so multi-call tests
    can share its in-process LRU across runner invocations (mirroring the
    "registered once, fired many" production posture).
    """
    if reactivity is None:
        reactivity = WhatsAppOrganicDiscoveryReactivity()
    registry = ReactivityRegistry(ledger=ledger, company_id=company_id)
    registry.register(reactivity)
    runner = ReactivityRunner(
        ledger=ledger, company_id=company_id, registry=registry,
        poll_interval_s=0.01,
    )
    await runner.run_once()
    return reactivity


# ---------------------------------------------------------------------------
# 1. New WhatsApp DM jid → propose_person with phone-prefix display name
# ---------------------------------------------------------------------------


async def test_new_whatsapp_dm_jid_proposes_person_with_phone_prefix_name(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    jid = "5491100000000@s.whatsapp.net"
    await _seed_chat_received(
        ledger, company_id,
        platform="whatsapp", platform_user_id=jid,
        channel_id=jid,  # DM: channel == sender's jid
        text="hello",
    )

    await _drive_via_whatsapp_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    proposals = _person_proposals(rows)
    assert len(proposals) == 1
    args = proposals[0]["payload"]["args"]
    assert args["platform"] == "whatsapp"
    assert args["platform_user_id"] == jid
    assert args["name"] == "+5491100000000"
    assert args["email"] is None
    assert args["proposed_by"] == "worm:whatsapp_organic_discovery"
    assert args.get("position") is None

    # Verify a full PEVR cycle landed (4 entries).
    pid = args["person_id"]
    rows_sorted = sorted(rows, key=lambda r: r["seq"])
    propose_idx: int | None = None
    for i, r in enumerate(rows_sorted):
        if r.get("kind") != "propose":
            continue
        body = r.get("payload") or {}
        if (
            body.get("ref_id") == pid
            and body.get("target_kind") == "person_proposed"
            and body.get("proposed_by") == "worm:whatsapp_organic_discovery"
        ):
            propose_idx = i
            break
    assert propose_idx is not None, (
        "WhatsApp Reactivity did not emit a propose row with ref_id=person_id"
    )
    pevr_kinds = [r["kind"] for r in rows_sorted[propose_idx:propose_idx + 4]]
    assert pevr_kinds == ["propose", "execute", "verify", "resolve"], (
        f"expected full PEVR cycle, got {pevr_kinds}"
    )
    # Verify row carries the Pydantic-validation check from
    # write_actions._pevr — confirms the write went through propose_person.
    verify_row = rows_sorted[propose_idx + 2]
    checks = verify_row["payload"].get("checks") or []
    assert checks and checks[0]["name"] == "emit_person_proposed_payload_valid"
    assert checks[0]["ok"] is True


# ---------------------------------------------------------------------------
# 2. Same jid second message → cache hit, no double-propose
# ---------------------------------------------------------------------------


async def test_same_jid_second_message_does_not_double_propose(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    jid = "15555550100@s.whatsapp.net"
    reactivity = WhatsAppOrganicDiscoveryReactivity()

    # First chat → propose.
    await _seed_chat_received(
        ledger, company_id,
        platform="whatsapp", platform_user_id=jid, channel_id=jid,
    )
    await _drive_via_whatsapp_reactivity(
        ledger, company_id, reactivity=reactivity,
    )
    rows_after_first = await ledger.fetch(company_id)
    assert len(_person_proposals(rows_after_first)) == 1

    # Cache should now contain the jid (per-tenant key).
    assert (str(company_id), jid) in reactivity.seen_jids

    # Second chat from same jid → no new propose (cache hit).
    await _seed_chat_received(
        ledger, company_id,
        platform="whatsapp", platform_user_id=jid, channel_id=jid,
        text="another message",
    )
    await _drive_via_whatsapp_reactivity(
        ledger, company_id, reactivity=reactivity,
    )
    rows_after_second = await ledger.fetch(company_id)
    assert len(_person_proposals(rows_after_second)) == 1


# ---------------------------------------------------------------------------
# 3. Cache cleared, jid already in ledger → ledger-fold safety net
# ---------------------------------------------------------------------------


async def test_cache_cleared_but_ledger_has_jid_does_not_double_propose(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Fresh process boot: LRU empty, but ledger already has the proposal.

    Mirrors the Wave A2 ``WhatsAppLogCapture._has_existing_policy``
    posture — the in-process cache is a fast path; the ledger fold is
    the correctness guarantee.
    """
    jid = "447700900100@s.whatsapp.net"
    # Pre-seed an existing person_proposed for this jid.
    await _seed_person_proposed(
        ledger, company_id,
        platform="whatsapp", platform_user_id=jid,
        name="+447700900100",
    )

    # Now an inbound chat arrives from the same jid.
    await _seed_chat_received(
        ledger, company_id,
        platform="whatsapp", platform_user_id=jid, channel_id=jid,
    )

    # Fresh Reactivity instance (LRU empty).
    reactivity = WhatsAppOrganicDiscoveryReactivity()
    assert reactivity.seen_jids == set()  # empty cache

    await _drive_via_whatsapp_reactivity(
        ledger, company_id, reactivity=reactivity,
    )

    rows = await ledger.fetch(company_id)
    proposals = _person_proposals(rows)
    # Only the pre-seeded proposal — no double-write from the Reactivity.
    assert len(proposals) == 1

    # Ledger fold should have populated the cache so subsequent fires
    # are O(1) cache hits, not repeated folds.
    assert (str(company_id), jid) in reactivity.seen_jids


async def test_identity_linked_marks_jid_as_known(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """An identity_linked entry is treated as "this jid is known".

    Mirrors UnknownPlatformIdReactivity's _KNOWN_TOOLS posture. If the
    operator merges a WhatsApp jid onto an existing Person via the
    /people merge UI (which writes emit_identity_linked), the discovery
    Reactivity must NOT then double-propose when the same jid chats.
    """
    jid = "5491100000999@s.whatsapp.net"
    pid = uuid4()
    # Pre-seed a Person on slack, then link a WhatsApp identity to it.
    await _seed_person_proposed(
        ledger, company_id,
        platform="slack", platform_user_id="U-bob-slack",
        name="Bob", proposed_by="worm",
    )
    # Override pid to match the seeded person's UUID by re-seeding the link.
    await _seed_identity_linked(
        ledger, company_id,
        person_id=pid, platform="whatsapp", platform_user_id=jid,
    )
    # Bob now chats from his WhatsApp.
    await _seed_chat_received(
        ledger, company_id,
        platform="whatsapp", platform_user_id=jid, channel_id=jid,
    )

    reactivity = WhatsAppOrganicDiscoveryReactivity()
    await _drive_via_whatsapp_reactivity(
        ledger, company_id, reactivity=reactivity,
    )

    rows = await ledger.fetch(company_id)
    # Only the seeded slack person_proposed — no new whatsapp proposal.
    proposals = _person_proposals(rows)
    assert len(proposals) == 1
    assert proposals[0]["payload"]["args"]["platform"] == "slack"


# ---------------------------------------------------------------------------
# 4. Group message with key.participant=<phone>@s.whatsapp.net → propose participant
#
# WhatsAppChannelAdapter._normalize_message already substitutes the
# participant jid for platform_user_id when the message is in a group
# (key.participant ?? key.remoteJid). So when the Reactivity sees a
# chat_received entry with platform_user_id="<phone>@s.whatsapp.net" but
# channel_id="<group>@g.us", it MUST propose the participant.
# ---------------------------------------------------------------------------


async def test_group_message_proposes_participant_not_group(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    group_jid = "120363001234567890@g.us"
    participant_jid = "5491199999999@s.whatsapp.net"

    await _seed_chat_received(
        ledger, company_id,
        platform="whatsapp",
        platform_user_id=participant_jid,  # adapter substituted participant
        channel_id=group_jid,              # but kept the group as channel
        text="hi from inside a group",
    )

    await _drive_via_whatsapp_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    proposals = _person_proposals(rows)
    assert len(proposals) == 1
    args = proposals[0]["payload"]["args"]
    # Person is the participant, not the group.
    assert args["platform_user_id"] == participant_jid
    assert args["name"] == "+5491199999999"


# ---------------------------------------------------------------------------
# 5. Group jid alone (no participant — pure observation) → no Person proposed
# ---------------------------------------------------------------------------


async def test_group_jid_with_no_participant_does_not_propose(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Defensive: a chat_received whose platform_user_id is a group jid
    must NEVER propose a Person.

    This is the pure-observation case where the channel-adapter's
    ``_normalize_message`` saw no ``key.participant`` and only had
    ``key.remoteJid`` pointing at the group. We don't expect this in
    practice — DMs would have remoteJid=<phone>@s.whatsapp.net — but
    the Reactivity's defensive filter pins it.
    """
    group_jid = "120363001234567890@g.us"
    await _seed_chat_received(
        ledger, company_id,
        platform="whatsapp",
        platform_user_id=group_jid,  # group jid as the user-id field
        channel_id=group_jid,
    )

    await _drive_via_whatsapp_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    assert _person_proposals(rows) == []


async def test_chat_received_with_null_platform_user_id_does_not_propose(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Defensive: missing platform_user_id never crashes nor proposes."""
    await _seed_chat_received(
        ledger, company_id,
        platform="whatsapp", platform_user_id=None,
        channel_id="120363001234567890@g.us",
    )

    await _drive_via_whatsapp_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    assert _person_proposals(rows) == []


# ---------------------------------------------------------------------------
# 6. No-regression: Slack chat_received still triggers Slack discovery path
# ---------------------------------------------------------------------------


async def test_slack_chat_received_triggers_slack_discovery_only(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """The WhatsApp Reactivity must not interfere with the Slack path.

    Construct a registry holding BOTH Reactivities (the production-
    parity posture once both wires fire) and seed a Slack chat_received.
    Assertion: the Slack Reactivity proposes (via its member_lookup);
    the WhatsApp Reactivity returns fired=False because of its inner
    platform filter.
    """
    slack_proposes_via: list[tuple[str, str]] = []

    def slack_member_lookup(platform: str, platform_user_id: str):
        slack_proposes_via.append((platform, platform_user_id))
        return {
            "name": "Stranger Danger",
            "email": "stranger@example.co",
            "avatar_url": None,
        }

    await _seed_chat_received(
        ledger, company_id,
        platform="slack", platform_user_id="U-stranger",
        channel_id="C-general",
    )

    registry = ReactivityRegistry(ledger=ledger, company_id=company_id)
    registry.register(
        UnknownPlatformIdReactivity(member_lookup=slack_member_lookup),
    )
    registry.register(WhatsAppOrganicDiscoveryReactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=company_id, registry=registry,
        poll_interval_s=0.01,
    )
    await runner.run_once()

    rows = await ledger.fetch(company_id)
    proposals = _person_proposals(rows)
    assert len(proposals) == 1
    args = proposals[0]["payload"]["args"]
    assert args["platform"] == "slack"
    assert args["platform_user_id"] == "U-stranger"
    # The WhatsApp Reactivity should NOT carry "worm:whatsapp_organic_discovery"
    # for a Slack proposal — the Slack lookup path uses proposed_by="worm".
    assert args["proposed_by"] == "worm"
    # Slack's lookup was consulted exactly once; WhatsApp's never consults
    # any lookup callable (it has none).
    assert slack_proposes_via == [("slack", "U-stranger")]


async def test_whatsapp_reactivity_does_not_consult_member_lookup(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Construction takes no member_lookup; the propose path is roster-free.

    Pin: WhatsApp identity discovery must work without any list_workspace_members
    call surface. The Reactivity carries no lookup callable and never
    constructs one.
    """
    reactivity = WhatsAppOrganicDiscoveryReactivity()
    # No member_lookup attribute. (The inverse of UnknownPlatformIdReactivity,
    # which carries `_member_lookup`.)
    assert not hasattr(reactivity, "_member_lookup")


# ---------------------------------------------------------------------------
# 7. Multi-tenant: same jid across two company_ids → propose per company
# ---------------------------------------------------------------------------


async def test_multitenant_same_jid_proposes_per_company(
    ledger: InMemoryLedger,
) -> None:
    """The same jid hitting two tenants must produce two proposals.

    Cache key includes company_id; ledger fold is company-scoped via
    ``ledger.fetch(company_id)``. Both layers are multi-tenant safe.
    """
    company_a = UUID("00000000-0000-0000-0000-00000000000a")
    company_b = UUID("00000000-0000-0000-0000-00000000000b")
    jid = "447700900100@s.whatsapp.net"

    # Tenant A sees the jid first.
    await _seed_chat_received(
        ledger, company_a,
        platform="whatsapp", platform_user_id=jid, channel_id=jid,
    )

    # Tenant B sees the same jid.
    await _seed_chat_received(
        ledger, company_b,
        platform="whatsapp", platform_user_id=jid, channel_id=jid,
    )

    # One Reactivity instance shared across both runs (pinning the
    # cross-tenant cache safety net).
    reactivity = WhatsAppOrganicDiscoveryReactivity()
    await _drive_via_whatsapp_reactivity(
        ledger, company_a, reactivity=reactivity,
    )
    await _drive_via_whatsapp_reactivity(
        ledger, company_b, reactivity=reactivity,
    )

    rows_a = await ledger.fetch(company_a)
    rows_b = await ledger.fetch(company_b)
    proposals_a = _person_proposals(rows_a)
    proposals_b = _person_proposals(rows_b)
    assert len(proposals_a) == 1
    assert len(proposals_b) == 1
    assert proposals_a[0]["payload"]["args"]["platform_user_id"] == jid
    assert proposals_b[0]["payload"]["args"]["platform_user_id"] == jid

    # Both (company, jid) keys live in the cache.
    assert (str(company_a), jid) in reactivity.seen_jids
    assert (str(company_b), jid) in reactivity.seen_jids


# ---------------------------------------------------------------------------
# Edge: emit_reactivity_fired entry recorded for trace UI
# ---------------------------------------------------------------------------


async def test_reactivity_emits_reactivity_fired_entry(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """The Reactivity records its fires in the ledger for /trace.

    Mirrors UnknownPlatformIdReactivity's contract — the runner writes
    an emit_reactivity_fired entry on every fire, and the Reactivity's
    novelty_key uniquely identifies the (platform, jid) pair.
    """
    jid = "5491111122222@s.whatsapp.net"
    await _seed_chat_received(
        ledger, company_id,
        platform="whatsapp", platform_user_id=jid, channel_id=jid,
    )

    await _drive_via_whatsapp_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    fires = [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_reactivity_fired"
    ]
    assert len(fires) == 1
    args = fires[0]["payload"]["args"]
    assert args["reactivity_id"] == "whatsapp_organic_discovery"
    assert args["novelty_key"] == f"whatsapp:{jid}"


# ---------------------------------------------------------------------------
# Edge: the WhatsApp Reactivity ignores non-whatsapp chat_received entries
# (paired with the Slack-no-regression test above; this test inverts —
# pin the WhatsApp Reactivity is silent on Slack inputs even when no
# Slack Reactivity is co-registered).
# ---------------------------------------------------------------------------


async def test_whatsapp_reactivity_silent_on_slack_chat(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    await _seed_chat_received(
        ledger, company_id,
        platform="slack", platform_user_id="U-some-id",
        channel_id="C-general",
    )

    await _drive_via_whatsapp_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    assert _person_proposals(rows) == []


# ---------------------------------------------------------------------------
# Edge: malformed jid (e.g. legacy device suffix) doesn't propose
# ---------------------------------------------------------------------------


async def test_malformed_jid_does_not_propose(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Defensive: jids that don't match the canonical DM-jid grammar skip.

    Examples: ``<phone>:1@s.whatsapp.net`` (legacy device suffix),
    ``<phone>@lid`` (Linked Devices internal id), or random garbage.
    """
    bad_jids = [
        "5491100000000:1@s.whatsapp.net",  # device suffix
        "5491100000000@lid",                # internal LID
        "not-a-jid-at-all",
        "@s.whatsapp.net",                  # missing phone
    ]
    for bad in bad_jids:
        await _seed_chat_received(
            ledger, company_id,
            platform="whatsapp", platform_user_id=bad, channel_id=bad,
        )

    await _drive_via_whatsapp_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    assert _person_proposals(rows) == []
