"use client";
/**
 * DataProductSections — three subsections rendered inside the
 * PersonDetailDrawer (F5):
 *
 *   - Data products requested  (via GET /api/data-products?requested_by=)
 *   - Data products consumed   (via GET /api/data-products/consumption?person_id=)
 *   - Notebooks authored       (via GET /api/notebooks?owner_person_id=)
 *
 * The drawer fetches these on mount; rows render as a thin wb-mono
 * compact list — full detail lives at /data-products/{id} and
 * /notebooks/{id}.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import type {
  DataProductRow,
  DataProductConsumptionRow,
  NotebookRow,
} from "../../lib/ledger-client.types";

interface Props {
  personId: string;
}

interface State {
  requested: DataProductRow[];
  consumed: DataProductConsumptionRow[];
  notebooks: NotebookRow[];
  loading: boolean;
  error: string | null;
}

const SECTION_HEADING_STYLE: React.CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 18,
  fontWeight: 500,
  borderBottom: "1px solid var(--wb-color-paper-edge)",
  paddingBottom: 6,
};

const ROW_STYLE: React.CSSProperties = {
  fontFamily: "var(--wb-font-mono)",
  fontSize: 12,
  color: "var(--wb-color-aged-ink)",
  padding: "4px 0",
};

export function DataProductSections({ personId }: Props) {
  const [state, setState] = useState<State>({
    requested: [],
    consumed: [],
    notebooks: [],
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [reqRes, consRes, nbRes] = await Promise.all([
          fetch(`/api/data-products?requested_by=${encodeURIComponent(personId)}`),
          fetch(
            `/api/people/${encodeURIComponent(personId)}/consumption`,
          ),
          fetch(
            `/api/notebooks?owner_person_id=${encodeURIComponent(personId)}`,
          ),
        ]);
        const reqJson = reqRes.ok ? await reqRes.json() : { dataProducts: [] };
        const consJson = consRes.ok
          ? await consRes.json()
          : { consumption: [] };
        const nbJson = nbRes.ok ? await nbRes.json() : { notebooks: [] };
        if (cancelled) return;
        setState({
          requested: reqJson.dataProducts ?? [],
          consumed: consJson.consumption ?? [],
          notebooks: nbJson.notebooks ?? [],
          loading: false,
          error: null,
        });
      } catch (err) {
        if (cancelled) return;
        setState((s) => ({
          ...s,
          loading: false,
          error: (err as Error).message,
        }));
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [personId]);

  return (
    <>
      <section
        data-testid="drawer-data-products-requested"
        style={{ display: "flex", flexDirection: "column", gap: 10 }}
      >
        <h3 style={SECTION_HEADING_STYLE}>Data products requested</h3>
        {state.loading ? (
          <p style={{ ...ROW_STYLE, color: "var(--wb-color-hash-gray)" }}>
            loading…
          </p>
        ) : state.requested.length === 0 ? (
          <p
            style={{
              ...ROW_STYLE,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            None yet.
          </p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {state.requested.map((dp) => (
              <li key={dp.dataProductId} style={ROW_STYLE}>
                <Link
                  href={`/data-products/${dp.dataProductId}`}
                  style={{ color: "var(--wb-color-aged-ink)" }}
                >
                  {dp.name}
                </Link>{" "}
                <span style={{ color: "var(--wb-color-hash-gray)" }}>
                  · {dp.kind} · {dp.status}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section
        data-testid="drawer-data-products-consumed"
        style={{ display: "flex", flexDirection: "column", gap: 10 }}
      >
        <h3 style={SECTION_HEADING_STYLE}>Data products consumed</h3>
        {state.loading ? (
          <p style={{ ...ROW_STYLE, color: "var(--wb-color-hash-gray)" }}>
            loading…
          </p>
        ) : state.consumed.length === 0 ? (
          <p
            style={{
              ...ROW_STYLE,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            None yet.
          </p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {state.consumed.map((c) => (
              <li key={c.consumptionId} style={ROW_STYLE}>
                <Link
                  href={`/data-products/${c.dataProductId}`}
                  style={{ color: "var(--wb-color-aged-ink)" }}
                >
                  {c.dataProductId.slice(0, 8)}…
                </Link>{" "}
                <span style={{ color: "var(--wb-color-hash-gray)" }}>
                  · {c.surface} · {new Date(c.ts).toISOString().slice(0, 19)}Z
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section
        data-testid="drawer-notebooks-authored"
        style={{ display: "flex", flexDirection: "column", gap: 10 }}
      >
        <h3 style={SECTION_HEADING_STYLE}>Notebooks authored</h3>
        {state.loading ? (
          <p style={{ ...ROW_STYLE, color: "var(--wb-color-hash-gray)" }}>
            loading…
          </p>
        ) : state.notebooks.length === 0 ? (
          <p
            style={{
              ...ROW_STYLE,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            None yet.
          </p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {state.notebooks.map((nb) => (
              <li key={nb.notebookId} style={ROW_STYLE}>
                <Link
                  href={`/notebooks/${nb.notebookId}`}
                  style={{ color: "var(--wb-color-aged-ink)" }}
                >
                  {nb.name}
                </Link>{" "}
                <span style={{ color: "var(--wb-color-hash-gray)" }}>
                  · {nb.kernel} · {nb.status}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
