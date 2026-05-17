# `/notebooks` — User guide

## What it does

The Notebooks tab lists every notebook in the tenant — both **authored
notebooks** (admin or maintainer wrote them) and **autoresearch-published
notebooks** (the per-user research loop's wins, automatically promoted to
notebook artifacts). Each notebook is multi-cell, replayable, and
**signable**: a published version carries a per-Person signature receipt.

Each row carries: name, kernel (`python_local` ships day one), owner Person
+ domain, status (`draft` / `published`), version, latest run id, and a
diff chip if the latest run differs from the latest published.

This is the data engineer's daily surface. CFOs and data owners use it
weekly to inspect autoresearch wins.

## First action

Open an autoresearch-published notebook:

1. Navigate to `/notebooks`. Filter by `owner_person_id=me` to see your
   personal autoresearch wins.
2. Click any row. The notebook viewer renders cell-by-cell — markdown +
   code + outputs side-by-side.
3. Scroll through. Each "keep" experiment from your autoresearch loop is
   a notebook with: hypothesis (markdown), query setup (code), metric
   calc (code), result line (markdown). The metric delta lives **inside**
   the notebook, not just on a dashboard tile.

To author from scratch (admin / maintainer):

1. Click **New notebook**. Pick kernel + owner domain.
2. Add cells (markdown / code / sql). The editor is YAML-spec under the
   hood — every cell is `{kind, source, language}`.
3. Click **Run** to execute against the lake. Each run writes
   `emit_notebook_run` with cell outputs + cell hashes + kernel state hash.
4. Click **Publish** to promote a run to a published version. Writes
   `emit_notebook_published` with `version=N`.

## Advanced

- **Sign a notebook** — per-Person cryptographic signature. Click **Sign**
  on a published version; writes `emit_notebook_published` with
  `signature=<bearer-derived>`. Auditors verify by replaying the run and
  comparing the signature.
- **Replay** — open any published version → **Replay**. Re-runs the YAML
  spec against pinned source-hashes; the new run's `kernel_state_hash`
  must match the original (writes `emit_notebook_run` with
  `replay_of=<original_run_id>`). If hashes differ, the row flags
  "source drift" or "code drift."
- **Diff two runs** — open the **Diff** view; pick two runs. The viewer
  shows cell-level diffs in source + output.
- **Export to .ipynb** — the YAML-spec converts to standard Jupyter
  format on demand. Useful for handoffs to data scientists outside the
  tenant.
- **Resource limits** — cells time out at 30s default. Memory cap at
  512MB. Out-of-bounds runs write `emit_notebook_run` with
  `status=error`. Admins can extend per-notebook via `/settings`.
- **Schedule** — published notebooks can be re-run on a schedule. Writes
  `emit_notebook_run` weekly (or daily / monthly).

## Behind the scenes

Reads from `projection_notebooks` + `projection_notebook_runs`, folds of:

```
emit_notebook_proposed       (form or autoresearch)
emit_notebook_run            (every cell execution batch)
emit_notebook_published      (version promotion + signature)
emit_notebook_archived
```

Notebook source lives as YAML-spec (cells = list of
`{kind: "code"|"markdown"|"sql", source: str, language: str}`). Simpler
than `.ipynb`, easier to diff in PRs. The kernel lives in worm-core's
notebook subsystem (`apps/worm-core/src/wormbase_core/notebook_kernel.py`)
— a sandboxed Python subprocess with `pandas`, `numpy`, `matplotlib`
available, the lake's silver/gold tables exposed as DataFrames via the
Connector adapter.

Cell-level provenance: each cell's output carries the hash of its inputs
(predecessor cell outputs + source data). Replay determinism guaranteed
at the cell level — a re-run with the same inputs produces a bit-identical
output hash, and the kernel state hash matches.

## Autoresearch promotion

When an experiment in `/research` resolves with `outcome=keep`, the
autoresearch loop publishes a notebook artifact summarizing it:

```
hypothesis (markdown)        ← the proposed change + expected delta
query setup (code)           ← the data pull
metric calc (code)           ← the evaluation
result (markdown)            ← the observed delta + keep rationale
```

The notebook lives at `/notebooks/<auto>` with `owner_person_id=<the
Person the loop ran for>`. The worm authors on their behalf. The keep is
a **tracked, replayable artifact** — owner attribution, version pinned,
kernel state hash pinned. Six months of this and the seat compiles into
a notebook library that audits.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Cell error: "kernel timeout" | Default 30s cap exceeded | Raise cap via `/settings` (admin); refactor cell |
| Replay flags "source drift" | A pinned source has been re-bronzed | Run a fresh version (new id) or restore the old bronze hash |
| Sign button absent | Current Person not maintainer or admin | Ask owner for `resource.maintainer` grant |
| Notebook viewer 404s | Run id deleted; try latest run instead | Open the row again to fetch the current latest |
| Autoresearch notebooks empty | Position not assigned, or loop not run for current Person | Confirm position via `/people/{me}`; wait one autoresearch cycle |
