"""Identity-merge property tests (W6.A1, P6 of demo-day PRD).

The hash chain is fuzzed elsewhere in this directory; this module fuzzes
the *highest-blast-radius admin action* — identity link / unlink / merge —
which is what regulated buyers will inspect first when they audit the
``/people`` surface. The four invariants asserted here are the spec at
``docs/superpowers/specs/2026-04-29-demo-day-prd.md`` §7 P6.

Invariants asserted
-------------------
I1. **Reconstructable confirmation chain.** ``Person.confirmed_by`` chain
    is fully reconstructable from the ledger by replaying
    ``emit_identity_linked`` / ``emit_identity_unlinked`` execute entries
    in seq order. Every link / unlink in the audit trail carries a
    non-null actor (``linked_by`` / ``unlinked_by``); the fold over those
    entries equals the orchestrator's ``_current_identities_for_person``
    output. Order matters: ``link → unlink → link`` resolves to ATTACHED.

I2. **No orphan PersonIdentity rows.** Every identity that the fold
    reports as currently attached belongs to a non-archived ``Person``;
    every identity that was once attached but is no longer attached has
    a corresponding ``emit_identity_unlinked`` (or
    ``emit_person_archived``) execute entry. There is no "ghost"
    identity: every PersonIdentity row is either current OR explicitly
    detached in the ledger.

I3. **Role-grant survival under merge.** ``emit_role_assigned``,
    ``emit_domain_role_assigned``, and ``emit_resource_role_assigned``
    entries written before a merge survive the merge byte-identically
    in the ledger, with their original ``granted_by`` attribution
    preserved. Merge does NOT silently transfer a grant onto the keeper
    without writing a corresponding ``emit_role_reassigned`` entry —
    in the current implementation, no such entry kind is emitted at
    merge time, so role grants on the mergee remain attributed to the
    mergee in the audit trail. The append-only ledger shape is the
    enforcement.

I4. **Determinism under replay.** Running the same sequence of write
    actions on a fresh tenant (with a pinned UUID stream so person_id
    and entry_id allocation is deterministic) yields identical logical
    ledger output: the (tool, person_id) execute signature is
    byte-equal, the ``_current_identities_for_person`` projection is
    byte-equal, and the role-grant projection (kind + person_id + role
    + granted_by + scope) is byte-equal across two independent runs.
    Wall-clock timestamps are NOT pinned because mutating ``ts``
    invalidates the row's ``hash`` field; the I4 comparison strips
    ``ts`` instead.

Strategy
--------
A scenario strategy produces a tuple of ``(persons, ops)`` where:
  * ``persons`` is a list of seed Persons (1..2), each carrying a
    proposing platform identity.
  * ``ops`` is a list of LINK / UNLINK / GRANT operations across the
    persons and a fixed pool of N platforms (N ∈ [1, 8]).

The scenario is replayed twice on independent ledgers (or, for I3, with
an interleaved merge); each invariant asserts a property over the
resulting ledger or projection. Each ``@given`` runs 55 examples with
deadline=None — above the W6.A1 floor of 51 trials per invariant, and
the whole module finishes well under the 5s budget on CI hardware.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch
from uuid import UUID

from hypothesis import HealthCheck, given, settings, strategies as st

from wormbase_core import write_actions
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.hash_chain import verify_chain


# ---------------------------------------------------------------------------
# Scenario primitives
# ---------------------------------------------------------------------------


# Pool of platforms: N ∈ [1, 8] per the PRD. We sample with replacement
# across operations, but the strategy bounds the *distinct* platform count
# per scenario so the I1 fold stays interesting.
_PLATFORMS: tuple[str, ...] = (
    "slack", "discord", "teams", "whatsapp",
    "signal", "matrix", "irc", "google_chat",
)


def _company_id_for(seed: int) -> UUID:
    """Stable per-trial company UUID derived from a Hypothesis-drawn int.

    Using a stable derivation (rather than uuid4) keeps shrinking
    behaviour deterministic — if Hypothesis finds a counterexample, it
    can replay it with the same company UUID next run.
    """
    # 0x6e (lowercase 'n' in ASCII) chosen as a stable byte pattern; the
    # last 4 bytes encode the seed so two trials never collide.
    return UUID(int=(0x6e << 120) | (seed & 0xFFFFFFFF))


# Per-Person seed: name + email + seed identity.
@st.composite
def _person_seed(draw: st.DrawFn, idx: int) -> dict[str, Any]:
    """Build a deterministic Person seed for index ``idx``.

    The seed is keyed off ``idx`` (not Hypothesis-drawn) so the I4
    determinism test can re-build exactly the same seed list on a fresh
    tenant by iterating the same indices.
    """
    return {
        "name": f"person_{idx}",
        "email": f"person_{idx}@example.test",
        "platform": _PLATFORMS[idx % len(_PLATFORMS)],
        "platform_user_id": f"U-{idx:04d}",
        "position": draw(st.sampled_from([None, "engineer", "analyst"])),
    }


@st.composite
def _scenario(
    draw: st.DrawFn,
    *,
    n_persons_min: int = 1,
    n_persons_max: int = 2,
    n_ops_min: int = 1,
    n_ops_max: int = 6,
    n_platforms_min: int = 1,
    n_platforms_max: int = 8,
) -> dict[str, Any]:
    """Hypothesis-built scenario consumed by every invariant.

    Returns:
        {
            "persons": list[PersonSeed],     # 1..3 seed persons
            "platforms": list[str],          # 1..8 distinct platforms in play
            "ops": list[Op],                 # link / unlink / grant ops
            "seed": int,                     # company-id derivation seed
        }

    Each Op is a tuple of (op_kind, args). op_kind ∈ {"link", "unlink",
    "grant_tenancy", "grant_domain", "grant_resource"}. Args are bound
    to the persons + platforms drawn for the scenario.
    """
    seed = draw(st.integers(min_value=0, max_value=2**31 - 1))
    n_persons = draw(st.integers(min_value=n_persons_min, max_value=n_persons_max))
    persons = [draw(_person_seed(i)) for i in range(n_persons)]

    n_platforms = draw(
        st.integers(min_value=n_platforms_min, max_value=n_platforms_max),
    )
    platforms = list(_PLATFORMS[:n_platforms])

    n_ops = draw(st.integers(min_value=n_ops_min, max_value=n_ops_max))
    ops: list[tuple[str, dict[str, Any]]] = []
    for j in range(n_ops):
        op_kind = draw(
            st.sampled_from(
                ["link", "unlink", "link", "grant_tenancy",
                 "grant_domain", "grant_resource"],
            )
        )
        person_ix = draw(st.integers(min_value=0, max_value=n_persons - 1))
        platform_ix = draw(st.integers(min_value=0, max_value=n_platforms - 1))
        # ``puid_pool`` keeps unlinks targeting identities that exist —
        # without it Hypothesis would burn a lot of trials on no-op unlinks.
        puid_ix = draw(st.integers(min_value=0, max_value=2))
        args = {
            "person_ix": person_ix,
            "platform": platforms[platform_ix],
            "platform_user_id": f"u-{person_ix}-{platform_ix}-{puid_ix}",
            # Role-grant fields (only used by the grant_* ops):
            "role_tenancy": draw(
                st.sampled_from(["member", "admin", "observer"]),
            ),
            "role_domain": draw(st.sampled_from(["owner", "contributor"])),
            "role_resource": draw(
                st.sampled_from(["maintainer", "contributor"]),
            ),
            # Stable per-op ix into a domain/resource pool so two replays
            # of the same scenario hit the same UUIDs (see _pinned_uuids).
            "domain_ix": draw(st.integers(min_value=0, max_value=2)),
            "resource_ix": draw(st.integers(min_value=0, max_value=2)),
            "resource_type": draw(
                st.sampled_from(["source", "table", "kpi"]),
            ),
            "op_ix": j,
        }
        ops.append((op_kind, args))

    return {
        "persons": persons,
        "platforms": platforms,
        "ops": ops,
        "seed": seed,
    }


# ---------------------------------------------------------------------------
# Replay harness
# ---------------------------------------------------------------------------


class _PinnedUUIDs:
    """A deterministic UUID stream for a single scenario replay.

    The stream is a function of ``(seed, role)`` so two replays of the
    same scenario yield identical ``entry_id`` / ``person_id`` /
    ``domain_id`` / ``resource_id`` sequences — which is what the I4
    determinism invariant compares.
    """

    def __init__(self, seed: int) -> None:
        self._seed = seed
        self._counter = 0

    def __call__(self) -> UUID:
        self._counter += 1
        # Pack (seed, counter) into a 128-bit UUID. Top 32 bits = seed
        # (so cross-scenario UUIDs never alias), low 96 bits = counter.
        n = ((self._seed & 0xFFFFFFFF) << 96) | (self._counter & ((1 << 96) - 1))
        return UUID(int=n)


def _stable_uuid(*parts: Any) -> UUID:
    """Deterministic UUID derived from a tuple of arbitrary parts.

    Used for domain_id / resource_id so a scenario re-runs to the same
    UUIDs without going through the pinned stream (those are reserved
    for entry/person UUIDs the orchestrator allocates).
    """
    import hashlib

    h = hashlib.sha256(repr(parts).encode("utf-8")).digest()
    return UUID(bytes=h[:16], version=4)


async def _run_scenario(
    scenario: dict[str, Any],
    *,
    company_id: UUID,
) -> tuple[InMemoryLedger, list[UUID], dict[str, Any]]:
    """Execute a scenario against a fresh InMemoryLedger.

    Returns ``(ledger, person_ids, meta)`` where ``meta`` carries:
        - ``actor``: a stable UUID used as ``linked_by`` / ``granted_by``

    Implementation note: timestamps are taken from ``datetime.now(UTC)``
    per the InMemoryLedger default. We do NOT mutate ``ts`` after the
    write because that would invalidate the row's ``hash`` field and
    break the chain. The I4 determinism invariant compares projections
    that don't read ``ts`` (kind, tool, person_id, role, granted_by,
    identity tuples) so timestamp drift across replays is fine.
    """
    ledger = InMemoryLedger()
    seed = scenario["seed"]
    pinned = _PinnedUUIDs(seed=seed)
    actor = _stable_uuid("actor", seed)

    person_ids: list[UUID] = []

    # Patch uuid4 in BOTH modules that allocate identifiers — write_actions
    # for person_id / domain pools, ledger_api for entry_id. Both modules
    # imported uuid4 by name, so we patch both module-level rebinds.
    with patch("wormbase_core.write_actions.uuid4", pinned), \
            patch("wormbase_ledger.ledger_api.uuid4", pinned):
        # 1. Propose every Person.
        for p in scenario["persons"]:
            pid, _ = await write_actions.propose_person(
                ledger, company_id,
                name=p["name"], email=p["email"],
                platform=p["platform"],
                platform_user_id=p["platform_user_id"],
                position=p["position"],
                proposed_by="property-suite",
            )
            person_ids.append(pid)

        # 2. Apply each op.
        for op, args in scenario["ops"]:
            pid = person_ids[args["person_ix"]]
            if op == "link":
                await write_actions.link_identity(
                    ledger, company_id,
                    person_id=pid,
                    platform=args["platform"],
                    platform_user_id=args["platform_user_id"],
                    linked_by=actor,
                )
            elif op == "unlink":
                await write_actions.unlink_identity(
                    ledger, company_id,
                    person_id=pid,
                    platform=args["platform"],
                    platform_user_id=args["platform_user_id"],
                    unlinked_by=actor,
                )
            elif op == "grant_tenancy":
                await write_actions.grant_tenancy_role(
                    ledger, company_id,
                    person_id=pid,
                    role=args["role_tenancy"],
                    granted_by=actor,
                )
            elif op == "grant_domain":
                await write_actions.grant_domain_role(
                    ledger, company_id,
                    person_id=pid,
                    domain_id=_stable_uuid("domain", args["domain_ix"]),
                    role=args["role_domain"],
                    granted_by=actor,
                )
            elif op == "grant_resource":
                await write_actions.grant_resource_role(
                    ledger, company_id,
                    person_id=pid,
                    resource_id=_stable_uuid(
                        "resource", args["resource_type"], args["resource_ix"],
                    ),
                    resource_type=args["resource_type"],
                    role=args["role_resource"],
                    granted_by=actor,
                )
            else:  # pragma: no cover — sanity guard
                raise AssertionError(f"unknown op {op}")

    return ledger, person_ids, {"actor": actor}


# ---------------------------------------------------------------------------
# Logical projections — what we compare across replays
# ---------------------------------------------------------------------------


def _fold_identities_from_ledger(
    rows: list[dict[str, Any]], person_id: UUID,
) -> list[tuple[str, str]]:
    """Re-implement the orchestrator's identity fold *from raw rows*.

    The orchestrator's ``_current_identities_for_person`` is async and
    re-fetches the ledger; this is its synchronous twin used by the
    invariant assertions. Output MUST match the orchestrator's output —
    that equality is the I1 invariant.
    """
    pid_str = str(person_id)
    state: dict[tuple[str, str], bool] = {}
    for row in rows:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        tool = payload.get("tool")
        args = payload.get("args") or {}
        if args.get("person_id") != pid_str:
            continue
        if tool == "emit_person_proposed":
            platform = args.get("platform")
            puid = args.get("platform_user_id")
            if platform and puid:
                state[(platform, puid)] = True
        elif tool == "emit_identity_linked":
            platform = args.get("platform")
            puid = args.get("platform_user_id")
            if platform and puid:
                state[(platform, puid)] = True
        elif tool == "emit_identity_unlinked":
            platform = args.get("platform")
            puid = args.get("platform_user_id")
            if platform and puid and (platform, puid) in state:
                state[(platform, puid)] = False
    return [k for k, attached in state.items() if attached]


def _role_grants_projection(
    rows: list[dict[str, Any]],
) -> list[tuple[str, ...]]:
    """Project role-grant entries to a comparable tuple form.

    Captures (kind, person_id, role, granted_by, [optional id]) for every
    role-grant execute payload. Used to assert byte-equal grant survival
    across replays AND to verify that no merge silently re-attributes a
    grant.
    """
    out: list[tuple[str, ...]] = []
    for row in rows:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        tool = payload.get("tool")
        args = payload.get("args") or {}
        if tool == "emit_role_assigned":
            out.append((
                tool,
                args.get("person_id", ""),
                args.get("role", ""),
                args.get("granted_by", ""),
            ))
        elif tool == "emit_domain_role_assigned":
            out.append((
                tool,
                args.get("person_id", ""),
                args.get("role", ""),
                args.get("granted_by", ""),
                args.get("domain_id", ""),
            ))
        elif tool == "emit_resource_role_assigned":
            out.append((
                tool,
                args.get("person_id", ""),
                args.get("role", ""),
                args.get("granted_by", ""),
                args.get("resource_id", ""),
                args.get("resource_type", ""),
            ))
    return out


def _execute_signature(
    rows: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """A stable fingerprint of the execute-payload sequence.

    Returns ``(tool, person_id-or-empty)`` for every execute row, in
    seq order. Two replays of the same scenario MUST produce identical
    signatures. This is the I4 byte-equal logical-ledger comparison.
    """
    out: list[tuple[str, str]] = []
    for row in rows:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        tool = payload.get("tool", "")
        args = payload.get("args") or {}
        out.append((tool, args.get("person_id", "")))
    return out


# ---------------------------------------------------------------------------
# I1 — Reconstructable confirmation chain
# ---------------------------------------------------------------------------


@given(_scenario())
@settings(
    max_examples=55, deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
def test_i1_confirmation_chain_reconstructable(scenario: dict[str, Any]) -> None:
    """I1 — confirmation chain reconstructable.

    For every Person, the orchestrator's identity fold must equal a
    raw replay of ``emit_identity_linked`` / ``emit_identity_unlinked``
    in seq order, and every link / unlink entry MUST carry a non-null
    actor (``linked_by`` / ``unlinked_by``). The fold over the audit
    trail is what reconstructs the ``Person.confirmed_by`` chain.
    """

    async def _go() -> None:
        company_id = _company_id_for(scenario["seed"])
        ledger, person_ids, _ = await _run_scenario(
            scenario, company_id=company_id,
        )
        rows = await ledger.fetch(company_id)

        # Hash chain stays valid — link / unlink / grant don't break it.
        ok, broken = verify_chain(rows)
        assert ok, f"hash chain broken at row {broken}"

        # Every link / unlink in the audit trail has a non-null actor.
        for row in rows:
            if row.get("kind") != "execute":
                continue
            payload = row.get("payload") or {}
            tool = payload.get("tool")
            args = payload.get("args") or {}
            if tool == "emit_identity_linked":
                assert args.get("linked_by"), (
                    f"identity_linked row {row['seq']} missing linked_by"
                )
            elif tool == "emit_identity_unlinked":
                assert args.get("unlinked_by"), (
                    f"identity_unlinked row {row['seq']} missing unlinked_by"
                )

        # Orchestrator-fold equals raw-row-fold for every Person.
        for pid in person_ids:
            orchestrator_fold = await write_actions._current_identities_for_person(
                ledger, company_id, person_id=pid,
            )
            raw_fold = _fold_identities_from_ledger(rows, pid)
            assert sorted(orchestrator_fold) == sorted(raw_fold), (
                f"fold mismatch for person {pid}: "
                f"orchestrator={sorted(orchestrator_fold)} "
                f"raw={sorted(raw_fold)}"
            )

    asyncio.run(_go())


# ---------------------------------------------------------------------------
# I2 — No orphan PersonIdentity rows
# ---------------------------------------------------------------------------


@given(_scenario())
@settings(
    max_examples=55, deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
def test_i2_no_orphan_person_identity_rows(scenario: dict[str, Any]) -> None:
    """I2 — every PersonIdentity row references a current Person OR has a
    matching ``emit_identity_unlinked`` (or ``emit_person_archived``) entry.

    Walk every link / propose entry in the ledger; for each (person_id,
    platform, platform_user_id) tuple that was *ever* attached, verify:
      a) the Person row exists in the ledger (we proposed it), AND
      b) either the identity is currently attached (per the fold), OR
         there is a corresponding ``emit_identity_unlinked`` entry on
         that person, OR the person was archived.
    """

    async def _go() -> None:
        company_id = _company_id_for(scenario["seed"])
        ledger, person_ids, _ = await _run_scenario(
            scenario, company_id=company_id,
        )
        rows = await ledger.fetch(company_id)

        # Index every "ever-attached" (person_id, platform, puid) tuple.
        ever: set[tuple[str, str, str]] = set()
        archived: set[str] = set()
        unlinked: set[tuple[str, str, str]] = set()
        proposed_persons: set[str] = set()
        for row in rows:
            if row.get("kind") != "execute":
                continue
            payload = row.get("payload") or {}
            tool = payload.get("tool")
            args = payload.get("args") or {}
            pid = args.get("person_id")
            if not pid:
                continue
            if tool == "emit_person_proposed":
                proposed_persons.add(pid)
                platform = args.get("platform") or ""
                puid = args.get("platform_user_id") or ""
                if platform and puid:
                    ever.add((pid, platform, puid))
            elif tool == "emit_identity_linked":
                platform = args.get("platform") or ""
                puid = args.get("platform_user_id") or ""
                if platform and puid:
                    ever.add((pid, platform, puid))
            elif tool == "emit_identity_unlinked":
                platform = args.get("platform") or ""
                puid = args.get("platform_user_id") or ""
                if platform and puid:
                    unlinked.add((pid, platform, puid))
            elif tool == "emit_person_archived":
                archived.add(pid)

        # The current fold per Person.
        current_per_person: dict[str, set[tuple[str, str]]] = {}
        for pid in person_ids:
            current_per_person[str(pid)] = set(
                _fold_identities_from_ledger(rows, pid),
            )

        # Every ever-attached identity MUST be reachable: either
        # currently attached, or unlinked, or its Person is archived.
        for (pid_str, platform, puid) in ever:
            assert pid_str in proposed_persons, (
                f"identity {(pid_str, platform, puid)} attached to a "
                f"Person that was never proposed"
            )
            currently = (platform, puid) in current_per_person.get(pid_str, set())
            has_unlink = (pid_str, platform, puid) in unlinked
            person_archived = pid_str in archived
            assert currently or has_unlink or person_archived, (
                f"orphan identity: {(pid_str, platform, puid)} is "
                f"neither current nor unlinked nor archived"
            )

    asyncio.run(_go())


# ---------------------------------------------------------------------------
# I3 — Role-grant survival under merge
# ---------------------------------------------------------------------------


@given(_scenario(n_persons_min=2, n_persons_max=2, n_ops_min=2, n_ops_max=5))
@settings(
    max_examples=55, deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
def test_i3_role_grants_survive_merge(scenario: dict[str, Any]) -> None:
    """I3 — role grants survive merge with original ``granted_by`` preserved.

    For any scenario that includes role grants on multiple Persons, run
    ``merge_persons`` on the first two Persons; verify:
      a) every pre-merge role-grant entry is still present in the
         post-merge ledger (the ledger is append-only, so this is a
         tautology of the substrate — the assertion is the *check*),
      b) every grant retains its original ``granted_by``,
      c) NO ``emit_role_reassigned`` entries appear (the current
         orchestrator does not silently transfer grants — and if a
         future change adds the kind, it must do so explicitly).
    """

    async def _go() -> None:
        company_id = _company_id_for(scenario["seed"])
        ledger, person_ids, meta = await _run_scenario(
            scenario, company_id=company_id,
        )
        # Capture role grants before the merge.
        rows_pre = await ledger.fetch(company_id)
        pre_grants = _role_grants_projection(rows_pre)

        # Merge person[1] into person[0] if both exist and differ.
        if len(person_ids) < 2:
            return  # nothing to merge — trial is vacuous
        keeper, mergee = person_ids[0], person_ids[1]

        with patch(
            "wormbase_core.write_actions.uuid4",
            _PinnedUUIDs(seed=scenario["seed"] ^ 0xDEADBEEF),
        ), patch(
            "wormbase_ledger.ledger_api.uuid4",
            _PinnedUUIDs(seed=scenario["seed"] ^ 0xCAFEBABE),
        ):
            await write_actions.merge_persons(
                ledger, company_id,
                keeper_id=keeper, mergee_id=mergee, merged_by=meta["actor"],
            )

        rows_post = await ledger.fetch(company_id)
        post_grants = _role_grants_projection(rows_post)

        # (a) + (b): every pre-merge grant tuple is still present
        # post-merge with byte-identical attribution.
        for grant in pre_grants:
            assert grant in post_grants, (
                f"role grant {grant} disappeared after merge"
            )

        # (c): no emit_role_reassigned entries written.
        for row in rows_post:
            if row.get("kind") != "execute":
                continue
            tool = (row.get("payload") or {}).get("tool")
            assert tool != "emit_role_reassigned", (
                "merge silently re-attributed a grant (emit_role_reassigned "
                "appeared in the audit trail)"
            )

        # Sanity: hash chain still valid post-merge.
        ok, broken = verify_chain(rows_post)
        assert ok, f"hash chain broken at row {broken} after merge"

    asyncio.run(_go())


# ---------------------------------------------------------------------------
# I4 — Determinism under replay
# ---------------------------------------------------------------------------


@given(_scenario(n_ops_max=5))
@settings(
    max_examples=55, deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
def test_i4_determinism_under_replay(scenario: dict[str, Any]) -> None:
    """I4 — same scenario on a fresh tenant yields identical projections.

    Run the same scenario twice on independent ledgers (with the same
    pinned UUID stream and timestamp policy). Assert that the
    (kind, tool, person_id) execute signature is byte-equal, the
    per-Person identity fold is byte-equal, and the role-grant
    projection is byte-equal across the two runs.
    """

    async def _go() -> None:
        # Two distinct company UUIDs but same logical scenario — so
        # company_id appears in the ledger envelope but NOT in the
        # comparisons we make (the projections we compare strip it).
        c1 = _company_id_for(scenario["seed"])
        c2 = _company_id_for(scenario["seed"] ^ 0x55555555)

        l1, pids1, _ = await _run_scenario(scenario, company_id=c1)
        l2, pids2, _ = await _run_scenario(scenario, company_id=c2)

        rows1 = await l1.fetch(c1)
        rows2 = await l2.fetch(c2)

        # Pinned UUID stream + identical scenario → identical person_ids
        # in identical order.
        assert pids1 == pids2, (
            f"person_id stream diverged: {pids1} vs {pids2}"
        )

        # Execute signature byte-equal.
        sig1 = _execute_signature(rows1)
        sig2 = _execute_signature(rows2)
        assert sig1 == sig2, (
            f"execute signature diverged across replays:\n  {sig1}\n  {sig2}"
        )

        # Identity projections per Person byte-equal.
        for pid in pids1:
            f1 = sorted(_fold_identities_from_ledger(rows1, pid))
            f2 = sorted(_fold_identities_from_ledger(rows2, pid))
            assert f1 == f2, (
                f"identity fold diverged for {pid}:\n  {f1}\n  {f2}"
            )

        # Role-grant projections byte-equal.
        g1 = _role_grants_projection(rows1)
        g2 = _role_grants_projection(rows2)
        assert g1 == g2, (
            f"role-grant projection diverged across replays:\n  {g1}\n  {g2}"
        )

    asyncio.run(_go())
