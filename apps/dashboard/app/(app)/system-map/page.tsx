import {
  getProcessMapDataProducts,
  getSystemMap,
} from "../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";
import { SystemMapGraph } from "../../../components/process/SystemMapGraph";
import { ConversationProcessMaps } from "../../../components/system-map/ConversationProcessMaps";
import { PageBoundary } from "../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · System map" };

/**
 * /system-map — Step 3c of the canonical product arc (process retrieval).
 *
 * Renders the org graph the worm has inferred from channel chatter:
 * persons + channels as nodes, edges weighted by message count. Reads
 * ``emit_system_map_node`` ledger entries (the most-recent flush per node).
 *
 * Also renders the P10 "Conversation Process Maps" lens below the
 * primary graph: process_map data products mined from recurring
 * threaded questions, each click-expandable into an edge table with a
 * link out to the canonical /data-products/{id} surface for confirm/
 * archive.
 */
export default async function SystemMapPage() {
  const companyId = await getCurrentCompanyId();
  const [payload, processMaps] = await Promise.all([
    getSystemMap(companyId),
    // P10 — process_map gold artifacts mined from chatter. Rendered
    // as an additive lens below the system-map graph; absence is
    // explicitly empty-stated, never silent.
    getProcessMapDataProducts(companyId),
  ]);

  return (
    <PageBoundary surface="system map" traceQuery="?surface=system-map">
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Pl. IX · Process retrieval · live
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 34,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
        >
          System map · {payload.nodes.length} node{payload.nodes.length === 1 ? "" : "s"}
        </h1>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Persons + channels arranged on concentric rings; edges weighted by
          message count. The worm flushes the running tally every cycle, so
          this graph compounds rather than re-derives at every load.
        </p>
      </header>

      <SystemMapGraph payload={payload} />

      <ConversationProcessMaps processMaps={processMaps} />
    </PageBoundary>
  );
}
