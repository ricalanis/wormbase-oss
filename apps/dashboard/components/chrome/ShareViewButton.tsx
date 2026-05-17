"use client";
/**
 * ShareViewButton — copy a deep-link URL of the current view to the
 * clipboard. Renders on every existing tab (D8 of the production-
 * dashboard plan).
 *
 * Behavior: click → reads window.location.href → writes to clipboard →
 * shows a brief "copied" confirmation. Falls back to a plain alert when
 * the navigator.clipboard API is unavailable (older browsers, file://
 * contexts, JSDOM).
 *
 * Visual language: same chrome as other inline action chips. wb-mono
 * caps, square corners, CSS-variable tokens.
 */
import { useCallback, useState } from "react";

export function ShareViewButton({ label = "share view" }: { label?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "error">("idle");

  const onClick = useCallback(async () => {
    try {
      const url = window.location.href;
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
      } else {
        // Fallback for environments without the Clipboard API. Use a
        // hidden textarea + execCommand so the share gesture still
        // succeeds; users see the URL in the alert.
        window.prompt("Copy this URL:", url);
      }
      setState("copied");
      setTimeout(() => setState("idle"), 1500);
    } catch {
      setState("error");
      setTimeout(() => setState("idle"), 1500);
    }
  }, []);

  const text =
    state === "copied"
      ? "copied ✓"
      : state === "error"
        ? "copy failed"
        : label;

  return (
    <button
      type="button"
      data-testid="share-view-button"
      data-state={state}
      onClick={onClick}
      className="wb-mono"
      style={{
        fontSize: 10,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        padding: "4px 8px",
        border: "1px solid var(--wb-color-aged-ink)",
        background:
          state === "copied"
            ? "var(--wb-color-botanical-green-soft)"
            : "var(--wb-color-paper)",
        color: "var(--wb-color-aged-ink)",
        cursor: "pointer",
        borderRadius: 0,
      }}
    >
      {text}
    </button>
  );
}
