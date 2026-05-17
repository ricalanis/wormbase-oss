/**
 * WizardProgress — three rectangular rules stacked horizontally. Filled-ink
 * for completed, hollow for upcoming. NOT a rounded progress bar.
 */

export function WizardProgress({
  currentTier,
  completed = [],
}: {
  currentTier: 1 | 2 | 3;
  completed?: number[];
}) {
  const tiers = [1, 2, 3] as const;
  return (
    <nav
      aria-label="onboarding progress"
      data-testid="wizard-progress"
      data-current-tier={currentTier}
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(3, 1fr)",
        gap: 8,
        borderTop: "1px solid var(--wb-color-paper-edge)",
        borderBottom: "1px solid var(--wb-color-paper-edge)",
        padding: "16px 0",
      }}
    >
      {tiers.map((t) => {
        const state =
          completed.includes(t)
            ? "done"
            : t === currentTier
              ? "current"
              : "pending";
        return (
          <div
            key={t}
            data-testid={`tier-${t}`}
            data-state={state}
            style={{
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
                color: "var(--wb-color-hash-gray)",
              }}
            >
              tier {String(t).padStart(2, "0")} ·{" "}
              {state === "done" ? "done" : state === "current" ? "current" : "pending"}
            </span>
            <span
              aria-hidden="true"
              style={{
                height: 6,
                background:
                  state === "done"
                    ? "var(--wb-color-aged-ink)"
                    : state === "current"
                      ? "var(--wb-color-botanical-green)"
                      : "var(--wb-color-paper-deep)",
                border: "1px solid var(--wb-color-aged-ink)",
              }}
            />
            <span
              style={{
                fontFamily: "var(--wb-font-serif)",
                fontSize: 14,
                fontWeight: state === "current" ? 600 : 400,
                color: "var(--wb-color-aged-ink)",
              }}
            >
              {t === 1 ? "Setup" : t === 2 ? "Context" : "Policy"}
            </span>
          </div>
        );
      })}
    </nav>
  );
}
