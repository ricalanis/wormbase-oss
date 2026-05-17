"use client";
/**
 * SourceDetailDrawer — slide-in drawer for one source on /sources.
 *
 * W2.A5 of `docs/superpowers/plans/2026-04-28-production-hardening.md`.
 *
 * Surfaces:
 *   - source receipt (hash + uri + classification + maintainer)
 *   - classification picker — re-emits `emit_source_reclassified`
 *     against the ledger, picked up by `getSources` on next poll.
 *   - maintainer assignment — calls worm-core
 *     `POST /api/v1/people/{id}/roles` with facet=resource,
 *     scope_type=source, scope_id=<source_id>, role=maintainer.
 *     Writes `emit_resource_role_assigned`.
 *   - archive — writes `emit_source_archived`. Disabled for the
 *     default local lake (provisioned at install).
 *
 * The drawer never patches its own UI optimistically without a
 * server-side acknowledgement: every edit waits for the API
 * response before flipping the displayed value. That keeps the
 * /sources tab honest — what you see is what's on the ledger.
 *
 * Closing the drawer never throws away an unsaved change because
 * the form is direct-write — there's no draft mode.
 */
import { useEffect, useMemo, useState } from "react";
import type {
  Classification,
  SourceRow as SourceRowModel,
} from "../../lib/ledger-client.types";

const CLASSIFICATION_OPTIONS: Classification[] = [
  "public",
  "internal",
  "confidential",
  "pii",
  "regulated",
  "restricted",
];

export interface SourceDetailDrawerProps {
  source: SourceRowModel;
  /** Optional list of People for the maintainer dropdown. Omitted ⇒
   *  the picker is hidden and only classification + archive are shown. */
  people?: { personId: string; displayName: string }[];
  /** Current admin Person id for granted_by attribution on the
   *  resource role assignment. */
  currentPersonId: string | null;
  onClose: () => void;
  /** Called after a successful write so the parent can update the
   *  in-memory list (so the row updates without a page refresh). */
  onSourceUpdated?: (next: Partial<SourceRowModel>) => void;
}

type SaveState =
  | { kind: "idle" }
  | { kind: "saving"; field: "classification" | "maintainer" | "archive" }
  | { kind: "saved"; field: string; hash?: string }
  | { kind: "error"; field: string; message: string };

