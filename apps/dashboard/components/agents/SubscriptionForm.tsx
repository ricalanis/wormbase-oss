/**
 * SubscriptionForm — admin form for creating agent subscriptions
 * (v2.A Task 7; v1.4 #5 — dynamic kinds list).
 *
 * Fields:
 *
 *   * `kinds` — multi-select checkboxes against the
 *     subscription-eligible subset of ``KIND_REGISTRY``. The list is
 *     fetched at page-load time from the worm-core endpoint
 *     ``GET /api/v1/read/subscription_eligible_kinds`` so adding a
 *     new event kind in the ledger surfaces it in the form without
 *     a dashboard code change. Falls back to a small canonical list
 *     when the endpoint is unreachable.
 *
 *   * `domains` — multi-select against the active domain set passed
 *     from the page.
 *
 *   * `agent_id_ref` — text input, optional, pre-filled with the
 *     current agentId so the most common case ("notify me about
 *     events involving MY queries") is a single click.
 *
 *   * `payload_path_eq` — repeating key/value pairs. The user adds
 *     rows on demand; the form sends only non-empty pairs.
 *
 *   * `transport` — radio: mcp_stream (default) or webhook. Selecting
 *     webhook reveals the URL + secret_ref inputs.
 *
 *   * `description` — optional free text.
 *
 * Validation: the form requires at least one filter axis to be non-
 * empty (matches the server action's check). Submit is disabled when
 * the validation would reject.
 *
 * Production contract: NO direct ledger write — the form submits via
 * the injected `createAction` server action which forwards to worm-core.
 */
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import type {
  CreateSubscriptionFormData,
  CreateSubscriptionResult,
  SubscriptionTransport,
} from "../../app/(app)/people/agents/[id]/subscriptions/actions";
import type { DomainRow } from "../../lib/ledger-client.types";

type Action = (
  agentId: string,
  formData: CreateSubscriptionFormData,
) => Promise<CreateSubscriptionResult>;

/**
 * One row in the dynamic kinds list. Mirrors the worm-core HTTP
 * endpoint's response shape (``description`` + ``family`` accompany
 * the bare kind string for rendering).
 */
export interface SubscriptionEligibleKind {
  kind: string;
  label: string;
  description: string;
  family: string;
}

export interface SubscriptionFormProps {
  agentId: string;
  domains: DomainRow[];
  /** Server action injected by the page. Tests pass a stub. */
  createAction: Action;
  /**
   * Kinds the form surfaces as checkboxes. Provided by the page
   * server-side (via the v1.4 #5 endpoint) so the list reflects the
   * current ``KIND_REGISTRY``. When empty, the form falls back to a
   * minimal canonical list — so a worm-core fetch failure still
   * renders a usable form.
   */
  availableKinds?: SubscriptionEligibleKind[];
}

/**
 * Fallback when the worm-core endpoint is unreachable. Same canon
 * as v2.A Batch C, less aspirational kinds (``source_disconnected``
 * and ``template_promoted`` aren't yet in KIND_REGISTRY at the time
 * of writing).
 */
const FALLBACK_KINDS: SubscriptionEligibleKind[] = [
  {
    kind: "bad_pattern_proposed",
    label: "bad pattern proposed",
    description: "Pattern that consistently produces low-quality outcomes.",
    family: "research_loop",
  },
  {
    kind: "semantic_gap_escalated",
    label: "semantic gap escalated",
    description: "Query intent the worm couldn't satisfy.",
    family: "research_loop",
  },
  {
    kind: "data_product_recommended",
    label: "data product recommended",
    description: "The worm recommends a new data product.",
    family: "data_products",
  },
  {
    kind: "source_connected",
    label: "source connected",
    description: "A new data source finished connecting.",
    family: "data_sources",
  },
  {
    kind: "data_product_consumed",
    label: "data product consumed",
    description: "An agent or human read a data product.",
    family: "data_products",
  },
  {
    kind: "query_outcome_recorded",
    label: "query outcome recorded",
    description: "An agent recorded the outcome of a query.",
    family: "research_loop",
  },
  {
    kind: "query_template_promoted",
    label: "query template promoted",
    description: "A query pattern has been promoted to a durable template.",
    family: "research_loop",
  },
];

