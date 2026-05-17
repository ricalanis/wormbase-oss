# Developers — contributing to WormBase

WormBase is maintained via agent-orchestrated waves. Most non-trivial changes
land through a scoped dispatch pattern rather than a single human typing at
the keyboard. Contributors do not have to use that pattern — straightforward
PRs are welcome — but understanding it makes larger contributions easier to
plan, scope, and merge cleanly.

For the architectural pins this practice maintains, read `ARCHITECTURE.md`.
For the distilled methodology behind the pattern (why waves, why
close-outs, what makes the practice compound), read
`docs/AUTONOMOUS_MAINTENANCE_PLAYBOOK.md`. This file covers the **how to
contribute** specifics.

## Contributing via agent-orchestrated maintenance

### The dispatch primitive

A scoped contribution has a fixed shape:

1. **Scope it.** Write a short paragraph: what is in, what is out, which
   files will change, which tests will move, and what "done" looks like.
   If the scope cannot fit on a screen, cut it smaller.
2. **Dispatch.** Hand the scoped work to a subagent (or write the code
   yourself) with the spec, the file paths, the test paths, and the
   acceptance gate. The work runs to completion or to a blocker; it does
   not negotiate scope mid-flight.
3. **Review.** Read the diff. Run the gate (`make qa` or the relevant
   targeted command). Confirm the spec was honored.
4. **Commit.** One atomic commit per scoped arc. The commit message
   records what landed, the test counts that moved, and any entry-kind
   counts that moved.
5. **Close-out.** Append a short note to the relevant wave file in
   `docs/superpowers/notes/` capturing what shipped, what was deferred,
   and what the next contributor should know.

Contributions that don't fit this shape (one-off doc edits, single-file
typo fixes, dependency bumps) are welcome as direct PRs without the full
ceremony.

### The attention-handoff posture

Agent dispatches have wall-clock — typically minutes to tens of minutes.
The contributor's attention has wall-clock too. The practice is to pair
every dispatch with an explicit handoff: a non-blocking activity matched
to the expected duration.

The point is not productivity theater. An orchestrator who sits and
watches a dispatch run is wasting their own time; one who context-switches
at random degrades their scoping quality. The handoff makes the wait
deliberate.

For multi-hour and overnight runs, the discipline grows three additional
points: any architectural decision the agents will need is locked in
writing before the handoff; each completed wave commits and pushes to the
canonical branch so peers wake to a readable git log; the last commit of
the run appends a summary to the wave's status file.

### Parallel-worktree discipline

Many waves have file-disjoint sub-tasks that can run concurrently. When
they do, the dispatch fans out to multiple subagents simultaneously.

**When two or more concurrent subagents will each commit and push within
their tasks, give each one its own `git worktree`.** The git index is a
shared resource; file-disjoint dispatch is *not* sufficient to avoid
races on `.git/index`. Even when subagents touch disjoint files, both
call `git add <files>` and `git commit` against the same `.git/index`,
and an interleaving of those calls can pick up the wrong staging.

```bash
# Setup, once per concurrent subagent
git worktree add /tmp/wormbase-wave-N-path-X main

# Dispatch each subagent with the assigned working directory as its cwd.
# The subagent commits to main (or to a short-lived branch) inside the worktree.

# After all parallel subagents complete:
# - Direct-to-main commits serialize cleanly at the remote; orchestrator
#   pulls and verifies.
# - Branch-based commits are merged by the orchestrator.

# Cleanup
git worktree remove /tmp/wormbase-wave-N-path-X
```

The subagent never `cd`'s to the main worktree. Absolute paths only,
all rooted in the assigned worktree. The subagent's `git status` should
show only its own changes; if it sees peers' files staged, the worktree
setup is wrong — stop and escalate.

#### When to skip the worktree

Worktree overhead is small but not zero. Skip when the benefit is also
zero:

- **Single subagent.** No parallelism, no race surface.
- **Pure docs work, single file.** One `git add docs/...`, no codegen,
  no lockfile mutation.
- **Read-only subagents.** Audits, plans, exploration dispatches that
  never commit.
- **Sequential dispatch.** If subagents will finish one at a time
  anyway, worktrees add overhead without benefit.

Break-even is roughly the second concurrent committing subagent. The
default for any parallel-commit wave is worktree-on.

#### Anti-pattern: shared-tree parallel commit

When NOT to dispatch parallel work against a shared tree:

- Two subagents both calling `git add` against the same `.git/index`.
- Two subagents both attempting to push (push serializes at the remote,
  but the local index does not; the loser sees stale or contaminated
  commits).
- Two subagents both running `pnpm install` (the `pnpm-lock.yaml` race).
- Two subagents both running a codegen step that writes the same file.

If worktree setup feels too heavy for the task at hand, fall back to
**sequential dispatch**. Two short subagents run back-to-back finish in
roughly the sum of their wall-clocks, with zero race risk.

### Close-out as compounding state

Every wave ends with a close-out note. The convention is one file per
wave or sub-wave, dated, in `docs/superpowers/notes/`. The close-out
contains:

- **Scope as shipped.** Not as planned. Deltas from the plan are called
  out explicitly.
- **Commit trail.** SHAs in order, one line each describing what they
  shipped.
- **Test counts that moved.** Before-and-after, per-package rollups.
- **Substrate state.** If entry kinds or projections changed, the new
  counts are recorded.
- **Open follow-ups.** Bounded items the wave deferred but did not drop,
  each with a sentence on why.
- **What the next wave should know.** The single most useful sentence
  for the next contributor in this area.

Close-outs compound: the first move in scoping a new wave is to read the
relevant close-outs from the last few months. Patterns repeat; prior
decisions are usually still correct; the close-out gives the next
contributor a running start.

## Cross-references

- `ARCHITECTURE.md` — the architectural pins this practice maintains.
- `docs/AUTONOMOUS_MAINTENANCE_PLAYBOOK.md` — distilled methodology behind
  the practice.
- `docs/superpowers/specs/` — authoritative deep dives on individual
  subsystems.
- `docs/superpowers/plans/` — wave-level plans before they are dispatched.
- `docs/superpowers/notes/` — close-out notes from shipped waves.
