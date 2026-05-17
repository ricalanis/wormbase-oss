"use client";
/**
 * Filters — domain / person / kind / status filters for /data-products.
 *
 * URL-driven filters (search params) so the filter state is shareable. The
 * server page reads the query params and passes them to listDataProducts.
 */
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

const KINDS = ["", "chart", "table", "report"];
const STATUSES = ["", "proposed", "generated", "archived"];

const SELECT_STYLE: React.CSSProperties = {
  fontFamily: "var(--wb-font-mono)",
  fontSize: 12,
  border: "1px solid var(--wb-color-aged-ink)",
  borderRadius: 0,
  background: "var(--wb-color-paper)",
  padding: "4px 8px",
};

export function Filters() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const update = useCallback(
    (key: string, value: string) => {
      const next = new URLSearchParams(params.toString());
      if (value) next.set(key, value);
      else next.delete(key);
      router.replace(`${pathname}?${next.toString()}`);
    },
    [params, pathname, router],
  );

  return (
    <div
      data-testid="data-products-filters"
      style={{
        display: "flex",
        gap: 12,
        alignItems: "center",
        flexWrap: "wrap",
        fontFamily: "var(--wb-font-mono)",
        fontSize: 11,
        color: "var(--wb-color-hash-gray)",
        textTransform: "uppercase",
        letterSpacing: "0.08em",
      }}
    >
      <label>
        kind&nbsp;
        <select
          value={params.get("kind") ?? ""}
          onChange={(e) => update("kind", e.target.value)}
          style={SELECT_STYLE}
        >
          {KINDS.map((k) => (
            <option key={k || "all"} value={k}>
              {k || "all"}
            </option>
          ))}
        </select>
      </label>
      <label>
        status&nbsp;
        <select
          value={params.get("status") ?? ""}
          onChange={(e) => update("status", e.target.value)}
          style={SELECT_STYLE}
        >
          {STATUSES.map((s) => (
            <option key={s || "all"} value={s}>
              {s || "all"}
            </option>
          ))}
        </select>
      </label>
      <label>
        domain&nbsp;
        <input
          defaultValue={params.get("domain_id") ?? ""}
          onBlur={(e) => update("domain_id", e.target.value)}
          placeholder="domain id"
          style={{ ...SELECT_STYLE, width: 220 }}
        />
      </label>
      <label>
        person&nbsp;
        <input
          defaultValue={params.get("requested_by") ?? ""}
          onBlur={(e) => update("requested_by", e.target.value)}
          placeholder="person id"
          style={{ ...SELECT_STYLE, width: 220 }}
        />
      </label>
    </div>
  );
}