const LABEL_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
  fontSize: 13,
};

const INPUT_STYLE: React.CSSProperties = {
  padding: "6px 8px",
  border: "1px solid var(--wb-color-aged-ink, #4b3f2f)",
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 13,
  background: "var(--wb-color-paper, #f6f1e7)",
};

const FIELDSET_STYLE: React.CSSProperties = {
  ...LABEL_STYLE,
  border: "1px solid var(--wb-color-edge, rgba(0,0,0,0.12))",
  padding: "10px 12px",
};

const LEGEND_STYLE: React.CSSProperties = {
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
  fontSize: 13,
  padding: "0 6px",
};

const BUTTON_PRIMARY: React.CSSProperties = {
  padding: "8px 16px",
  borderRadius: 0,
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
  fontSize: 13,
  border: "1px solid var(--wb-color-botanical-green-deep, #2a5b3f)",
  background: "var(--wb-color-botanical-green, #3c7a55)",
  color: "var(--wb-color-paper, #f6f1e7)",
  cursor: "pointer",
};

const BUTTON_GHOST: React.CSSProperties = {
  padding: "8px 16px",
  borderRadius: 0,
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
  fontSize: 13,
  border: "1px solid var(--wb-color-aged-ink, #4b3f2f)",
  background: "transparent",
  color: "var(--wb-color-aged-ink, #4b3f2f)",
  cursor: "pointer",
  textDecoration: "none",
  display: "inline-block",
};

const BUTTON_SMALL: React.CSSProperties = {
  padding: "4px 8px",
  borderRadius: 0,
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 11,
  border: "1px solid var(--wb-color-aged-ink, #4b3f2f)",
  background: "transparent",
  color: "var(--wb-color-aged-ink, #4b3f2f)",
  cursor: "pointer",
};

interface FormState {
  kinds: Set<string>;
  domains: Set<string>;
  agentIdRef: string;
  payloadPathEq: { path: string; value: string }[];
  transport: SubscriptionTransport;
  webhookUrl: string;
  webhookSecretRef: string;
  description: string;
}

