"use client";

/**
 * WS5 S4 — "Ask the worm" panel.
 *
 * Removes the "I have to set up Slack to evaluate" friction for first-time
 * visitors. Renders a textarea + "Ask" button on /dashboard. On submit,
 * POSTs to /api/ask, awaits the response, and displays it inline.
 *
 * Today the response is an honest stub — the worm-core /api/v1/ask
 * handler isn't wired yet. The panel therefore explains the wiring
 * state rather than pretending to answer. When the upstream handler
 * lands, this UI stays the same; only /api/ask switches from stub to
 * pass-through.
 */
import { useCallback, useState } from "react";

import type { AskResponseBody } from "../../app/api/ask/route";

export function AskTheWormPanel() {
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<AskResponseBody | null>(null);

  const onSubmit = useCallback(
    async (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      const trimmed = question.trim();
      if (!trimmed) {
        setError("Type a question first.");
        return;
      }
      setError(null);
      setPending(true);
      try {
        const res = await fetch("/api/ask", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ question: trimmed }),
        });
        const json = (await res.json()) as AskResponseBody;
        setResponse(json);
      } catch (err) {
        setError(
          `Couldn't reach /api/ask — ${(err as Error).message ?? "network error"}.`,
        );
      } finally {
        setPending(false);
      }
    },
    [question],
  );

  return (
    <section
      data-testid="ask-the-worm-panel"
      style={panelStyle}
    >
      <header style={headerStyle}>
        <span className="wb-mono" style={eyebrowStyle}>
          ask the worm · evaluator path
        </span>
        <h2 style={titleStyle}>What do you want to know?</h2>
        <p style={bodyStyle}>
          Type a question — no chat platform required. Once Slack / Discord
          / Teams is wired, the worm answers in-channel with ledger evidence.
        </p>
      </header>
      <form onSubmit={onSubmit} style={formStyle}>
        <label htmlFor="ask-the-worm-input" style={visuallyHidden}>
          Question for the worm
        </label>
        <textarea
          id="ask-the-worm-input"
          data-testid="ask-the-worm-input"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. What's our Q3 net revenue and how was it computed?"
          rows={3}
          style={textareaStyle}
        />
        <div style={actionsRowStyle}>
          <button
            type="submit"
            data-testid="ask-the-worm-submit"
            disabled={pending}
            style={{ ...submitButtonStyle, opacity: pending ? 0.5 : 1 }}
          >
            {pending ? "asking…" : "ask →"}
          </button>
          {error ? (
            <span
              data-testid="ask-the-worm-error"
              className="wb-mono"
              style={errorStyle}
            >
              {error}
            </span>
          ) : null}
        </div>
      </form>
      {response ? (
        <article
          data-testid="ask-the-worm-response"
          data-passthrough={response.passthrough ? "true" : "false"}
          style={responseStyle}
        >
          <span className="wb-mono" style={responseEyebrowStyle}>
            {response.passthrough ? "answer" : "wiring note"}
          </span>
          <p style={responseBodyStyle}>{response.answer}</p>
          {response.references.length > 0 ? (
            <ul style={refListStyle}>
              {response.references.map((r, i) => (
                <li key={i} className="wb-mono" style={refItemStyle}>
                  {r.kind} · {r.ref}
                </li>
              ))}
            </ul>
          ) : null}
        </article>
      ) : null}
    </section>
  );
}

const panelStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 14,
  padding: 20,
  border: "1px solid var(--wb-color-paper-edge)",
  background: "var(--wb-color-paper)",
};

const headerStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
};

const eyebrowStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const titleStyle: React.CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 22,
  fontWeight: 500,
  letterSpacing: "-0.005em",
  color: "var(--wb-color-aged-ink)",
};

const bodyStyle: React.CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontStyle: "italic",
  fontSize: 14,
  lineHeight: 1.55,
  color: "var(--wb-color-hash-gray)",
  maxWidth: 640,
};

const formStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 10,
};

const textareaStyle: React.CSSProperties = {
  width: "100%",
  minHeight: 72,
  padding: 12,
  border: "1px solid var(--wb-color-paper-edge)",
  background: "var(--wb-color-paper-deep)",
  fontFamily: "var(--wb-font-serif)",
  fontSize: 14,
  color: "var(--wb-color-aged-ink)",
  borderRadius: 0,
  resize: "vertical",
  boxSizing: "border-box",
};

const actionsRowStyle: React.CSSProperties = {
  display: "flex",
  gap: 12,
  alignItems: "baseline",
};

const submitButtonStyle: React.CSSProperties = {
  display: "inline-block",
  padding: "8px 14px",
  borderRadius: 0,
  border: "1px solid var(--wb-color-botanical-green-deep)",
  background: "var(--wb-color-botanical-green)",
  color: "var(--wb-color-paper)",
  fontFamily: "var(--wb-font-serif)",
  fontSize: 13,
  cursor: "pointer",
};

const errorStyle: React.CSSProperties = {
  fontSize: 11,
  color: "var(--wb-color-hash-gray)",
};

const responseStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
  padding: "14px 16px",
  border: "1px dashed var(--wb-color-aged-ink)",
  background: "var(--wb-color-paper-deep)",
};

const responseEyebrowStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const responseBodyStyle: React.CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 14,
  lineHeight: 1.55,
  color: "var(--wb-color-aged-ink)",
};

const refListStyle: React.CSSProperties = {
  margin: 0,
  padding: 0,
  listStyle: "none",
  display: "flex",
  flexDirection: "column",
  gap: 4,
};

const refItemStyle: React.CSSProperties = {
  fontSize: 11,
  color: "var(--wb-color-hash-gray)",
};

const visuallyHidden: React.CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0,0,0,0)",
  whiteSpace: "nowrap",
  border: 0,
};
