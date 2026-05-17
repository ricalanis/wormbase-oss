"use client";
/**
 * VoicePanel — the slide-in panel underneath the AskTheWormFloater.
 *
 * Surfaces (top → bottom):
 *
 *   1. Header — "Ask the worm" + close (×).
 *   2. Mic / text input. On Chrome/Edge (Web Speech API standard), the
 *      mic button toggles live STT and a transcript previews live as
 *      the user speaks. On Firefox / unsupported browsers, the mic is
 *      disabled and the input renders as a textarea (graceful degrade).
 *   3. Submit button (`POST /api/v1/voice/ask`).
 *   4. Answer area — shows the worm's reply, the deterministic
 *      hash_receipt, and a ledger receipt link of the form
 *      `/trace?seq=<ledger_seq>` (sister A10's filter).
 *   5. Service-unavailable state when the proxy returns 503 — no
 *      fixture answer, just an honest banner with retry.
 *
 * Per W3.A12 quality bar: no fixture fallbacks; the answer is a real
 * upstream call; the hash_receipt comes from the voice-agent service.
 *
 * W7.A5 — Web Speech API graceful degradation. The Speech API has
 * origin/cert restrictions on some HTTPS tunnels (Cloudflare,
 * trycloudflare.com) and is entirely missing on Firefox. Whichever
 * failure fires, we render an honest user-visible explanation and keep
 * the textarea fully functional. The text input is the universal
 * fallback — never disabled by voice state.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export type VoiceStatus =
  | "idle"
  | "listening"
  | "submitting"
  | "answered"
  | "error";

/**
 * Why classify? Different speech-init failures call for different
 * user-visible copy. "Browser unsupported" (Firefox) is a clean
 * graceful-degrade message; "service-not-allowed" / "not-allowed" is
 * a tunnel/cert/permissions issue specific to the current origin and
 * the user can switch browsers or ask the host for HTTPS-direct;
 * "failed" is a generic catch-all (network, transient, unknown).
 */
export type VoiceInitMode = "ok" | "unsupported" | "not-allowed" | "failed";

export interface AskKPI {
  id: string;
  name: string;
  formula: string | null;
  unit: string | null;
  ownerPosition: string | null;
  status: string | null;
}

export interface AskAnswer {
  answer: string;
  hashReceipt: string | null;
  ledgerSeq: number | null;
  model: string | null;
  sessionId: string | null;
  /**
   * P13 — citation_kind is `"kpi_node"` when worm-core's MCP server
   * resolved a real KPI for the question; the trace link then points
   * at the KPI's most recent ``emit_kpi_node`` entry. Otherwise it
   * falls back to ``"chat_sent"`` (the answer's own ledger row).
   *
   * Optional so that callers / tests written before P13 still satisfy
   * the contract — the panel renders the chat_sent default when the
   * field is absent.
   */
  citationKind?: "kpi_node" | "chat_sent" | null;
  kpi?: AskKPI | null;
}

export interface VoicePanelProps {
  open: boolean;
  onClose: () => void;
  /**
   * Override the fetcher for tests. Defaults to a real
   * ``POST /api/v1/voice/ask`` against the dashboard proxy.
   */
  ask?: (transcript: string) => Promise<AskAnswer>;
  /**
   * Override the speech-recognition factory for tests. Defaults to
   * detecting `window.SpeechRecognition` / `window.webkitSpeechRecognition`.
   *
   * The factory may legitimately throw — some browsers raise a
   * `SecurityError` at construction time on disallowed origins. The
   * panel handles that and degrades to text-only.
   */
  speechRecognitionFactory?: () => SpeechRecognitionLike | null;
}

export interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start: () => void;
  stop: () => void;
  abort?: () => void;
  onresult: ((ev: SpeechRecognitionEventLike) => void) | null;
  onerror: ((ev: { error?: string }) => void) | null;
  onend: (() => void) | null;
}

interface SpeechRecognitionEventLike {
  results: ArrayLike<{
    isFinal: boolean;
    [index: number]: { transcript: string };
    length: number;
  }>;
  resultIndex: number;
}