export function SubscriptionForm({
  agentId,
  domains,
  createAction,
  availableKinds,
}: SubscriptionFormProps): JSX.Element {
  const kinds: SubscriptionEligibleKind[] =
    availableKinds && availableKinds.length > 0 ? availableKinds : FALLBACK_KINDS;
  const router = useRouter();
  const [form, setForm] = useState<FormState>({
    kinds: new Set<string>(),
    domains: new Set<string>(),
    agentIdRef: agentId,
    payloadPathEq: [],
    transport: "mcp_stream",
    webhookUrl: "",
    webhookSecretRef: "",
    description: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function toggleKind(kind: string): void {
    setForm((f) => {
      const next = new Set(f.kinds);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return { ...f, kinds: next };
    });
  }

  function toggleDomain(domainId: string): void {
    setForm((f) => {
      const next = new Set(f.domains);
      if (next.has(domainId)) next.delete(domainId);
      else next.add(domainId);
      return { ...f, domains: next };
    });
  }

  function addPayloadPair(): void {
    setForm((f) => ({
      ...f,
      payloadPathEq: [...f.payloadPathEq, { path: "", value: "" }],
    }));
  }

  function updatePayloadPair(
    index: number,
    side: "path" | "value",
    value: string,
  ): void {
    setForm((f) => ({
      ...f,
      payloadPathEq: f.payloadPathEq.map((row, i) =>
        i === index ? { ...row, [side]: value } : row,
      ),
    }));
  }

  function removePayloadPair(index: number): void {
    setForm((f) => ({
      ...f,
      payloadPathEq: f.payloadPathEq.filter((_, i) => i !== index),
    }));
  }

  const hasAxis =
    form.kinds.size > 0 ||
    form.domains.size > 0 ||
    form.agentIdRef.trim().length > 0 ||
    form.payloadPathEq.some(
      (r) => r.path.trim().length > 0 && r.value.trim().length > 0,
    );

  function submit(): void {
    setError(null);
    startTransition(async () => {
      const result = await createAction(agentId, {
        kinds: Array.from(form.kinds),
        domains: Array.from(form.domains),
        agentIdRef: form.agentIdRef.trim() || undefined,
        payloadPathEq: form.payloadPathEq
          .filter(
            (r) => r.path.trim().length > 0 && r.value.trim().length > 0,
          )
          .map((r) => [r.path.trim(), r.value.trim()] as [string, string]),
        transport: form.transport,
        webhookUrl: form.webhookUrl.trim() || undefined,
        webhookSecretRef: form.webhookSecretRef.trim() || undefined,
        description: form.description.trim() || undefined,
      });
      if (result.ok) {
        router.push(
          `/people/agents/${encodeURIComponent(agentId)}/subscriptions`,
        );
        router.refresh();
      } else {
        setError(result.error ?? "unknown error");
      }
    });
  }

  return (
    <form
      data-testid="subscription-form"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        maxWidth: 720,
      }}
    >
      {/* Kinds checkboxes — grouped by family for scannability. */}
      <fieldset data-testid="subscription-kinds" style={FIELDSET_STYLE}>
        <legend style={LEGEND_STYLE}>Event kinds</legend>
        <p
          style={{
            margin: "0 0 8px 0",
            fontStyle: "italic",
            fontSize: 12,
            color: "var(--wb-color-hash-gray, #6b6256)",
          }}
        >
          Pick the ledger entry kinds the agent should be notified about.
          Leave empty to match all kinds (combine with a domain or
          agent_id_ref to keep the filter scoped).{" "}
          <span data-testid="subscription-kinds-count">
            {kinds.length} eligible kind{kinds.length === 1 ? "" : "s"}
          </span>
          .
        </p>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
            gap: 6,
          }}
        >
          {kinds.map((row) => (
            <label
              key={row.kind}
              title={row.description}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 8,
                fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                fontSize: 12,
                padding: "4px 6px",
                border:
                  "1px solid var(--wb-color-edge, rgba(0,0,0,0.06))",
              }}
            >
              <input
                type="checkbox"
                data-testid={`subscription-kind-${row.kind}`}
                checked={form.kinds.has(row.kind)}
                onChange={() => toggleKind(row.kind)}
                style={{ marginTop: 2 }}
              />
              <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <span style={{ fontWeight: 500 }}>{row.kind}</span>
                <span
                  style={{
                    fontFamily: "var(--wb-font-serif, Georgia, serif)",
                    fontSize: 11,
                    fontStyle: "italic",
                    color: "var(--wb-color-hash-gray, #6b6256)",
                    lineHeight: 1.3,
                  }}
                >
                  {row.description}
                </span>
                <span
                  data-testid={`subscription-kind-family-${row.kind}`}
                  className="wb-mono"
                  style={{
                    fontSize: 9,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    color: "var(--wb-color-hash-gray, #6b6256)",
                  }}
                >
                  {row.family}
                </span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      {/* Domains checkboxes */}
      <fieldset data-testid="subscription-domains" style={FIELDSET_STYLE}>
        <legend style={LEGEND_STYLE}>Domains</legend>
        {domains.length === 0 ? (
          <p
            data-testid="subscription-domains-empty"
            style={{
              margin: 0,
              fontStyle: "italic",
              fontSize: 12,
              color: "var(--wb-color-hash-gray, #6b6256)",
            }}
          >
            No domains yet — add one via Tier 2 onboarding first, or leave
            this section empty.
          </p>
        ) : (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 4,
              marginTop: 6,
            }}
          >
            {domains.map((d) => (
              <label
                key={d.domainId}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontFamily: "var(--wb-font-serif, Georgia, serif)",
                  fontSize: 13,
                }}
              >
                <input
                  type="checkbox"
                  data-testid={`subscription-domain-${d.domainId}`}
                  checked={form.domains.has(d.domainId)}
                  onChange={() => toggleDomain(d.domainId)}
                />
                <span>{d.name}</span>
              </label>
            ))}
          </div>
        )}
      </fieldset>

      {/* agent_id_ref */}
      <label style={LABEL_STYLE}>
        agent_id_ref (optional)
        <input
          type="text"
          data-testid="subscription-agent-id-ref"
          value={form.agentIdRef}
          onChange={(e) =>
            setForm((f) => ({ ...f, agentIdRef: e.target.value }))
          }
          style={INPUT_STYLE}
          placeholder={agentId}
        />
        <span
          style={{
            fontFamily: "var(--wb-font-serif, Georgia, serif)",
            fontStyle: "italic",
            fontSize: 11,
            color: "var(--wb-color-hash-gray, #6b6256)",
          }}
        >
          Match entries whose <code>args.agent_id</code> equals this value.
          Defaults to this agent ({agentId.slice(0, 12)}…) so the most
          common case is one click.
        </span>
      </label>

      {/* payload_path_eq */}
      <fieldset data-testid="subscription-payload-pairs" style={FIELDSET_STYLE}>
        <legend style={LEGEND_STYLE}>Payload path matches (optional)</legend>
        <p
          style={{
            margin: "0 0 8px 0",
            fontStyle: "italic",
            fontSize: 12,
            color: "var(--wb-color-hash-gray, #6b6256)",
          }}
        >
          Match entries whose payload at <code>dotted.path</code> equals the
          given value. Example: <code>args.canonical_intent</code> ={" "}
          <code>weekly revenue</code>.
        </p>
        {form.payloadPathEq.map((row, index) => (
          <div
            key={index}
            data-testid={`subscription-payload-row-${index}`}
            style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}
          >
            <input
              type="text"
              placeholder="dotted.path"
              data-testid={`subscription-payload-path-${index}`}
              value={row.path}
              onChange={(e) =>
                updatePayloadPair(index, "path", e.target.value)
              }
              style={{ ...INPUT_STYLE, flex: 1 }}
            />
            <span aria-hidden style={{ opacity: 0.6 }}>=</span>
            <input
              type="text"
              placeholder="value"
              data-testid={`subscription-payload-value-${index}`}
              value={row.value}
              onChange={(e) =>
                updatePayloadPair(index, "value", e.target.value)
              }
              style={{ ...INPUT_STYLE, flex: 1 }}
            />
            <button
              type="button"
              data-testid={`subscription-payload-remove-${index}`}
              onClick={() => removePayloadPair(index)}
              style={BUTTON_SMALL}
            >
              remove
            </button>
          </div>
        ))}
        <button
          type="button"
          data-testid="subscription-payload-add"
          onClick={addPayloadPair}
          style={BUTTON_SMALL}
        >
          + add path/value pair
        </button>
      </fieldset>

      {/* Transport radio */}
      <fieldset data-testid="subscription-transport" style={FIELDSET_STYLE}>
        <legend style={LEGEND_STYLE}>Transport</legend>
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontFamily: "var(--wb-font-serif, Georgia, serif)",
            fontSize: 13,
            marginBottom: 4,
          }}
        >
          <input
            type="radio"
            data-testid="subscription-transport-mcp_stream"
            name="transport"
            value="mcp_stream"
            checked={form.transport === "mcp_stream"}
            onChange={() =>
              setForm((f) => ({ ...f, transport: "mcp_stream" }))
            }
          />
          <span>mcp_stream (long-poll SSE via MCP)</span>
        </label>
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontFamily: "var(--wb-font-serif, Georgia, serif)",
            fontSize: 13,
          }}
        >
          <input
            type="radio"
            data-testid="subscription-transport-webhook"
            name="transport"
            value="webhook"
            checked={form.transport === "webhook"}
            onChange={() => setForm((f) => ({ ...f, transport: "webhook" }))}
          />
          <span>webhook (POST with HMAC-SHA256)</span>
        </label>

        {form.transport === "webhook" ? (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 8,
              marginTop: 8,
              paddingTop: 8,
              borderTop: "1px dotted var(--wb-color-edge, rgba(0,0,0,0.12))",
            }}
          >
            <label style={LABEL_STYLE}>
              webhook_url
              <input
                type="url"
                data-testid="subscription-webhook-url"
                value={form.webhookUrl}
                onChange={(e) =>
                  setForm((f) => ({ ...f, webhookUrl: e.target.value }))
                }
                style={INPUT_STYLE}
                placeholder="https://your-agent.example.com/webhooks/wormbase"
              />
            </label>
            <label style={LABEL_STYLE}>
              webhook_secret_ref
              <input
                type="text"
                data-testid="subscription-webhook-secret-ref"
                value={form.webhookSecretRef}
                onChange={(e) =>
                  setForm((f) => ({ ...f, webhookSecretRef: e.target.value }))
                }
                style={INPUT_STYLE}
                placeholder="env://WORMBASE_WEBHOOK_SECRET or vault://..."
              />
              <span
                style={{
                  fontFamily: "var(--wb-font-serif, Georgia, serif)",
                  fontStyle: "italic",
                  fontSize: 11,
                  color: "var(--wb-color-hash-gray, #6b6256)",
                }}
              >
                Reference (never the raw secret) — the CredentialBroker
                resolves this at delivery time.
              </span>
            </label>
          </div>
        ) : null}
      </fieldset>

      {/* Description */}
      <label style={LABEL_STYLE}>
        Description (optional)
        <input
          type="text"
          data-testid="subscription-description"
          value={form.description}
          onChange={(e) =>
            setForm((f) => ({ ...f, description: e.target.value }))
          }
          style={INPUT_STYLE}
          placeholder="e.g. revenue-bot — alerts on bad_pattern_proposed"
        />
      </label>

      {!hasAxis ? (
        <p
          data-testid="subscription-validation-warning"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif, Georgia, serif)",
            fontStyle: "italic",
            fontSize: 12,
            color: "var(--wb-color-hash-gray, #6b6256)",
          }}
        >
          Pick at least one filter axis — kinds, domains, agent_id_ref,
          or a payload path/value pair. A wildcard subscription would
          match every ledger entry.
        </p>
      ) : null}

      {error ? (
        <p
          data-testid="subscription-form-error"
          role="alert"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif, Georgia, serif)",
            fontSize: 12,
            color: "var(--wb-color-error, #b03a2e)",
            background: "var(--wb-color-error-bg, rgba(176,58,46,0.08))",
            padding: "8px 10px",
            border: "1px solid var(--wb-color-error, #b03a2e)",
          }}
        >
          {error}
        </p>
      ) : null}

      <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
        <button
          type="submit"
          data-testid="subscription-submit"
          disabled={pending || !hasAxis}
          style={{
            ...BUTTON_PRIMARY,
            opacity: pending || !hasAxis ? 0.6 : 1,
            cursor: pending || !hasAxis ? "default" : "pointer",
          }}
        >
          {pending ? "Creating…" : "Create subscription"}
        </button>
        <Link
          href={`/people/agents/${encodeURIComponent(agentId)}/subscriptions`}
          data-testid="subscription-cancel"
          style={BUTTON_GHOST}
        >
          Cancel
        </Link>
      </div>
    </form>
  );
}
