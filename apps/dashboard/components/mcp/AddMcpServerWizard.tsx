"use client";
/**
 * AddMcpServerWizard — W2.A9.
 *
 * Inbound MCP preset registration wizard. The worm consumes external
 * MCP servers (Notion, Atlassian, GitHub, Linear, …) by registering a
 * preset under ``packages/connectors/.../mcp_presets`` — each preset
 * is an ``MCPConnector`` subclass with a fixed kind + server URL +
 * required-secrets list. The runtime presets are in code; this wizard
 * captures the operator's intent in the ledger.
 *
 * Flow:
 *   1. Operator picks a preset from the curated list (Notion, etc.) or
 *      "custom".
 *   2. Operator confirms the server URL + classification + description.
 *   3. We POST /api/v1/mcp/presets with {kind, serverUrl, ...}.
 *   4. The dashboard route resolves the current admin via
 *      getCurrentPerson and proxies to worm-core, which writes a
 *      ``source_proposed`` ledger entry with ``source_kind=mcp:<kind>``.
 *   5. The proposal surfaces in /sources alongside native sources and
 *      can be confirmed / connected through the existing flow.
 *
 * The wizard does NOT mutate the in-process connector registry — those
 * presets self-register at import. The ledger entry is the durable
 * record of the operator's intent, multi-tenant safe.
 */

import { useCallback, useMemo, useState } from "react";

interface PresetOption {
  kind: string;
  label: string;
  defaultUrl: string;
  description: string;
}

const CURATED_PRESETS: PresetOption[] = [
  {
    kind: "notion",
    label: "Notion",
    defaultUrl: "https://mcp.notion.com/mcp",
    description:
      "Pages, databases, comments — Notion's official MCP endpoint.",
  },
  {
    kind: "atlassian",
    label: "Atlassian (Jira / Confluence)",
    defaultUrl: "https://mcp.atlassian.com/v1/sse",
    description:
      "Jira issues, Confluence pages — Atlassian Cloud's MCP server.",
  },
  {
    kind: "github",
    label: "GitHub",
    defaultUrl: "https://api.githubcopilot.com/mcp",
    description: "Repos, issues, PRs — GitHub's MCP server.",
  },
  {
    kind: "linear",
    label: "Linear",
    defaultUrl: "https://mcp.linear.app/sse",
    description: "Issues, projects, cycles — Linear's MCP server.",
  },
  {
    kind: "custom",
    label: "Custom MCP server",
    defaultUrl: "",
    description: "Any streamable-HTTP MCP endpoint with a bearer-token auth.",
  },
];

const CLASSIFICATIONS = [
  "public",
  "internal",
  "confidential",
  "pii",
  "regulated",
] as const;
type Classification = (typeof CLASSIFICATIONS)[number];

type Status = "idle" | "submitting" | "ok" | "error";

export interface AddMcpServerWizardProps {
  /** Optional callback fired after a successful registration. */
  onRegistered?: (sourceId: string, sourceKind: string) => void;
}