function defaultSpeechRecognitionFactory(): SpeechRecognitionLike | null {
  if (typeof window === "undefined") return null;
  const SR =
    (window as unknown as { SpeechRecognition?: new () => SpeechRecognitionLike })
      .SpeechRecognition ??
    (
      window as unknown as {
        webkitSpeechRecognition?: new () => SpeechRecognitionLike;
      }
    ).webkitSpeechRecognition;
  if (!SR) return null;
  return new SR();
}

async function defaultAsk(transcript: string): Promise<AskAnswer> {
  const res = await fetch("/api/v1/voice/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ transcript }),
  });
  const text = await res.text();
  let parsed: Record<string, unknown> = {};
  try {
    parsed = text ? (JSON.parse(text) as Record<string, unknown>) : {};
  } catch {
    throw new Error(`voice-agent returned non-JSON: ${text.slice(0, 200)}`);
  }
  if (!res.ok) {
    const message =
      typeof parsed.message === "string"
        ? parsed.message
        : `voice-agent error (HTTP ${res.status})`;
    throw new Error(message);
  }
  const rawKpi = parsed.kpi as Record<string, unknown> | null | undefined;
  const kpi: AskKPI | null =
    rawKpi && typeof rawKpi === "object" && typeof rawKpi.id === "string"
      ? {
          id: rawKpi.id,
          name: typeof rawKpi.name === "string" ? rawKpi.name : rawKpi.id,
          formula:
            typeof rawKpi.formula === "string" ? rawKpi.formula : null,
          unit: typeof rawKpi.unit === "string" ? rawKpi.unit : null,
          ownerPosition:
            typeof rawKpi.owner_position === "string"
              ? rawKpi.owner_position
              : null,
          status:
            typeof rawKpi.status === "string" ? rawKpi.status : null,
        }
      : null;
  const rawCitationKind = parsed.citation_kind;
  const citationKind: "kpi_node" | "chat_sent" | null =
    rawCitationKind === "kpi_node" || rawCitationKind === "chat_sent"
      ? rawCitationKind
      : null;
  return {
    answer: typeof parsed.answer === "string" ? parsed.answer : "",
    hashReceipt:
      typeof parsed.hash_receipt === "string" ? parsed.hash_receipt : null,
    ledgerSeq:
      typeof parsed.ledger_seq === "number" ? parsed.ledger_seq : null,
    model: typeof parsed.model === "string" ? parsed.model : null,
    sessionId:
      typeof parsed.session_id === "string" ? parsed.session_id : null,
    citationKind,
    kpi,
  };
}

/**
 * Map a SpeechRecognition `error` event code to a `VoiceInitMode`.
 * The values come from the Web Speech API spec — `not-allowed`
 * (mic permission denied) and `service-not-allowed` (origin/cert
 * blocked the recognition service) are the two known HTTPS-tunnel
 * symptoms; everything else is bucketed as `failed` with the raw
 * error code surfaced in the message.
 */
function classifySpeechError(code: string | undefined): VoiceInitMode {
  if (code === "not-allowed" || code === "service-not-allowed") {
    return "not-allowed";
  }
  return "failed";
}

const INIT_MODE_COPY: Record<
  Exclude<VoiceInitMode, "ok">,
  { eyebrow: string; headline: string; body: string }
> = {
  unsupported: {
    eyebrow: "voice unavailable",
    headline: "Voice no disponible en este navegador",
    body:
      "Web Speech API isn't supported here (try Chrome or Edge). Type your question below — the rest of the panel works the same.",
  },
  "not-allowed": {
    eyebrow: "voice unavailable",
    headline: "Voice no disponible en este origen",
    body:
      "The browser blocked speech recognition for this URL — usually a tunnel/cert restriction or a denied microphone permission. Use the text field below.",
  },
  failed: {
    eyebrow: "voice failed",
    headline: "Speech recognition failed",
    body:
      "Couldn't start the speech engine. Use the text field below or hit retry.",
  },
};