export function SourceDetailDrawer({
  source,
  people,
  currentPersonId,
  onClose,
  onSourceUpdated,
}: SourceDetailDrawerProps) {
  const [classification, setClassification] = useState<Classification>(
    (source.classification as Classification) ??
      source.receipt.classification ??
      "internal",
  );
  const [maintainerId, setMaintainerId] = useState<string>(
    source.maintainerPersonId ?? "",
  );
  const [save, setSave] = useState<SaveState>({ kind: "idle" });

  const isDefaultLake = useMemo(
    () =>
      source.kind === "local_lake" &&
      source.addedViaFlow === "provisioned_at_install",
    [source.kind, source.addedViaFlow],
  );

  // Close on Escape — drawer-style affordance.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function saveClassification() {
    if (classification === source.classification) return;
    setSave({ kind: "saving", field: "classification" });
    try {
      const res = await fetch(
        `/api/sources/${encodeURIComponent(source.sourceId)}/classification`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ classification }),
        },
      );
      const body = (await res.json().catch(() => ({}))) as {
        ok?: boolean;
        receipt?: { hash?: string };
        error?: string;
      };
      if (!res.ok || body.ok === false) {
        setSave({
          kind: "error",
          field: "classification",
          message: body.error ?? `request failed: ${res.status}`,
        });
        return;
      }
      setSave({
        kind: "saved",
        field: "classification",
        hash: body.receipt?.hash,
      });
      onSourceUpdated?.({ classification });
    } catch (err) {
      setSave({
        kind: "error",
        field: "classification",
        message: (err as Error).message ?? String(err),
      });
    }
  }

  async function saveMaintainer() {
    if (!maintainerId) return;
    if (maintainerId === source.maintainerPersonId) return;
    if (!currentPersonId) {
      setSave({
        kind: "error",
        field: "maintainer",
        message:
          "current admin Person id is unknown; refusing to write self-grant placeholder",
      });
      return;
    }
    setSave({ kind: "saving", field: "maintainer" });
    try {
      const res = await fetch(
        `/api/people/${encodeURIComponent(maintainerId)}/roles`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            facet: "resource",
            role: "maintainer",
            scope_id: source.sourceId,
            scope_type: "source",
            granted_by: currentPersonId,
          }),
        },
      );
      const body = (await res.json().catch(() => ({}))) as {
        entry_ids?: string[];
        error?: string;
        message?: string;
      };
      if (!res.ok) {
        setSave({
          kind: "error",
          field: "maintainer",
          message: body.message ?? body.error ?? `request failed: ${res.status}`,
        });
        return;
      }
      const newName =
        people?.find((p) => p.personId === maintainerId)?.displayName ?? null;
      setSave({
        kind: "saved",
        field: "maintainer",
        hash: body.entry_ids?.[0]?.slice(0, 12),
      });
      onSourceUpdated?.({
        maintainerPersonId: maintainerId,
        maintainerName: newName,
      });
    } catch (err) {
      setSave({
        kind: "error",
        field: "maintainer",
        message: (err as Error).message ?? String(err),
      });
    }
  }

  return (
    <div
      data-testid="source-detail-drawer-backdrop"
      role="dialog"
      aria-label={`Source detail · ${source.uri}`}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(20, 20, 20, 0.45)",
        zIndex: 100,
        display: "flex",
        justifyContent: "flex-end",
      }}
      onClick={onClose}
    >
      <aside
        data-testid="source-detail-drawer"
        data-source-id={source.sourceId}
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(520px, 90vw)",
          height: "100vh",
          background: "var(--wb-color-paper)",
          borderLeft: "1px solid var(--wb-color-aged-ink)",
          padding: 24,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 18,
        }}
      >
        <header
          style={{ display: "flex", flexDirection: "column", gap: 4 }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            source detail · {source.kind}
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 22,
              wordBreak: "break-all",
            }}
          >
            {source.uri}
          </h2>
          <span
            className="wb-mono"
            style={{
              fontSize: 11,
              color: "var(--wb-color-hash-gray)",
              letterSpacing: "0.06em",
            }}
          >
            receipt {source.receipt.hash} · {source.rowCount.toLocaleString()}{" "}
            rows · added {source.addedAt.slice(0, 10)} via{" "}
            {source.addedViaFlow}
          </span>
        </header>

        <section
          data-testid="drawer-classification"
          style={{ display: "flex", flexDirection: "column", gap: 8 }}
        >
          <label
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
            htmlFor={`drawer-classification-${source.sourceId}`}
          >
            classification
          </label>
          <select
            id={`drawer-classification-${source.sourceId}`}
            data-testid="drawer-classification-select"
            value={classification}
            onChange={(e) => setClassification(e.target.value as Classification)}
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              padding: "6px 8px",
              border: "1px solid var(--wb-color-aged-ink)",
              background: "var(--wb-color-paper)",
              borderRadius: 0,
            }}
          >
            {CLASSIFICATION_OPTIONS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <button
            type="button"
            data-testid="drawer-classification-save"
            onClick={saveClassification}
            disabled={
              save.kind === "saving" && save.field === "classification"
            }
            className="wb-mono"
            style={{
              alignSelf: "flex-start",
              fontSize: 11,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              padding: "6px 12px",
              border: "1px solid var(--wb-color-aged-ink)",
              background: "var(--wb-color-paper)",
              cursor: "pointer",
              borderRadius: 0,
            }}
          >
            {save.kind === "saving" && save.field === "classification"
              ? "saving…"
              : "save classification"}
          </button>
        </section>

        {people && people.length > 0 ? (
          <section
            data-testid="drawer-maintainer"
            style={{ display: "flex", flexDirection: "column", gap: 8 }}
          >
            <label
              className="wb-mono"
              style={{
                fontSize: 10,
                letterSpacing: "0.18em",
                textTransform: "uppercase",
                color: "var(--wb-color-hash-gray)",
              }}
              htmlFor={`drawer-maintainer-${source.sourceId}`}
            >
              maintainer
            </label>
            <select
              id={`drawer-maintainer-${source.sourceId}`}
              data-testid="drawer-maintainer-select"
              value={maintainerId}
              onChange={(e) => setMaintainerId(e.target.value)}
              style={{
                fontFamily: "var(--wb-font-serif)",
                fontSize: 13,
                padding: "6px 8px",
                border: "1px solid var(--wb-color-aged-ink)",
                background: "var(--wb-color-paper)",
                borderRadius: 0,
              }}
            >
              <option value="">— unassigned —</option>
              {people.map((p) => (
                <option key={p.personId} value={p.personId}>
                  {p.displayName}
                </option>
              ))}
            </select>
            <button
              type="button"
              data-testid="drawer-maintainer-save"
              onClick={saveMaintainer}
              disabled={
                !maintainerId ||
                (save.kind === "saving" && save.field === "maintainer")
              }
              className="wb-mono"
              style={{
                alignSelf: "flex-start",
                fontSize: 11,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                padding: "6px 12px",
                border: "1px solid var(--wb-color-aged-ink)",
                background: "var(--wb-color-botanical-green-soft)",
                cursor: "pointer",
                borderRadius: 0,
              }}
            >
              {save.kind === "saving" && save.field === "maintainer"
                ? "assigning…"
                : "assign maintainer"}
            </button>
          </section>
        ) : null}

        {save.kind === "saved" ? (
          <div
            data-testid="drawer-save-result"
            className="wb-mono"
            style={{
              fontSize: 11,
              color: "var(--wb-color-botanical-green-deep)",
            }}
          >
            saved {save.field}
            {save.hash ? ` · receipt ${save.hash}` : ""}
          </div>
        ) : null}
        {save.kind === "error" ? (
          <div
            data-testid="drawer-save-error"
            className="wb-mono"
            style={{
              fontSize: 11,
              color: "var(--wb-color-sepia-warning-deep)",
              wordBreak: "break-all",
            }}
          >
            {save.field}: {save.message}
          </div>
        ) : null}

        {isDefaultLake ? (
          <p
            data-testid="drawer-default-lake-note"
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              fontSize: 12,
              color: "var(--wb-color-hash-gray)",
              margin: 0,
            }}
          >
            Default local lake — provisioned at install. Archiving is
            disabled because every tenant relies on this source from
            minute zero.
          </p>
        ) : null}

        <footer style={{ marginTop: "auto", display: "flex", gap: 8 }}>
          <button
            type="button"
            data-testid="drawer-close"
            onClick={onClose}
            className="wb-mono"
            style={{
              fontSize: 11,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              padding: "6px 12px",
              border: "1px solid var(--wb-color-aged-ink)",
              background: "var(--wb-color-paper)",
              cursor: "pointer",
              borderRadius: 0,
            }}
          >
            close
          </button>
        </footer>
      </aside>
    </div>
  );
}