export function AddMcpServerWizard({ onRegistered }: AddMcpServerWizardProps) {
  const [open, setOpen] = useState(false);
  const [presetIdx, setPresetIdx] = useState(0);
  const [customKind, setCustomKind] = useState("");
  const [serverUrl, setServerUrl] = useState(CURATED_PRESETS[0].defaultUrl);
  const [description, setDescription] = useState(
    CURATED_PRESETS[0].description,
  );
  const [domain, setDomain] = useState("general");
  const [classification, setClassification] = useState<Classification>(
    "internal",
  );
  const [status, setStatus] = useState<Status>("idle");
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [registered, setRegistered] = useState<{
    sourceId: string;
    sourceKind: string;
  } | null>(null);

  const preset = CURATED_PRESETS[presetIdx];
  const isCustom = preset.kind === "custom";
  const effectiveKind = isCustom ? customKind.trim() : preset.kind;

  const canSubmit = useMemo(() => {
    if (status === "submitting") return false;
    if (!serverUrl.trim()) return false;
    if (isCustom && !customKind.trim()) return false;
    return true;
  }, [status, serverUrl, isCustom, customKind]);

  const handlePickPreset = useCallback((idx: number) => {
    setPresetIdx(idx);
    const next = CURATED_PRESETS[idx];
    setServerUrl(next.defaultUrl);
    setDescription(next.description);
    setRegistered(null);
    setStatus("idle");
    setErrMsg(null);
  }, []);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setStatus("submitting");
      setErrMsg(null);
      try {
        const res = await fetch("/api/v1/mcp/presets", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            kind: effectiveKind,
            serverUrl: serverUrl.trim(),
            description,
            suggestedDomain: domain,
            suggestedClassification: classification,
          }),
        });
        const text = await res.text();
        if (!res.ok) {
          setStatus("error");
          setErrMsg(text.slice(0, 240) || `HTTP ${res.status}`);
          return;
        }
        const json = JSON.parse(text) as {
          source_id: string;
          source_kind: string;
        };
        setStatus("ok");
        setRegistered({
          sourceId: json.source_id,
          sourceKind: json.source_kind,
        });
        onRegistered?.(json.source_id, json.source_kind);
      } catch (err) {
        setStatus("error");
        setErrMsg((err as Error).message);
      }
    },
    [effectiveKind, serverUrl, description, domain, classification, onRegistered],
  );

  if (!open) {
    return (
      <button
        type="button"
        data-testid="add-mcp-server-cta"
        onClick={() => setOpen(true)}
        style={{
          fontFamily: "var(--wb-font-mono)",
          fontSize: 12,
          padding: "8px 14px",
          border: "1px solid var(--wb-color-aged-ink)",
          background: "var(--wb-color-paper)",
          color: "var(--wb-color-aged-ink)",
          cursor: "pointer",
          alignSelf: "flex-start",
        }}
      >
        + Add MCP server
      </button>
    );
  }

  return (
    <section
      data-testid="add-mcp-server-wizard"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        border: "1px solid var(--wb-color-aged-ink)",
        padding: "16px 20px",
      }}
    >
      <header
        style={{
          display: "flex",
          flexDirection: "row",
          justifyContent: "space-between",
          alignItems: "flex-start",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.16em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            Inbound · MCP
          </span>
          <h3
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 18,
              fontWeight: 500,
            }}
          >
            Add MCP server
          </h3>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
              fontSize: 13,
            }}
          >
            Register an external MCP server the worm can read from.
            Recorded as a <code>source_proposed</code> ledger entry —
            replayable, multi-tenant scoped, surfaces in /sources.
          </p>
        </div>
        <button
          type="button"
          data-testid="add-mcp-server-close"
          onClick={() => setOpen(false)}
          style={{
            fontFamily: "var(--wb-font-mono)",
            fontSize: 11,
            padding: "4px 10px",
            border: "1px solid var(--wb-color-rule-line)",
            background: "var(--wb-color-paper)",
            color: "var(--wb-color-hash-gray)",
            cursor: "pointer",
          }}
        >
          close
        </button>
      </header>

      <form
        onSubmit={handleSubmit}
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
      >
        <fieldset
          data-testid="preset-picker"
          style={{
            border: "1px solid var(--wb-color-rule-line)",
            padding: "10px 12px",
            display: "flex",
            flexWrap: "wrap",
            gap: 8,
          }}
        >
          <legend
            className="wb-mono"
            style={{
              padding: "0 6px",
              fontSize: 11,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            Preset
          </legend>
          {CURATED_PRESETS.map((p, idx) => {
            const selected = idx === presetIdx;
            return (
              <button
                key={p.kind}
                type="button"
                data-testid={`preset-${p.kind}`}
                onClick={() => handlePickPreset(idx)}
                style={{
                  fontFamily: "var(--wb-font-mono)",
                  fontSize: 11,
                  padding: "4px 10px",
                  border: selected
                    ? "1px solid var(--wb-color-aged-ink)"
                    : "1px solid var(--wb-color-rule-line)",
                  background: selected
                    ? "var(--wb-color-paper-edge)"
                    : "var(--wb-color-paper)",
                  color: "var(--wb-color-aged-ink)",
                  cursor: "pointer",
                }}
              >
                {p.label}
              </button>
            );
          })}
        </fieldset>

        {isCustom ? (
          <Field
            label="Kind"
            hint="Lower-case slug for the source kind, e.g. ‘gworkspace’"
            input={
              <input
                data-testid="custom-kind-input"
                type="text"
                value={customKind}
                onChange={(e) => setCustomKind(e.target.value)}
                placeholder="gworkspace"
                required
                style={inputStyle}
              />
            }
          />
        ) : null}

        <Field
          label="Server URL"
          hint="Streamable-HTTP MCP endpoint."
          input={
            <input
              data-testid="server-url-input"
              type="url"
              value={serverUrl}
              onChange={(e) => setServerUrl(e.target.value)}
              required
              style={inputStyle}
            />
          }
        />

        <Field
          label="Description"
          hint="Editorial description rendered in the connector picker."
          input={
            <input
              data-testid="description-input"
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              style={inputStyle}
            />
          }
        />

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Field
            label="Domain"
            hint="Functional area this preset serves."
            input={
              <input
                data-testid="domain-input"
                type="text"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                style={inputStyle}
              />
            }
          />
          <Field
            label="Classification"
            hint="Default classification for proposed resources."
            input={
              <select
                data-testid="classification-select"
                value={classification}
                onChange={(e) =>
                  setClassification(e.target.value as Classification)
                }
                style={inputStyle}
              >
                {CLASSIFICATIONS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            }
          />
        </div>

        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button
            type="submit"
            data-testid="add-mcp-server-submit"
            disabled={!canSubmit}
            style={{
              fontFamily: "var(--wb-font-mono)",
              fontSize: 12,
              padding: "8px 14px",
              border: "1px solid var(--wb-color-aged-ink)",
              background: canSubmit
                ? "var(--wb-color-paper)"
                : "var(--wb-color-paper-edge)",
              color: "var(--wb-color-aged-ink)",
              cursor: canSubmit ? "pointer" : "default",
              opacity: canSubmit ? 1 : 0.6,
            }}
          >
            {status === "submitting"
              ? "registering…"
              : status === "ok"
                ? "register another"
                : "register preset"}
          </button>
          {registered ? (
            <span
              data-testid="add-mcp-server-success"
              className="wb-mono"
              style={{
                fontSize: 11,
                color: "var(--wb-color-botanical-green)",
              }}
            >
              registered · {registered.sourceKind} · source{" "}
              {registered.sourceId.slice(0, 8)}…
            </span>
          ) : null}
        </div>

        {status === "error" && errMsg ? (
          <p
            data-testid="add-mcp-server-error"
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-mono)",
              fontSize: 12,
              color: "var(--wb-color-aged-ink)",
              background: "var(--wb-color-paper-edge)",
              padding: "8px 12px",
              border: "1px solid var(--wb-color-rule-line)",
            }}
          >
            {errMsg}
          </p>
        ) : null}
      </form>
    </section>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "6px 8px",
  border: "1px solid var(--wb-color-rule-line)",
  fontFamily: "var(--wb-font-mono)",
  fontSize: 13,
  background: "var(--wb-color-paper)",
  color: "var(--wb-color-aged-ink)",
};

function Field({
  label,
  hint,
  input,
}: {
  label: string;
  hint: string;
  input: React.ReactNode;
}) {
  return (
    <label
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        fontFamily: "var(--wb-font-serif)",
        fontSize: 13,
      }}
    >
      <span>
        {label}
        <span
          style={{
            marginLeft: 6,
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 12,
          }}
        >
          {hint}
        </span>
      </span>
      {input}
    </label>
  );
}
