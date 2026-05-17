# Helper Duplications Register (O-B5)

Status: durable
Authoritative: yes
Owner: worm decomposition

## Purpose

A small set of helpers are intentionally duplicated across `apps/worm-core`
and `packages/wormbase-chat-presence`. The duplication exists to keep each
chat-presence module self-contained and to avoid worm-core ↔ chat-presence
import cycles after the Wave B decomposition (see
`docs/superpowers/specs/2026-04-26-production-dashboard-and-identity.md`
and the worm-decomposition orchestration log).

This register names every intentional duplicate, identifies the canonical
site, and pins the drift policy. A contract test at
`tests/contract/test_helper_duplication_drift.py` enforces the policy at
commit time.

## Drift policy (default)

**Byte-equivalent.** Duplicates must match the canonical site verbatim
modulo whitespace and comments. If the canonical site changes, the
duplicate must be updated in the same commit. The drift detector rejects
PRs that allow them to diverge.

When a duplicate must legitimately diverge (different event-shape
handling, etc.), promote the canonical helper to a shared location
(governance, ledger, or a dedicated `wormbase-shared` package) rather
than letting the two copies drift. Drifting is never the answer; either
sync or unify.

## Register

### `_PII_FILENAME_HINTS`

| Field | Value |
|---|---|
| Kind | `re.Pattern` (compiled regex) |
| Canonical site | `apps/worm-core/src/wormbase_core/flows.py` (line ~69) |
| Duplicate site | `packages/wormbase-chat-presence/src/wormbase_chat_presence/chat_flows/kpi_gap_triggered.py` (line ~27) |
| Reason | Avoid coupling `kpi_gap_triggered` to `drop_and_profile`'s internals; the lake-discovery shim in worm-core also reads it without importing chat_flows. |
| Drift policy | `pattern` attribute must be byte-equivalent. Drift detector compares `core.pattern == chat.pattern`. |

### `_scrub_credential`

| Field | Value |
|---|---|
| Kind | function `(uri: str) -> str` |
| Canonical site | `apps/worm-core/src/wormbase_core/flows.py` (line ~81) |
| Duplicate site | `packages/wormbase-chat-presence/src/wormbase_chat_presence/chat_flows/credential_in_dm.py` (line ~48) |
| Reason | Both `DashboardFormFlow` (worm-core) and `CredentialInDmFlow` (chat-presence) need to redact `user:pass` from URIs before emitting ledger entries. Keeping a local copy in each module avoids cross-package imports for a one-line regex sub. |
| Drift policy | Function source (modulo whitespace/comments) must be byte-equivalent. |

### `_DATA_SOURCE_KEYWORDS`

| Field | Value |
|---|---|
| Kind | `tuple[str, ...]` |
| Canonical site | `packages/governance/src/wormbase_governance/relevance.py` (line ~43) |
| Re-export shim 1 | `apps/worm-core/src/wormbase_core/relevance.py` (re-export) |
| Re-export shim 2 | `packages/wormbase-chat-presence/src/wormbase_chat_presence/relevance.py` (re-export) |
| Reason | Wave D consolidation lifted the relevance gate into governance; the two shim modules preserve legacy import paths during the Wave E slim-down window. The constant is consumed by both `RulesBasedRelevanceGate` (governance) and tests (worm-core, chat-presence). |
| Drift policy | The `set()` of the tuple must match across all import paths. Re-exports are guaranteed equivalent by Python's import machinery; the test asserts `set(core) == set(chat)` to defend against accidental local override. |

### `_event_to_infra`

| Field | Value |
|---|---|
| Kind | function `(event: dict, company_id: UUID) -> InfraEvent` |
| Canonical site | `apps/worm-core/src/wormbase_core/service.py` (line ~207) |
| Duplicate site | `packages/wormbase-chat-presence/src/wormbase_chat_presence/dispatcher.py` (line ~31) |
| Reason | Both the legacy worm-core lurker/poller and the chat-presence flow dispatcher need to coerce a raw channel event dict into a typed `InfraEvent`. Chat-presence keeps a private mirror to avoid a `worm-core → chat-presence` import (chat-presence imports worm-core but not vice-versa, so re-exporting from chat-presence would create a cycle for any future worm-core caller that needed it). |
| Drift policy | Function source (normalized: stripped lines, no comments) must be byte-equivalent. The chat-presence copy is treated as a pinned mirror of the canonical site; legitimate divergences (e.g. handling new event types like `dm`) must land in worm-core first, then be propagated. |

## Drift detector contract

`tests/contract/test_helper_duplication_drift.py` runs three assertions:

```python
core.pattern == chat.pattern                          # _PII_FILENAME_HINTS
set(core) == set(chat)                                # _DATA_SOURCE_KEYWORDS
_norm(inspect.getsource(core)) == _norm(getsource(chat))  # _event_to_infra
```

`_norm` strips blank lines, leading/trailing whitespace per line, and
comment-only lines so docstrings and trailing whitespace do not trigger
false drift.

`_scrub_credential` is verified by source-equivalence in the same test
module via the same `_norm` helper.

If a duplicate legitimately diverges in a future change, the right move
is to:

1. Hoist the canonical helper to `wormbase_shared` (or governance, if
   semantically governance-y).
2. Replace both call sites with the shared import.
3. Delete the duplicate's row from this register.
4. Delete the corresponding assertion from the drift detector.

Drifting in place is never sanctioned.
