# @wormbase/dashboard

Next.js 15 + Tailwind dashboard rendering every WormBase surface (onboarding, ramp gauges, KPI tree, trace stream, governance lenses, sources). Consumes the ledger read-side via `packages/ledger` projections and the design system from `packages/design`; all data is tenant-scoped by `company_id`. Run with `pnpm --filter @wormbase/dashboard dev` once Phase 1A lands the Field Notebook design system.

## Step 3 — Build Concurrently

The `/kpis`, `/domains`, and `/policies` views realize **Step 3 of the canonical 5-step product arc** — see `docs/superpowers/specs/2026-04-26-wormbase-product-arc.md` (Steps 3a + 3b). They are **dynamic, live-polling, on-thesis** views designed to be the demo's show-window for "the worm is doing the bookkeeping you'd never get around to":

- **`/kpis`** (`components/kpi/KpiTreeView.tsx`) — KPI tree as a React Flow graph (`@xyflow/react`). Click any node to inspect its formula, source URIs, owner, classification, and receipt in the side panel. Polls `/api/kpi-tree/refresh` every 5s — the cadence at which "live polling makes the worm feel alive."
- **`/domains`** (`components/domains/DomainCardGrid.tsx`) — domain cards in a grid. Inline owner reassignment via dropdown (`@dnd-kit/core` powers resource → domain drag-and-drop). Optimistic UI; reverts on error. Polls `/api/governance/domain` every 10s.
- **`/policies`** (`components/policies/PolicyTable.tsx`) — sortable table with inline classification editing. Each change re-emits an `emit_policy_applied` execute entry; the read-side picks the latest per `policy_id`. Polls `/api/governance/policy` every 10s.

### Live-polling helper

`lib/use-poll.ts` exposes `usePoll(fn, { intervalMs })` — a tiny client-side hook used across the three views (and by `/research` later). It pauses on `document.hidden`, dedupes in-flight requests, and exposes `lastTickAt` so views can render "live · 2s ago" badges that make polling visible to the audience.

### Governance write routes

- `POST /api/governance/domain` — `{domain_id, owner_person_id?}` → `emit_domain_owner_assigned`.
- `POST /api/governance/policy` — `{policy_id, classification?}` → re-emits `emit_policy_applied` with the new classification.
- `GET /api/kpi-tree/refresh` — returns the latest `getKpiTree(companyId)` for the React Flow client.

All three writes attempt a real Postgres ledger insert via `lib/ledger-client.ts` and fall back to a synthetic receipt when Postgres is unavailable — same fixture-bias the read paths use, so the dashboard stays receipted in dev and during demo recovery.

### Conventions

- TypeScript strict; server components for static parts, client components for interactivity.
- Field-Notebook color tokens only (`packages/design/src/tokens/colors.ts`). No SaaS-pastel colors, no `rounded-lg/xl/full`, no gradients (`scripts/lint-anti-patterns.ts` enforces this in CI).
- No new global state libraries — extend `lib/tenant-context.tsx` if cross-route state grows; otherwise local `useState` is the rule.
