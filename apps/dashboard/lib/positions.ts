/**
 * Canonical position registry.
 *
 * Mirrors `apps/worm-core/src/wormbase_core/positions.py`. Hardcoded here
 * so the onboarding wizard can render a position dropdown without
 * round-tripping to the worm-core service. If positions change in the
 * Python registry, update this list.
 *
 * Lives in `lib/` (not in the route file) because Next.js routes are
 * strict about non-handler exports — only `dynamic`, `revalidate`,
 * `runtime`, and the HTTP method handlers are allowed at the top level.
 * Sharing constants between routes goes through `lib/`.
 */

export interface PositionOption {
  id: string;
  label: string;
  description: string;
}

export const POSITIONS: PositionOption[] = [
  {
    id: "cfo",
    label: "CFO",
    description: "Revenue, runway, CAC payback, net burn.",
  },
  {
    id: "cmo",
    label: "CMO",
    description: "Retention, channel mix, viral coefficient, ad-spend efficiency.",
  },
  {
    id: "data_engineer",
    label: "Data engineer",
    description: "Pipeline P95 latency, schema drift, query cost.",
  },
  {
    id: "marketing_lead",
    label: "Marketing lead",
    description: "MQL→SQL ratio, campaign lift, creative CTR.",
  },
  {
    id: "ops_manager",
    label: "Ops manager",
    description: "Ticket P95 resolution, on-call paging, incidents 7d.",
  },
  {
    id: "customer_success",
    label: "Customer success",
    description: "NPS, renewal rate, at-risk accounts.",
  },
  {
    id: "founder",
    label: "Founder",
    description: "Revenue, runway, hiring velocity, strategy cadence.",
  },
  {
    id: "admin",
    label: "Admin",
    description: "Policy violations, ramp completeness, source coverage.",
  },
  {
    id: "product_manager",
    label: "Product manager",
    description: "Activation, feature adoption (P7), DAU/WAU.",
  },
];
