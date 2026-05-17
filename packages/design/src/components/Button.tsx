"use client";

import { type ButtonHTMLAttributes, type ReactNode, forwardRef } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  children: ReactNode;
}

/**
 * Field Notebook button — rectangular, serif label, no gradient, no shadow.
 *
 * Corner radius ≤2px. Primary uses botanical green; secondary uses ink;
 * danger uses sepia (warnings only); ghost is bare text with an
 * underline-on-hover — naturalist's journal, not SaaS admin.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "primary", size = "md", style, children, ...rest }, ref) => {
    const sizing = sizeMap[size];
    const palette = variantMap[variant];

    return (
      <button
        ref={ref}
        {...rest}
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          gap: "var(--wb-space-2)",
          fontFamily: "var(--wb-font-serif)",
          fontWeight: 500,
          fontSize: sizing.fontSize,
          padding: sizing.padding,
          borderRadius: "2px",
          border: palette.border,
          background: palette.bg,
          color: palette.fg,
          cursor: rest.disabled ? "not-allowed" : "pointer",
          opacity: rest.disabled ? 0.55 : 1,
          transition:
            "background var(--wb-duration-standard) var(--wb-ease-standard), color var(--wb-duration-standard) var(--wb-ease-standard)",
          letterSpacing: "0.01em",
          ...style,
        }}
        onMouseEnter={(e) => {
          if (rest.disabled) return;
          e.currentTarget.style.background = palette.bgHover;
          e.currentTarget.style.color = palette.fgHover;
        }}
        onMouseLeave={(e) => {
          if (rest.disabled) return;
          e.currentTarget.style.background = palette.bg;
          e.currentTarget.style.color = palette.fg;
        }}
      >
        {children}
      </button>
    );
  }
);
Button.displayName = "Button";

const sizeMap: Record<ButtonSize, { padding: string; fontSize: string }> = {
  sm: { padding: "6px 14px", fontSize: "var(--wb-text-sm)" },
  md: { padding: "10px 22px", fontSize: "var(--wb-text-base)" },
  lg: { padding: "14px 28px", fontSize: "var(--wb-text-md)" },
};

interface VariantPalette {
  bg: string;
  bgHover: string;
  fg: string;
  fgHover: string;
  border: string;
}

const variantMap: Record<ButtonVariant, VariantPalette> = {
  primary: {
    bg: "var(--wb-color-botanical-green)",
    bgHover: "var(--wb-color-botanical-green-deep)",
    fg: "var(--wb-color-paper)",
    fgHover: "var(--wb-color-paper)",
    border: "1px solid var(--wb-color-botanical-green-deep)",
  },
  secondary: {
    bg: "var(--wb-color-paper)",
    bgHover: "var(--wb-color-paper-deep)",
    fg: "var(--wb-color-aged-ink)",
    fgHover: "var(--wb-color-aged-ink)",
    border: "1px solid var(--wb-color-aged-ink)",
  },
  ghost: {
    bg: "transparent",
    bgHover: "var(--wb-color-highlight)",
    fg: "var(--wb-color-aged-ink)",
    fgHover: "var(--wb-color-aged-ink)",
    border: "1px solid transparent",
  },
  danger: {
    bg: "var(--wb-color-sepia-warning)",
    bgHover: "var(--wb-color-sepia-warning-deep)",
    fg: "var(--wb-color-paper)",
    fgHover: "var(--wb-color-paper)",
    border: "1px solid var(--wb-color-sepia-warning-deep)",
  },
};
