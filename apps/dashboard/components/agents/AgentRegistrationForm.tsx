/**
 * AgentRegistrationForm — admin form for `/people/agents/new` (Wave 3.2 Hole #1).
 *
 * Fields:
 *   * `external_provider` — select of {claude, openai, kimi, internal_worm, other}
 *   * `display_name` — free text, required, max 80 chars
 *   * `domain_read_ids` — multi-select of existing domains; at least one
 *     domain.read OR a model.access budget should be provided to make a
 *     usable agent (admin can re-grant later, so we don't hard-require)
 *   * `model_access_budget_usd` — optional decimal-as-string for the
 *     initial model.access grant
 *
 * Submission calls the injected ``registerAction`` server action. On
 * success (`{ok: true, agentId}`), the form navigates to
 * `/people/agents/[id]`. On failure, the error string from the action
 * surfaces inline; the form stays mounted so the admin can retry.
 *
 * Empty-state copy when no domains exist: a callout points to Tier 2
 * onboarding (`/onboarding/tier-2` is where the domain pack lands) —
 * the form still submits but with an empty `domain_read_ids` array.
 *
 * Production contract:
 *   * NO direct ledger write — submission routes through the server
 *     action which forwards to worm-core's HTTP write API.
 *   * Failure paths render the error inline; the form does NOT auto-
 *     reset on error so the admin's typed values survive a retry.
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import type {
  AgentExternalProvider,
  RegisterAgentFormData,
  RegisterAgentResult,
} from "../../app/(app)/people/agents/new/actions";
import type { DomainRow } from "../../lib/ledger-client.types";

type Action = (formData: RegisterAgentFormData) => Promise<RegisterAgentResult>;

export interface AgentRegistrationFormProps {
  domains: DomainRow[];
  /** Server action injected by the page. Tests pass a stub. */
  registerAction: Action;
}

const PROVIDER_OPTIONS: { value: AgentExternalProvider; label: string }[] = [
  { value: "claude", label: "Claude (Anthropic)" },
  { value: "openai", label: "OpenAI" },
  { value: "kimi", label: "Kimi (Moonshot)" },
  { value: "internal_worm", label: "Internal worm" },
  { value: "other", label: "Other" },
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

interface FormState {
  externalProvider: AgentExternalProvider;
  displayName: string;
  domainReadIds: string[];
  modelAccessBudgetUsd: string;
}

export function AgentRegistrationForm({
  domains,
  registerAction,
}: AgentRegistrationFormProps): JSX.Element {
  const router = useRouter();
  const [form, setForm] = useState<FormState>({
    externalProvider: "claude",
    displayName: "",
    domainReadIds: [],
    modelAccessBudgetUsd: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function toggleDomain(domainId: string): void {
    setForm((f) => {
      const has = f.domainReadIds.includes(domainId);
      return {
        ...f,
        domainReadIds: has
          ? f.domainReadIds.filter((d) => d !== domainId)
          : [...f.domainReadIds, domainId],
      };
    });
  }

  function submit(): void {
    setError(null);
    startTransition(async () => {
      const result = await registerAction({
        externalProvider: form.externalProvider,
        displayName: form.displayName.trim(),
        domainReadIds: form.domainReadIds,
        modelAccessBudgetUsd:
          form.modelAccessBudgetUsd.trim() || undefined,
      });
      if (result.ok && result.agentId) {
        router.push(`/people/agents/${result.agentId}`);
      } else {
        setError(result.error ?? "unknown error");
      }
    });
  }

  return (
    <form
      data-testid="agent-registration-form"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        maxWidth: 640,
      }}
    >
      <label style={LABEL_STYLE}>
        External provider
        <select
          data-testid="agent-external-provider"
          value={form.externalProvider}
          onChange={(e) =>
            setForm((f) => ({
              ...f,
              externalProvider: e.target.value as AgentExternalProvider,
            }))
          }
          style={INPUT_STYLE}
        >
          {PROVIDER_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>

      <label style={LABEL_STYLE}>
        Display name
        <input
          type="text"
          required
          maxLength={80}
          data-testid="agent-display-name"
          value={form.displayName}
          onChange={(e) =>
            setForm((f) => ({ ...f, displayName: e.target.value }))
          }
          style={INPUT_STYLE}
          placeholder="e.g. revenue-analyst-claude"
        />
        <span
          style={{
            fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
            fontSize: 10,
            color: "var(--wb-color-hash-gray, #6b6256)",
          }}
        >
          {form.displayName.length}/80
        </span>
      </label>

      <fieldset
        data-testid="agent-domain-grants"
        style={{
          ...LABEL_STYLE,
          border: "1px solid var(--wb-color-edge, rgba(0,0,0,0.12))",
          padding: "10px 12px",
        }}
      >
        <legend
          style={{
            fontFamily: "var(--wb-font-serif, Georgia, serif)",
            fontSize: 13,
            padding: "0 6px",
          }}
        >
          Domain read grants
        </legend>
        {domains.length === 0 ? (
          <p
            data-testid="agent-domains-empty"
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif, Georgia, serif)",
              fontStyle: "italic",
              fontSize: 12,
              color: "var(--wb-color-hash-gray, #6b6256)",
            }}
          >
            No domains yet — add one via Tier 2 onboarding first. You can
            still register the agent and add domain grants later via{" "}
            <code>/people/agents/[id]</code>.
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
                  data-testid={`agent-domain-${d.domainId}`}
                  checked={form.domainReadIds.includes(d.domainId)}
                  onChange={() => toggleDomain(d.domainId)}
                />
                <span>{d.name}</span>
                <span
                  className="wb-mono"
                  style={{
                    fontSize: 10,
                    color: "var(--wb-color-hash-gray, #6b6256)",
                  }}
                >
                  {d.domainId.slice(0, 8)}…
                </span>
              </label>
            ))}
          </div>
        )}
      </fieldset>

      <label style={LABEL_STYLE}>
        Model access budget (USD, optional)
        <input
          type="text"
          inputMode="decimal"
          pattern="^[0-9]*\.?[0-9]*$"
          data-testid="agent-budget"
          value={form.modelAccessBudgetUsd}
          onChange={(e) =>
            setForm((f) => ({ ...f, modelAccessBudgetUsd: e.target.value }))
          }
          style={INPUT_STYLE}
          placeholder="e.g. 25.00"
        />
        <span
          style={{
            fontFamily: "var(--wb-font-serif, Georgia, serif)",
            fontStyle: "italic",
            fontSize: 11,
            color: "var(--wb-color-hash-gray, #6b6256)",
          }}
        >
          Leave blank to register without a model.access grant. Budgets can
          be added later as a separate grant entry.
        </span>
      </label>

      {error ? (
        <p
          data-testid="agent-registration-error"
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
          data-testid="agent-register-submit"
          disabled={pending || form.displayName.trim().length === 0}
          style={{
            ...BUTTON_PRIMARY,
            opacity: pending || form.displayName.trim().length === 0 ? 0.6 : 1,
            cursor:
              pending || form.displayName.trim().length === 0
                ? "default"
                : "pointer",
          }}
        >
          {pending ? "Registering…" : "Register agent"}
        </button>
        <Link
          href="/people/agents"
          data-testid="agent-register-cancel"
          style={BUTTON_GHOST}
        >
          Cancel
        </Link>
      </div>
    </form>
  );
}
