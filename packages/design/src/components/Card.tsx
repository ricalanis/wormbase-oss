import { type HTMLAttributes, type ReactNode, forwardRef } from "react";

export interface CardProps
  extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title?: ReactNode;
  eyebrow?: ReactNode;
  children: ReactNode;
  /** Dense cards drop padding; used for ledger lists. */
  density?: "default" | "dense";
}

/**
 * Field Notebook card — warm paper, thin rule, no shadow, no rounded corner
 * beyond 2px. The card is a framed page, not a floating chip.
 */
export const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ title, eyebrow, children, density = "default", style, ...rest }, ref) => {
    const padding = density === "dense" ? "var(--wb-space-4)" : "var(--wb-space-6)";
    return (
      <section
        ref={ref}
        {...rest}
        style={{
          background: "var(--wb-color-paper)",
          border: "1px solid var(--wb-color-rule-line)",
          borderRadius: "2px",
          padding,
          display: "flex",
          flexDirection: "column",
          gap: "var(--wb-space-4)",
          ...style,
        }}
      >
        {eyebrow ? (
          <div
            className="wb-mono"
            style={{
              fontSize: "var(--wb-text-xs)",
              color: "var(--wb-color-hash-gray)",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
            }}
          >
            {eyebrow}
          </div>
        ) : null}
        {title ? (
          <h3
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: "var(--wb-text-md)",
              fontWeight: 600,
              color: "var(--wb-color-aged-ink)",
              letterSpacing: "-0.005em",
            }}
          >
            {title}
          </h3>
        ) : null}
        <div>{children}</div>
      </section>
    );
  }
);
Card.displayName = "Card";
