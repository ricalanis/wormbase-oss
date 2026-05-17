"use client";
/**
 * DecisionsClient — client wrapper that composes ``DecisionsTable``
 * with ``DecisionDetailDrawer`` (W2.A7).
 *
 * The /decisions page is a server component that queries the ledger
 * projection and hands the rows here. Row click opens the inspect
 * drawer; the page header's "Record decision" button opens the
 * record-mode drawer.
 *
 * Intentionally thin: the table and drawer carry their own visual
 * weight; this file only wires them together so the server component
 * stays a pure data-fetcher.
 */
import { useState } from "react";
import type { DecisionRow } from "../../lib/ledger-client.types";
import { Button } from "@wormbase/design";
import { DecisionsTable } from "../process/DecisionsTable";
import { DecisionDetailDrawer } from "./DecisionDetailDrawer";

export interface DecisionsClientProps {
  rows: DecisionRow[];
}

type DrawerState =
  | { open: false }
  | { open: true; mode: "inspect"; decision: DecisionRow }
  | { open: true; mode: "record"; decision: null };

export function DecisionsClient({ rows }: DecisionsClientProps) {
  const [state, setState] = useState<DrawerState>({ open: false });

  const handleRowClick = (decision: DecisionRow) =>
    setState({ open: true, mode: "inspect", decision });
  const openRecord = () =>
    setState({ open: true, mode: "record", decision: null });
  const closeDrawer = () => setState({ open: false });

  return (
    <>
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          paddingBottom: 12,
        }}
      >
        <Button
          data-testid="decisions-record-open"
          variant="primary"
          size="sm"
          onClick={openRecord}
        >
          Record decision
        </Button>
      </div>
      <DecisionsTable rows={rows} onRowClick={handleRowClick} />
      <DecisionDetailDrawer
        open={state.open}
        mode={state.open ? state.mode : "inspect"}
        decision={state.open && state.mode === "inspect" ? state.decision : null}
        onClose={closeDrawer}
      />
    </>
  );
}
