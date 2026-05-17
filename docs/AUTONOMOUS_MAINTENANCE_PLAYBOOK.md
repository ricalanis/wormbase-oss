# Autonomous Maintenance Playbook

> How agent-orchestrated codebases sustain themselves.

## Why this playbook exists

WormBase is maintained by a small set of humans and a much larger set of subagents.
Most of the substrate — packages, ledger entry kinds, dashboard surfaces, test suites,
spec documents, runbooks — is written and re-written by agents working in waves, with
a human orchestrator scoping, dispatching, reviewing, and merging. This document
captures the durable practice that emerged from that posture, distilled for OSS
adopters who want to run their codebases the same way.

The playbook is not a tooling manifesto. It is invariant under tool choice: the
patterns below apply whether you drive subagents through Claude Code, plain SDK
calls, or any other harness that can carry a scoped task to completion. What
matters is the *shape* of the work — discrete, scoped, file-disjoint, evidenced —
not the wire it travels over.

## The dispatch primitive

A maintenance arc has five phases, in this order:

1. **Scope.** Decide what is in. Decide what is out. The scope is a paragraph,
   a file list, a test list, and a definition of done. If you cannot write it in
   under five minutes, the scope is wrong; cut it smaller.
2. **Dispatch.** Hand the scoped work to a subagent with the spec, the file
   paths, the test paths, and the acceptance gate. The subagent runs to
   completion or to a blocker; it does not negotiate scope mid-flight.
3. **Review.** Read the diff. Run the gate. Confirm the spec was honored.
   Negotiate only the deltas: places where the subagent flagged a deviation, or
   places where reality contradicted the spec. Most reviews are short.
4. **Commit.** One atomic commit per scoped arc. Message records the wave, the
   scope, the test counts that moved, the entry-kind counts that moved if any.
   The commit is the durable artifact; everything before it is scaffolding.
5. **Close-out.** Append a short note to the wave's status file: what landed,
   what shipped, what was deferred, what the next arc should be aware of.
   Close-outs are the compounding state the next arc reads first.

Skip any phase and the practice breaks. Skipping scope produces dispatch sprawl.
Skipping review produces incoherent merges. Skipping close-out produces orphan
work that has to be re-discovered next session.

## Wave-shaped decomposition

Maintenance work decomposes naturally into **waves**, and waves decompose into
**sub-waves**. A wave is a coherent arc — "production-harden the install flow,"
"add WhatsApp as a first-class channel," "extract the catalog-mirror package."
A sub-wave is an internal phase of that arc that has its own definition of done
and can be reviewed on its own clock.

The convention used here is Sub-wave A through Sub-wave D for the most common
shape of multi-package work:

- **Sub-wave A — Ledger foundation.** New entry kinds, new projection
  migrations, schema-level changes. Lands first because everything downstream
  reads from it.
- **Sub-wave B — Domain logic.** The actual feature work: new strategies, new
  reactivities, new readers, new composites. Depends on A's substrate.
- **Sub-wave C — Wiring.** Hub orchestration (in WormBase: `apps/worm-core`):
  boot wires, HTTP endpoints, MCP tools, write actions. Depends on B's surface.
- **Sub-wave D — Dashboard surfaces.** The user-facing readout. Depends on C's
  accessors and Sub-wave A's projection tables.

The shape generalizes: substrate → logic → integration → surface. Different
domains will need different letter-counts, but the principle is the same: each
sub-wave has a single owner per dispatch, lands in its own commit, and is
green-on-its-own before the next sub-wave starts.

Why this works for compounding architecture: each sub-wave creates a stable
contract the next sub-wave depends on. If Sub-wave A's payload schema drifts
mid-wave, every downstream sub-wave has to chase the drift. Lock the substrate
first; build outward.

## The attention-handoff posture

Agent dispatches have wall-clock — typically minutes to tens of minutes. The
orchestrator's attention has wall-clock too. The practice is to pair every
dispatch with an explicit handoff for the human's attention, matched to the
expected duration:

| Dispatch wall-clock | Handoff |
|---|---|
| ~15 min | Grab coffee. One task switch. |
| ~30 min | Walk. Pair the phone. Read a paper. |
| ~1-2 hours | A meeting. Lunch. Deep-focus work in a different repo. |
| Overnight | Sleep. The status note is the morning summary. |

This is not a productivity hack. It is the only way to sustain the practice at
scale: an orchestrator who sits and watches a dispatch run is wasting the
orchestrator's wall-clock; an orchestrator who dispatches without a handoff
ends up context-switching at random intervals and degrading their own scoping
quality. The handoff is part of the dispatch contract.

When a wave is multi-hour and the human will be asleep or otherwise unreachable,
the dispatch grows three additional discipline points:

1. **Locked decisions before sleep.** Any architectural decision the agents
   will need is locked, in writing, in the wave's status file, before the
   handoff. Agents do not improvise architectural decisions.
2. **Commit + push between waves.** Each completed wave lands on the canonical
   branch with a clean commit message. The human wakes to a readable git log,
   not a working tree.
3. **Morning summary.** The last commit of the run appends a summary block to
   the status file: what landed, what shipped, what was deferred, what the
   first question is when the human wakes.

## Parallel dispatch discipline

Sub-waves often have file-disjoint sub-tasks that can run concurrently. When
they do, the dispatch fans out to multiple subagents simultaneously. The
canonical pattern: three concurrent subagents, each owning a disjoint slice
of the codebase, all committing to the canonical branch.

