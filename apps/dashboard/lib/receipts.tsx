/**
 * Dashboard-side Receipt re-export + ReceiptStrip helper.
 *
 * Receipt itself lives in `@wormbase/design`. We re-export it here so
 * dashboard surfaces have one import path; that import path is also where
 * we mount thin layout helpers like ReceiptStrip (rendering N receipts in a
 * row with thin vertical dividers) without bloating the design package.
 */

import { Receipt as DesignReceipt } from "@wormbase/design";
import type { ReceiptProps as DesignReceiptProps } from "@wormbase/design";
import type { Receipt as ReceiptModel } from "./ledger-client.types";

export type ReceiptProps = DesignReceiptProps;
export const Receipt = DesignReceipt;

/**
 * ReceiptStrip — thin row of N receipts. Used for list rows where a single
 * record may be backed by multiple sources / KPI dependencies.
 */
export function ReceiptStrip({
  receipts,
  compact = true,
}: {
  receipts: ReceiptModel[];
  compact?: boolean;
}) {
  return (
    <div
      data-receipt-strip
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 12,
        rowGap: 4,
        alignItems: "center",
      }}
    >
      {receipts.map((r, i) => (
        <span
          key={`${r.hash}-${i}`}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            paddingRight: 12,
            borderRight:
              i === receipts.length - 1
                ? "none"
                : "1px solid var(--wb-color-paper-edge)",
          }}
        >
          <Receipt
            hash={r.hash}
            source={r.source}
            owner={r.owner}
            classification={r.classification}
            compact={compact}
          />
        </span>
      ))}
    </div>
  );
}
