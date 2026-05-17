# Architecture Decision Records

This directory contains the durable architectural decisions that shaped
WormBase. Each ADR captures a single decision: the context that motivated
it, the decision itself, the rejected alternatives, and the consequences
the project lives with as a result.

ADRs are immutable once accepted. If a later decision supersedes an
existing ADR, a new ADR is added with status `Accepted` and the older
ADR's status is updated with a back-reference. ADRs are never deleted.

For the day-to-day architectural surface these decisions composed into,
see [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md). For the deep specs
that some ADRs reference, see `../../superpowers/specs/`.

## Index

| # | Date | Title | Synopsis |
|---|---|---|---|
| [ADR-0001](ADR-0001-listener-shaped-channel-adapter.md) | 2026-04-27 | Listener-shaped channel adapter (OpenClaw over responder-shaped Hermes) | Chose OpenClaw's global event log over Hermes's responder-shaped hook system because the worm must capture every message regardless of bot engagement. |
| [ADR-0002](ADR-0002-mcp-server-in-band-with-governance-gates.md) | 2026-04-27 | Agent Gateway as in-band MCP server with governance gates | In-process FastMCP server that writes every tool call through the same PEVR primitive as every other ledger write; bearer-auth, stateless HTTP, ~3.7ms median round-trip. |
| [ADR-0003](ADR-0003-lake-maintainer-pattern.md) | 2026-05-02 | Lake-Maintainer package pattern for pluggable data-source watchers | Split the Source Protocol into `AcquirableSource` (external + filedrop) and `MaintainableSource` (all four families); compose with the W5a Reactivity registry; drop `watch()` from the v1 surface. |
| [ADR-0004](ADR-0004-chat-presence-package.md) | 2026-05-03 | Chat Presence reactivity for channel-first conversation ingest | Extracted the chat triad, four Reactivities, and the `ChatReply` PEVR-tracked speech primitive into `packages/wormbase-chat-presence`; talkativeness becomes projection-backed policy. |
| [ADR-0005](ADR-0005-composable-governance-gates.md) | 2026-05-03 | Composable governance gates and policy-as-code | Consolidated `RulesBasedRelevanceGate` and the governance result types into `packages/governance`; introduced `PolicyGate` as a typing-only Protocol; preserved the relevance-vs-gate-fired audit distinction. |
| [ADR-0006](ADR-0006-hub-redefinition-and-four-wire-boot.md) | 2026-05-03 | Hub redefinition and the four-wire boot path | The hub stabilizes at 27 modules + 3 subpackages; the boot path calls four `wire_*_for_install`s (not five); lake-maintainer wires per-source and governance composes at construction sites. |
| [ADR-0007](ADR-0007-identity-resolver-protocol.md) | 2026-05-03 | IdentityResolver Protocol and identity-tracker package | Single frozen Protocol with four methods; ledger-backed implementation; greenfield Reactivities (position inference, resource ownership) deferred behind two new entry kinds. |
| [ADR-0008](ADR-0008-process-extractor-as-reactivities.md) | 2026-05-03 | Process extraction as W5a Reactivities | Decomposed the 970-LOC polling `ProcessExtractor` into three working Reactivities plus one stub; net negative LOC; zero new entry kinds; topic_extractor stays with chat-worm. |
| [ADR-0009](ADR-0009-research-loop-as-reactivities.md) | 2026-05-03 | Autoresearch loop as W5a Reactivities | Three Reactivities plus a keep-rate publisher replace the autoresearch / team / company runners; deleted `heuristic_loop.py`; composition with W5b phenomenon-gap detectors at the predicate level. |
| [ADR-0010](ADR-0010-deferred-backlog-criteria.md) | 2026-05-04 | Deferral criteria for portfolio-adjacent cleanups | One combined wave with three sub-waves clears eight portfolio-adjacent items; Wave B.5 gated on a freeze-pause doctrine review; pytest cross-package collection unsupported by design. |
| [ADR-0011](ADR-0011-multitenancy-v2-signup-and-isolation.md) | 2026-05-04 | Multi-tenant signup, session, and isolation model | Canonical `tenant_signup_*` ledger flow; signed `wormbase-session` cookie; MCP token gate asserts Person exists in tenant; five-tenant demo carousel via magic-link round-robin. |
| [ADR-0012](ADR-0012-semantic-layer-foundations.md) | 2026-05-10 | Semantic layer foundations — catalog mirror, broker, and MCP audit chain | Six foundational assumptions validated; dbt parser whitelist; Snowflake `DESCRIBE` two-step; one Vault backend for data + model creds; lake-maintainer dual-mode as Source-instance type. |

## Doctrine reviews

Reviews that revisit a doctrine periodically and ratify (or amend) its
operating thresholds. These sit alongside the ADRs because each review
either confirms an existing decision or supersedes a previous addendum.

- [doctrine-schema-evolution-review.md](doctrine-schema-evolution-review.md)
  — Full audit of the 117-kind registry; confirms no consolidations;
  recommends raising the ceiling to 150 with per-family caps + a new
  `lake-side-loops` family; pairs with formal DEPRECATED marking for
  three retire-candidates. Companion to the schema-evolution doctrine
  spec.

## Format

Each ADR follows a consistent shape:

- **Context** — what problem space did this decision address?
- **Decision** — what was decided, and what alternatives were rejected?
- **Consequences** — positive, negative, and neutral trade-offs.
- **Cross-references** — related ADRs, specs, and architecture sections.

ADRs are honest about trade-offs. They are not PR-polished; they record
what the project gave up alongside what it gained.