The discipline that makes this safe:

- **Worktrees per concurrent committer.** When two or more subagents will each
  call `git add` + `git commit` + `git push` within their tasks, give each one
  its own `git worktree`. The git index is a shared resource; file-disjoint
  dispatch is *not* sufficient to avoid races on `.git/index`. Even when
  subagents touch disjoint files, both call `git add <files>` and `git commit`
  against the same `.git/index`. If A's `git add` lands between B's `git add`
  and B's `git commit`, B's commit accidentally includes A's staged files.
- **Absolute paths only.** Each subagent operates from its assigned worktree.
  No `cd` to the main worktree. No relative paths. The subagent's `git status`
  should show only its own changes; if it sees peers' files staged, the
  worktree setup is wrong — stop and escalate.
- **Concurrency-aware pulls.** Multiple worktrees point at the same `.git/`;
  `git pull` will reflect peer progress. Subagents should not be surprised by
  this.
- **Sequential dispatch as fallback.** When worktree setup feels heavier than
  the task at hand, fall back to sequential dispatch. Two 15-minute subagents
  run back-to-back finish in 30-minute wall-clock with zero race risk — still
  vastly faster than a human at the keyboard.

When to skip the worktree:

- **Single subagent.** No parallelism, no race possible.
- **Pure docs work, single file.** One `git add docs/...`, no codegen, no
  lockfile mutation. Race surface is negligible.
- **Read-only subagents.** Audits, plans, exploration dispatches that never
  commit.
- **Sequential dispatch.** If subagents will finish one at a time anyway,
  worktrees add overhead without benefit.

Break-even is roughly the second concurrent committing subagent. The setup is
cheap enough that the default for any parallel-commit wave is worktree-on.

## Close-out as compounding state

Every wave ends with a close-out note. The convention here is one file per
wave or sub-wave, dated, in a long-lived `notes/` or `decisions/` directory.
Each close-out contains:

- **Scope as shipped.** Not the scope as planned; the scope as actually merged.
  Deltas from the plan are called out explicitly.
- **Commit trail.** SHAs in order, with one line each describing what they
  shipped. The git log is the source of truth; the close-out is the index.
- **Test counts that moved.** Before-and-after. Net new tests; per-package
  rollups. A regression-free wave produces a monotonically-growing test count
  with zero failures.
- **Substrate state.** If entry kinds, projections, or other schema-level
  state changed, the new counts are recorded in the close-out for the next
  wave's freeze-pause check.
- **Open follow-ups.** Bounded items the wave deferred but did not drop.
  Architectural debt goes here, but only with a sentence or two explaining
  why it was deferred. "We'll fix it later" without context is not a
  follow-up; it's a leak.
- **What the next wave should know.** The single most useful sentence: what
  the next person to touch this part of the codebase needs to be aware of.

Close-outs compound because each one becomes a recipe-template for the next
wave's planning. The orchestrator's first move in scoping a new wave is to
read the relevant close-outs from the last few months. Patterns repeat;
prior decisions are usually still correct; the close-out gives the
orchestrator a running start.

## Anti-patterns to resist

Three failure modes recur often enough to call out by name:

- **Scoping with pre-agent intuitions.** "Three subsystems in eight days is
  too much for a solo developer." That intuition is calibrated to a pre-agent
  workflow. A solo operator with a serious subagent harness routinely runs
  three subsystems in eight days. When a wave feels "too ambitious," check
  the calibration before cutting scope.
- **Sequential execution of parallelizable work.** Two file-disjoint tasks
  should be two concurrent subagents, not two consecutive ones. The largest
  silent tax on velocity is doing serially what could have been done in
  parallel.
- **Rebuilding what the integration substrate already provides.** If your
  agent harness already speaks to Slack, Jira, Notion, GitHub, Postgres,
  whatever — wire the existing adapter and move on. Custom integration code
  is rarely the load-bearing differentiator.

Two further failure modes specific to this practice:

- **Treating specs as optional.** The spec is the project; the code is a
  derivative artifact. Vague specs produce vague code, faster. Invest
  disproportionately in writing the spec before dispatching the work.
- **Skipping the close-out.** Without a close-out, the next wave can't build
  on the prior wave's compounding state. The wave still shipped, but the
  practice did not compound.

## When to stop

A wave ends when its scoped definition of done is met, the gate is green,
and the close-out is written. Three honest endpoints:

1. **Shipped.** The scoped work is done; the wave closes cleanly.
2. **Bounded follow-up.** The wave is done in its critical path but uncovered
   a specific, well-defined piece of work that should land in a follow-up
   wave. Record the follow-up in the close-out, name the next wave, and
   close.
3. **Architectural debt surfaced.** The wave ran into a structural problem
   that cannot be fixed within its scope. The wave closes with a partial
   merge or a revert, and a separate spec is written for the architectural
   work. The follow-up is *not* a wave; it is a spec → plan → wave sequence
   of its own.

When in doubt about whether to ship now or push further: ship now, write the
follow-up. Compounding favors small, frequent commits over large, infrequent
ones. The close-out is the place to record everything that didn't make this
wave; the next wave will pick it up.

## Cross-references

- The architectural pins this practice maintains are in `ARCHITECTURE.md`.
- The contributor-facing dispatch protocol (how to actually open a PR using
  the patterns above) is in `DEVELOPERS.md`.
- Spec-driven plans for individual waves live under `docs/superpowers/plans/`.
- Close-outs for shipped waves live under `docs/superpowers/notes/`.