export function VoicePanel({
  open,
  onClose,
  ask = defaultAsk,
  speechRecognitionFactory = defaultSpeechRecognitionFactory,
}: VoicePanelProps) {
  const [transcript, setTranscript] = useState("");
  const [interim, setInterim] = useState("");
  const [status, setStatus] = useState<VoiceStatus>("idle");
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  /**
   * Speech-init probe — runs synchronously per render of the factory
   * identity. We resolve it lazily once via a `useState` initializer,
   * then re-probe inside `useEffect` if the factory identity changes
   * (matters for tests that swap the factory between renders).
   *
   * The probe distinguishes three failure modes:
   *   - `unsupported` — factory returned null (no SpeechRecognition
   *     constructor on `window`, e.g. Firefox).
   *   - `not-allowed` — factory threw at construction (some browsers
   *     raise `SecurityError` on locked-down origins).
   *   - `failed` — set later by `start()` throws or `onerror` events.
   */
  const probeSpeechSupport = useCallback((): {
    mode: VoiceInitMode;
    detail: string | null;
  } => {
    try {
      const r = speechRecognitionFactory();
      if (r === null) return { mode: "unsupported", detail: null };
      // Best-effort cleanup of the probe instance — most native impls
      // tolerate `stop()` before `start()`, but ignore if they don't.
      try {
        r.stop();
      } catch {
        // best-effort
      }
      return { mode: "ok", detail: null };
    } catch (err) {
      return {
        mode: "not-allowed",
        detail: (err as Error).message ?? null,
      };
    }
  }, [speechRecognitionFactory]);

  const [initState, setInitState] = useState<{
    mode: VoiceInitMode;
    detail: string | null;
  }>(() => probeSpeechSupport());
  const initMode = initState.mode;
  const initDetail = initState.detail;
  const setInitMode = useCallback(
    (mode: VoiceInitMode, detail: string | null = null) => {
      setInitState({ mode, detail });
    },
    [],
  );

  // Re-probe when the factory identity changes (test swap).
  useEffect(() => {
    setInitState(probeSpeechSupport());
  }, [probeSpeechSupport]);

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  const speechSupported = initMode !== "unsupported" && initMode !== "not-allowed";

  // Reset on close so re-opening the panel starts fresh.
  useEffect(() => {
    if (!open) {
      stopListening();
      setTranscript("");
      setInterim("");
      setStatus("idle");
      setAnswer(null);
      setErrorMsg(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const stopListening = useCallback(() => {
    const r = recognitionRef.current;
    if (r) {
      try {
        r.stop();
      } catch {
        // best-effort
      }
    }
    recognitionRef.current = null;
  }, []);

  const startListening = useCallback(() => {
    if (!speechSupported) return;
    let r: SpeechRecognitionLike | null = null;
    try {
      r = speechRecognitionFactory();
    } catch (err) {
      // Same SecurityError class as in the support probe — the user
      // tried again after permissions changed, but they didn't.
      setInitMode("not-allowed", (err as Error).message ?? null);
      return;
    }
    if (!r) {
      setInitMode("unsupported");
      return;
    }
    r.continuous = true;
    r.interimResults = true;
    r.lang = "en-US";
    r.onresult = (ev) => {
      let finalText = "";
      let interimText = "";
      for (let i = ev.resultIndex; i < ev.results.length; i += 1) {
        const result = ev.results[i];
        const piece = result[0]?.transcript ?? "";
        if (result.isFinal) {
          finalText += piece;
        } else {
          interimText += piece;
        }
      }
      if (finalText) {
        setTranscript((prev) => (prev ? `${prev} ${finalText}` : finalText));
      }
      setInterim(interimText);
    };
    r.onerror = (ev) => {
      // Classify the error so the panel can render the right copy.
      // `not-allowed` / `service-not-allowed` → tunnel/cert/permission
      // bucket; everything else → generic failure with retry.
      const mode = classifySpeechError(ev.error);
      setInitMode(mode, ev.error ?? null);
      // Mirror into the legacy error banner so existing screen-readers
      // and tests still surface the failure.
      setStatus("error");
      setErrorMsg(
        ev.error
          ? `speech recognition: ${ev.error}`
          : "speech recognition failed",
      );
      recognitionRef.current = null;
    };
    r.onend = () => {
      setStatus((prev) => (prev === "listening" ? "idle" : prev));
      setInterim("");
      recognitionRef.current = null;
    };
    recognitionRef.current = r;
    setStatus("listening");
    setErrorMsg(null);
    try {
      r.start();
    } catch (err) {
      // Some browsers throw on start() when the previous session
      // hasn't fully torn down, or when the origin is blocked
      // post-construction. Treat as a generic init failure rather
      // than a permissions issue — the user can hit retry.
      setInitMode("failed", (err as Error).message ?? null);
      setStatus("error");
      setErrorMsg(
        (err as Error).message ?? "could not start speech recognition",
      );
      recognitionRef.current = null;
    }
  }, [speechRecognitionFactory, speechSupported, setInitMode]);

  const toggleMic = useCallback(() => {
    if (status === "listening") {
      stopListening();
      setStatus("idle");
    } else {
      startListening();
    }
  }, [status, startListening, stopListening]);

  const submit = useCallback(async () => {
    const text = (transcript + " " + interim).trim();
    if (!text) {
      setErrorMsg("please say or type a question first");
      return;
    }
    stopListening();
    setStatus("submitting");
    setErrorMsg(null);
    setAnswer(null);
    try {
      const result = await ask(text);
      setAnswer(result);
      setStatus("answered");
    } catch (err) {
      setStatus("error");
      setErrorMsg((err as Error).message ?? "ask failed");
    }
  }, [ask, interim, stopListening, transcript]);

  const retryVoice = useCallback(() => {
    // Reset the init state and let the user retry. The next mic-toggle
    // will re-probe via the factory.
    setInitMode("ok");
    setStatus("idle");
    setErrorMsg(null);
  }, [setInitMode]);

  const fullTranscript = useMemo(() => {
    return interim ? `${transcript} ${interim}`.trim() : transcript;
  }, [transcript, interim]);

  if (!open) return null;

  // Speech is only "live" when the init mode is ok AND the factory
  // returned a usable recognition object on probe. The mic button is
  // disabled in every other mode; the textarea is never disabled by
  // voice state.
  const speechLive = speechSupported && initMode === "ok";

  return (
    <aside
      data-testid="voice-panel"
      role="dialog"
      aria-label="Ask the worm"
      style={{
        position: "fixed",
        right: 24,
        bottom: 96,
        width: 380,
        maxHeight: "70vh",
        display: "flex",
        flexDirection: "column",
        gap: 12,
        background: "var(--wb-color-paper, #f5f1e8)",
        border: "1px solid var(--wb-color-aged-ink, #2a2a2a)",
        boxShadow: "0 12px 32px rgba(0, 0, 0, 0.16)",
        padding: "16px 18px",
        zIndex: 9999,
        overflowY: "auto",
      }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 8,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray, #6b6258)",
            }}
          >
            Voice · dashboard
          </span>
          <h3
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif, Georgia, serif)",
              fontSize: 18,
              fontWeight: 500,
            }}
          >
            Ask the worm
          </h3>
        </div>
        <button
          type="button"
          data-testid="voice-panel-close"
          onClick={onClose}
          aria-label="close voice panel"
          style={{
            background: "transparent",
            border: "none",
            fontFamily: "var(--wb-font-mono, monospace)",
            fontSize: 16,
            cursor: "pointer",
            color: "var(--wb-color-aged-ink, #2a2a2a)",
            lineHeight: 1,
            padding: 4,
          }}
        >
          ×
        </button>
      </header>

      {/* Voice-unavailable banner — sits above the mic+textarea so the
          user reads the explanation before reaching for the disabled
          mic. The textarea below remains fully functional, which is
          the whole point of graceful degradation. */}
      {initMode !== "ok" ? (
        <div
          data-testid="voice-init-fallback"
          data-mode={initMode}
          role="status"
          style={{
            padding: "10px 12px",
            border: "1px dashed var(--wb-color-sepia-warning, #b85a3e)",
            background: "var(--wb-color-paper-soft, #f7f3ea)",
            color: "var(--wb-color-aged-ink, #2a2a2a)",
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-sepia-warning-deep, #8a3a25)",
            }}
          >
            {INIT_MODE_COPY[initMode].eyebrow}
          </span>
          <strong
            style={{
              fontFamily: "var(--wb-font-serif, Georgia, serif)",
              fontSize: 14,
              fontWeight: 500,
            }}
          >
            {INIT_MODE_COPY[initMode].headline}
          </strong>
          <span
            style={{
              fontFamily: "var(--wb-font-serif, Georgia, serif)",
              fontStyle: "italic",
              fontSize: 13,
              lineHeight: 1.45,
              color: "var(--wb-color-hash-gray, #6b6258)",
            }}
          >
            {INIT_MODE_COPY[initMode].body}
          </span>
          {initDetail ? (
            <code
              data-testid="voice-init-detail"
              className="wb-mono"
              style={{
                fontSize: 11,
                color: "var(--wb-color-hash-gray, #6b6258)",
                wordBreak: "break-all",
              }}
            >
              {initDetail}
            </code>
          ) : null}
          {initMode === "failed" ? (
            <button
              type="button"
              data-testid="voice-init-retry"
              onClick={retryVoice}
              style={{
                alignSelf: "flex-start",
                fontFamily: "var(--wb-font-mono, monospace)",
                fontSize: 11,
                padding: "4px 10px",
                border: "1px solid var(--wb-color-aged-ink, #2a2a2a)",
                background: "var(--wb-color-paper, #f5f1e8)",
                color: "var(--wb-color-aged-ink, #2a2a2a)",
                cursor: "pointer",
              }}
            >
              retry
            </button>
          ) : null}
        </div>
      ) : null}

      {/* Mic + textarea */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            type="button"
            data-testid="voice-mic-toggle"
            data-listening={status === "listening" ? "true" : "false"}
            onClick={toggleMic}
            disabled={!speechLive || status === "submitting"}
            title={
              speechLive
                ? status === "listening"
                  ? "stop listening"
                  : "start listening"
                : "speech recognition not available — type your question"
            }
            style={{
              fontFamily: "var(--wb-font-mono, monospace)",
              fontSize: 12,
              padding: "8px 12px",
              border: "1px solid var(--wb-color-aged-ink, #2a2a2a)",
              background:
                status === "listening"
                  ? "var(--wb-color-botanical-green-soft, #d6e3c7)"
                  : "var(--wb-color-paper, #f5f1e8)",
              color: "var(--wb-color-aged-ink, #2a2a2a)",
              cursor:
                !speechLive || status === "submitting"
                  ? "not-allowed"
                  : "pointer",
              opacity: !speechLive ? 0.55 : 1,
            }}
          >
            {status === "listening"
              ? "■ stop"
              : speechLive
                ? "● mic"
                : "mic ✕"}
          </button>
          <span
            data-testid="voice-support-status"
            className="wb-mono"
            style={{
              fontSize: 11,
              color: "var(--wb-color-hash-gray, #6b6258)",
            }}
          >
            {speechLive
              ? status === "listening"
                ? "listening…"
                : "press mic or type below"
              : "browser STT unavailable — type below"}
          </span>
        </div>
        <textarea
          data-testid="voice-transcript"
          value={fullTranscript}
          onChange={(e) => {
            setTranscript(e.target.value);
            setInterim("");
          }}
          rows={3}
          placeholder='e.g. "what was Q3 net revenue?"'
          // The textarea is the universal fallback. It is only ever
          // disabled while a request is in flight — never by speech
          // state.
          disabled={status === "submitting"}
          style={{
            fontFamily: "var(--wb-font-mono, monospace)",
            fontSize: 13,
            padding: "8px 10px",
            border: "1px solid var(--wb-color-rule-line, #c8bfac)",
            background: "var(--wb-color-paper, #f5f1e8)",
            color: "var(--wb-color-aged-ink, #2a2a2a)",
            resize: "vertical",
          }}
        />
        <button
          type="button"
          data-testid="voice-submit"
          onClick={submit}
          disabled={status === "submitting" || !fullTranscript.trim()}
          style={{
            fontFamily: "var(--wb-font-mono, monospace)",
            fontSize: 12,
            padding: "8px 14px",
            border: "1px solid var(--wb-color-aged-ink, #2a2a2a)",
            background: "var(--wb-color-aged-ink, #2a2a2a)",
            color: "var(--wb-color-paper, #f5f1e8)",
            cursor:
              status === "submitting" || !fullTranscript.trim()
                ? "not-allowed"
                : "pointer",
            opacity:
              status === "submitting" || !fullTranscript.trim() ? 0.55 : 1,
          }}
        >
          {status === "submitting" ? "asking…" : "ask the worm"}
        </button>
      </div>

      {status === "error" && errorMsg ? (
        <div
          data-testid="voice-error"
          style={{
            padding: "10px 12px",
            border: "1px solid #9c1f1f",
            background: "#fde7e7",
            color: "#7a0e0e",
            fontFamily: "var(--wb-font-mono, monospace)",
            fontSize: 12,
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <strong>service unavailable</strong>
          <span>{errorMsg}</span>
          <button
            type="button"
            data-testid="voice-retry"
            onClick={() => {
              setStatus("idle");
              setErrorMsg(null);
            }}
            style={{
              alignSelf: "flex-start",
              fontFamily: "var(--wb-font-mono, monospace)",
              fontSize: 11,
              padding: "4px 10px",
              border: "1px solid #9c1f1f",
              background: "var(--wb-color-paper, #f5f1e8)",
              color: "#7a0e0e",
              cursor: "pointer",
            }}
          >
            retry
          </button>
        </div>
      ) : null}

      {answer ? (
        <section
          data-testid="voice-answer"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
            padding: "12px 14px",
            border: "1px solid var(--wb-color-rule-line, #c8bfac)",
            background: "var(--wb-color-paper-edge, #ebe6d6)",
          }}
        >
          <p
            data-testid="voice-answer-text"
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif, Georgia, serif)",
              fontSize: 14,
              lineHeight: 1.5,
              color: "var(--wb-color-aged-ink, #2a2a2a)",
            }}
          >
            {answer.answer}
          </p>
          <dl
            className="wb-mono"
            style={{
              display: "grid",
              gridTemplateColumns: "auto 1fr",
              columnGap: 10,
              rowGap: 2,
              margin: 0,
              fontSize: 11,
              color: "var(--wb-color-hash-gray, #6b6258)",
            }}
          >
            <dt>receipt</dt>
            <dd
              data-testid="voice-hash-receipt"
              style={{ margin: 0, wordBreak: "break-all" }}
            >
              {answer.hashReceipt
                ? `sha256 · ${answer.hashReceipt.slice(0, 16)}…`
                : "—"}
            </dd>
            <dt>trace</dt>
            <dd style={{ margin: 0 }}>
              {answer.ledgerSeq != null ? (
                <a
                  data-testid="voice-trace-link"
                  data-citation-kind={answer.citationKind ?? "chat_sent"}
                  href={`/trace?seq=${answer.ledgerSeq}`}
                  style={{
                    color: "var(--wb-color-botanical-green-deep, #2e5a2e)",
                    textDecoration: "underline",
                  }}
                  title={
                    answer.citationKind === "kpi_node" && answer.kpi
                      ? `KPI ${answer.kpi.name} — most recent ledger entry`
                      : "ledger entry for this answer"
                  }
                >
                  {answer.citationKind === "kpi_node" && answer.kpi
                    ? `KPI ${answer.kpi.name} · ledger row ${answer.ledgerSeq}`
                    : `ledger row ${answer.ledgerSeq}`}
                </a>
              ) : (
                "—"
              )}
            </dd>
            {answer.kpi ? (
              <>
                <dt>kpi</dt>
                <dd
                  data-testid="voice-kpi-meta"
                  style={{ margin: 0, wordBreak: "break-all" }}
                >
                  {answer.kpi.name}
                  {answer.kpi.formula ? ` · ${answer.kpi.formula}` : ""}
                  {answer.kpi.unit ? ` (${answer.kpi.unit})` : ""}
                </dd>
              </>
            ) : null}
            {answer.model ? (
              <>
                <dt>model</dt>
                <dd style={{ margin: 0 }}>{answer.model}</dd>
              </>
            ) : null}
          </dl>
        </section>
      ) : null}
    </aside>
  );
}

export { defaultAsk, classifySpeechError };
