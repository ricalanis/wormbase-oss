"use client";
/**
 * TraceFilterBar — URL-encoded filter strip for /trace (W2.A10).
 *
 * Renders the filter inputs that narrow the visible trace rows server-side
 * via query string. State is held entirely in `next/navigation`'s
 * `useSearchParams`, so a copy-paste of the URL reproduces the exact
 * filtered view — that's the "shareable filter state" requirement from the
 * production-hardening plan.
 *
 * Filter axes (matches `TraceCursor` in `lib/ledger-client.types.ts`):
 *
 *   - `kind`        — substring match on the derived entry kind
 *                      (e.g. `source_proposed`, `chat_received`).
 *   - `person_id`   — exact match on `payload.actor` /
 *                     `payload.args.{person_id,added_by_person,confirmed_by_person,…}`.
 *   - `channel_id`  — exact match on `payload.args.channel_id`.
 *   - `ts_from`     — ISO8601; entries with `ts < ts_from` drop.
 *   - `ts_to`       — ISO8601; entries with `ts > ts_to` drop.
 *
 * Wire mirrors the `Filters` component used by /data-products: blur-to-commit
 * for free-text inputs, replace-not-push so back-button doesn't accumulate
 * 30 history entries, square wb-mono chrome to fit the editorial style.
 */
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

const INPUT_STYLE: React.CSSProperties = {
  fontFamily: "var(--wb-font-mono)",
  fontSize: 12,
  border: "1px solid var(--wb-color-aged-ink)",
  borderRadius: 0,
  background: "var(--wb-color-paper)",
  padding: "4px 8px",
};

const QUADRANT_OPTIONS = ["", "propose", "execute", "verify", "resolve"];

/**
 * W5.A5 — entry-kind shortcuts for the new reactivity / resource-
 * conversation / phenomenon-gap surfaces. Picking one of these populates
 * the substring `kind` filter so the trace list focuses on the
 * matching emit_* tool entries. Purely additive — the quadrant select
 * still drives the SQL fast-path; this select drives the substring path.
 */
const KIND_SHORTCUTS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "", label: "any kind" },
  { value: "emit_reactivity_proposed", label: "reactivity · proposed" },
  { value: "emit_reactivity_confirmed", label: "reactivity · confirmed" },
  { value: "emit_reactivity_disabled", label: "reactivity · disabled" },
  { value: "emit_reactivity_fired", label: "reactivity · fired" },
  {
    value: "emit_resource_conversation_proposed",
    label: "resource conv · proposed",
  },
  {
    value: "emit_resource_conversation_replied",
    label: "resource conv · replied",
  },
  {
    value: "emit_resource_conversation_resolved",
    label: "resource conv · resolved",
  },
  {
    value: "emit_phenomenon_gap_detected",
    label: "phenomenon-gap · detected",
  },
];

export function TraceFilterBar() {
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

  const clearAll = useCallback(() => {
    router.replace(pathname);
  }, [pathname, router]);

  const activeCount = ["kind", "person_id", "channel_id", "ts_from", "ts_to"].filter(
    (k) => (params.get(k) ?? "").length > 0,
  ).length;

  return (
    <div
      data-testid="trace-filter-bar"
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
        padding: "10px 12px",
        border: "1px solid var(--wb-color-paper-edge)",
        background: "var(--wb-color-paper-deep)",
      }}
    >
      <label>
        kind&nbsp;
        <select
          data-testid="trace-filter-kind"
          value={params.get("kind") ?? ""}
          onChange={(e) => update("kind", e.target.value)}
          style={INPUT_STYLE}
        >
          {QUADRANT_OPTIONS.map((q) => (
            <option key={q || "all"} value={q}>
              {q || "all"}
            </option>
          ))}
        </select>
      </label>
      <label>
        kind contains&nbsp;
        <input
          data-testid="trace-filter-kind-text"
          defaultValue={params.get("kind") ?? ""}
          onBlur={(e) => update("kind", e.target.value)}
          placeholder="e.g. source_proposed"
          style={{ ...INPUT_STYLE, width: 200 }}
        />
      </label>
      <label>
        emit kind&nbsp;
        <select
          data-testid="trace-filter-kind-shortcut"
          value={
            KIND_SHORTCUTS.some((s) => s.value === (params.get("kind") ?? ""))
              ? params.get("kind") ?? ""
              : ""
          }
          onChange={(e) => update("kind", e.target.value)}
          style={INPUT_STYLE}
        >
          {KIND_SHORTCUTS.map((s) => (
            <option key={s.value || "any"} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        person&nbsp;
        <input
          data-testid="trace-filter-person"
          defaultValue={params.get("person_id") ?? ""}
          onBlur={(e) => update("person_id", e.target.value)}
          placeholder="person id"
          style={{ ...INPUT_STYLE, width: 200 }}
        />
      </label>
      <label>
        channel&nbsp;
        <input
          data-testid="trace-filter-channel"
          defaultValue={params.get("channel_id") ?? ""}
          onBlur={(e) => update("channel_id", e.target.value)}
          placeholder="channel id"
          style={{ ...INPUT_STYLE, width: 200 }}
        />
      </label>
      <label>
        from&nbsp;
        <input
          data-testid="trace-filter-ts-from"
          type="datetime-local"
          defaultValue={params.get("ts_from") ?? ""}
          onBlur={(e) => update("ts_from", e.target.value)}
          style={INPUT_STYLE}
        />
      </label>
      <label>
        to&nbsp;
        <input
          data-testid="trace-filter-ts-to"
          type="datetime-local"
          defaultValue={params.get("ts_to") ?? ""}
          onBlur={(e) => update("ts_to", e.target.value)}
          style={INPUT_STYLE}
        />
      </label>
      <button
        type="button"
        data-testid="trace-filter-clear"
        onClick={clearAll}
        disabled={activeCount === 0}
        style={{
          ...INPUT_STYLE,
          cursor: activeCount === 0 ? "default" : "pointer",
          opacity: activeCount === 0 ? 0.5 : 1,
          background: "transparent",
        }}
      >
        clear ({activeCount})
      </button>
    </div>
  );
}
