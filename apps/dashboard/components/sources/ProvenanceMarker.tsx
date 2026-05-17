import type { SourceFlow } from "../../lib/ledger-client.types";

const FLOW_TREATMENT: Record<
  SourceFlow,
  { color: string; style: "solid" | "dashed" }
> = {
  drop_and_profile: { color: "var(--wb-color-botanical-green)", style: "solid" },
  credential_offered_in_dm: { color: "var(--wb-color-aged-ink)", style: "solid" },
  mentioned_in_conversation: { color: "var(--wb-color-hash-gray)", style: "solid" },
  dashboard_form: { color: "var(--wb-color-sepia-warning)", style: "solid" },
  kpi_gap_triggered: { color: "var(--wb-color-botanical-green)", style: "dashed" },
  // Step 2 of the canonical product arc — see
  // docs/superpowers/specs/2026-04-26-wormbase-product-arc.md.
  lake_discovery: { color: "var(--wb-color-aged-ink)", style: "dashed" },
  // Block I: the default lake provisions on install. Distinct treatment
  // (heavy ink rule) marks "this came from the install act itself, not
  // from any of the five user-driven flows".
  provisioned_at_install: { color: "var(--wb-color-aged-ink)", style: "solid" },
};

export interface ProvenanceMarkerProps {
  addedByPerson: string;
  addedAt: string;
  addedViaFlow: SourceFlow;
  addedInResponseTo: string | null;
}

export function ProvenanceMarker({
  addedByPerson,
  addedAt,
  addedViaFlow,
  addedInResponseTo,
}: ProvenanceMarkerProps) {
  const treatment = FLOW_TREATMENT[addedViaFlow];
  return (
    <div
      data-testid="provenance-marker"
      data-flow={addedViaFlow}
      style={{
        borderLeft: `2px ${treatment.style} ${treatment.color}`,
        paddingLeft: 12,
        fontFamily: "var(--wb-font-mono)",
        fontSize: 11,
        lineHeight: 1.55,
        color: "var(--wb-color-aged-ink-soft)",
      }}
    >
      added by{" "}
      <span style={{ color: "var(--wb-color-aged-ink)" }}>@{addedByPerson}</span>{" "}
      at <span style={{ color: "var(--wb-color-aged-ink)" }}>{addedAt}</span>{" "}
      via <span style={{ color: "var(--wb-color-aged-ink)" }}>{addedViaFlow}</span>
      {addedInResponseTo ? (
        <>
          {" "}
          in response to{" "}
          <span style={{ color: "var(--wb-color-aged-ink-soft)", fontStyle: "italic" }}>
            {addedInResponseTo}
          </span>
        </>
      ) : null}
    </div>
  );
}
