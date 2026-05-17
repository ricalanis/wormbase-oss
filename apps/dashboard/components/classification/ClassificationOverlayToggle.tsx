"use client";

import { useEffect, useState } from "react";

/**
 * ClassificationOverlayToggle — sets `[data-overlay="classification"]` on
 * <body> so every Receipt grows a 4px sepia/green/gray left band per its
 * classification. The overlay reveals information that was always present;
 * it does not introduce new chrome.
 *
 * Persistence is per-session via sessionStorage; we deliberately do NOT cross
 * page reloads (per Task 4.12 contract).
 */
export function ClassificationOverlayToggle() {
  const [on, setOn] = useState<boolean>(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.sessionStorage.getItem("wb:classification-overlay");
    if (stored === "1") setOn(true);
  }, []);

  useEffect(() => {
    if (typeof document === "undefined") return;
    if (on) {
      document.body.setAttribute("data-overlay", "classification");
      window.sessionStorage.setItem("wb:classification-overlay", "1");
    } else {
      document.body.removeAttribute("data-overlay");
      window.sessionStorage.removeItem("wb:classification-overlay");
    }
  }, [on]);

  return (
    <button
      type="button"
      data-testid="classification-overlay-toggle"
      data-state={on ? "on" : "off"}
      aria-pressed={on}
      onClick={() => setOn((v) => !v)}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        padding: "8px 10px",
        background: "transparent",
        border: "1px solid var(--wb-color-aged-ink)",
        borderRadius: 0,
        cursor: "pointer",
        color: "var(--wb-color-aged-ink)",
        fontFamily: "var(--wb-font-serif)",
        fontSize: 13,
        letterSpacing: "0.01em",
        textAlign: "left",
        width: "100%",
      }}
    >
      <span
        aria-hidden="true"
        style={{
          width: 14,
          height: 14,
          background: on
            ? "var(--wb-color-botanical-green)"
            : "var(--wb-color-paper-deep)",
          border: "1px solid var(--wb-color-aged-ink)",
        }}
      />
      Classification overlay
      <span
        className="wb-mono"
        style={{
          marginLeft: "auto",
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        {on ? "on" : "off"}
      </span>
    </button>
  );
}
