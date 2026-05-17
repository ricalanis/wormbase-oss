"use client";
/**
 * AskTheWormFloater — floating "Ask the worm" affordance (W3.A12).
 *
 * Bottom-right floating button. Click toggles a slide-in
 * :class:`VoicePanel`. The floater is mounted at the (app)/layout level
 * so every (app)-prefixed route gets the same universal voice
 * affordance — no per-page wiring required.
 *
 * The button is always visible; the panel is only rendered when open.
 * Browsers that don't support the Web Speech API (e.g. Firefox) still
 * see the button — the panel falls back to a text-input flow without
 * the mic.
 *
 * W7.A5 — the panel is wrapped in a localized `VoiceErrorBoundary`
 * (cousin of `chrome/PageErrorBoundary`). Speech-API init can throw
 * synchronously on some HTTPS-tunnel origins; if it does, the
 * boundary catches the render error and renders a compact honest
 * fallback that still lets the user type. The floater button itself
 * never crashes: a thrown panel does not take the rest of the app
 * with it.
 */
import {
  Component,
  type ErrorInfo,
  type ReactNode,
  useCallback,
  useState,
} from "react";

import { VoicePanel, type VoicePanelProps } from "./VoicePanel";

export interface AskTheWormFloaterProps
  extends Pick<VoicePanelProps, "ask" | "speechRecognitionFactory"> {
  /**
   * Initial open state — defaults to ``false``. Tests can mount with
   * ``initialOpen=true`` to skip the click-to-open step.
   */
  initialOpen?: boolean;
}

interface VoiceErrorBoundaryProps {
  children: ReactNode;
  onClose: () => void;
}

interface VoiceErrorBoundaryState {
  error: Error | null;
}

/**
 * Localized error boundary scoped to the voice panel. Mirrors the
 * `chrome/PageErrorBoundary` editorial pattern but rendered as a
 * compact panel-shaped surface so it doesn't blow up the bottom-right
 * UI.
 *
 * Why a class component? Error boundaries require
 * `componentDidCatch` / `getDerivedStateFromError`, which only exist
 * on classes. The hook ecosystem still doesn't have an equivalent.
 */
class VoiceErrorBoundary extends Component<
  VoiceErrorBoundaryProps,
  VoiceErrorBoundaryState
> {
  state: VoiceErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): VoiceErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Surface to the dev console without rethrowing. Production audit
    // trail lives server-side; this line is for local dev only.
    if (typeof window !== "undefined" && console?.error) {
      console.error(
        "[VoiceErrorBoundary]",
        "voice-panel render threw",
        error,
        info.componentStack,
      );
    }
  }

  handleDismiss = (): void => {
    this.setState({ error: null });
    this.props.onClose();
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <aside
        data-testid="voice-panel-error"
        role="alert"
        style={{
          position: "fixed",
          right: 24,
          bottom: 96,
          width: 380,
          maxHeight: "70vh",
          display: "flex",
          flexDirection: "column",
          gap: 10,
          background: "var(--wb-color-paper, #f5f1e8)",
          border: "1px dashed var(--wb-color-sepia-warning, #b85a3e)",
          boxShadow: "0 12px 32px rgba(0, 0, 0, 0.16)",
          padding: "16px 18px",
          zIndex: 9999,
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
          voice unavailable
        </span>
        <h3
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif, Georgia, serif)",
            fontSize: 16,
            fontWeight: 500,
          }}
        >
          Voice no disponible en este origen
        </h3>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif, Georgia, serif)",
            fontStyle: "italic",
            fontSize: 13,
            lineHeight: 1.45,
            color: "var(--wb-color-hash-gray, #6b6258)",
          }}
        >
          Speech recognition couldn&rsquo;t initialise here — usually a
          tunnel/cert restriction. Close this panel and ask in chat
          instead.
        </p>
        <code
          data-testid="voice-panel-error-detail"
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-hash-gray, #6b6258)",
            wordBreak: "break-all",
          }}
        >
          {error.message || "unknown speech-init error"}
        </code>
        <button
          type="button"
          data-testid="voice-panel-error-dismiss"
          onClick={this.handleDismiss}
          style={{
            alignSelf: "flex-start",
            fontFamily: "var(--wb-font-mono, monospace)",
            fontSize: 12,
            padding: "6px 12px",
            border: "1px solid var(--wb-color-aged-ink, #2a2a2a)",
            background: "var(--wb-color-paper, #f5f1e8)",
            color: "var(--wb-color-aged-ink, #2a2a2a)",
            cursor: "pointer",
          }}
        >
          dismiss
        </button>
      </aside>
    );
  }
}

export function AskTheWormFloater({
  ask,
  speechRecognitionFactory,
  initialOpen = false,
}: AskTheWormFloaterProps = {}) {
  const [open, setOpen] = useState<boolean>(initialOpen);

  const toggle = useCallback(() => setOpen((v) => !v), []);
  const close = useCallback(() => setOpen(false), []);

  return (
    <>
      <button
        type="button"
        data-testid="ask-the-worm-floater"
        data-open={open ? "true" : "false"}
        aria-label="ask the worm"
        aria-expanded={open}
        onClick={toggle}
        style={{
          position: "fixed",
          right: 24,
          bottom: 24,
          width: 56,
          height: 56,
          borderRadius: "50%",
          background: "var(--wb-color-aged-ink, #2a2a2a)",
          color: "var(--wb-color-paper, #f5f1e8)",
          border: "1px solid var(--wb-color-aged-ink, #2a2a2a)",
          cursor: "pointer",
          fontFamily: "var(--wb-font-serif, Georgia, serif)",
          fontSize: 22,
          fontWeight: 500,
          boxShadow: "0 4px 12px rgba(0, 0, 0, 0.18)",
          zIndex: 9998,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {open ? "×" : "?"}
      </button>
      <VoiceErrorBoundary onClose={close}>
        <VoicePanel
          open={open}
          onClose={close}
          ask={ask}
          speechRecognitionFactory={speechRecognitionFactory}
        />
      </VoiceErrorBoundary>
    </>
  );
}
