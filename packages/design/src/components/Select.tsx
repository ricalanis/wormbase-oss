"use client";

import {
  type ReactNode,
  type SelectHTMLAttributes,
  forwardRef,
  useId,
} from "react";

export interface SelectOption {
  value: string;
  label: string;
  hint?: string;
}

export interface SelectProps
  extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "children"> {
  label?: ReactNode;
  options: SelectOption[];
  helperText?: ReactNode;
}

/**
 * Field Notebook select — rectangular card, thin rule border, serif label.
 *
 * Uses the native <select> for accessibility; style is disciplined
 * — no chevron gradients, no rounded pills.
 */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, options, helperText, id, style, ...rest }, ref) => {
    const autoId = useId();
    const selectId = id ?? autoId;
    const helperId = `${selectId}-helper`;

    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "var(--wb-space-1_5)",
        }}
      >
        {label ? (
          <label
            htmlFor={selectId}
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: "var(--wb-text-sm)",
              color: "var(--wb-color-aged-ink)",
              letterSpacing: "0.02em",
            }}
          >
            {label}
          </label>
        ) : null}
        <div
          style={{
            position: "relative",
            border: "1px solid var(--wb-color-aged-ink)",
            borderRadius: "2px",
            background: "var(--wb-color-paper)",
          }}
        >
          <select
            ref={ref}
            id={selectId}
            aria-describedby={helperText ? helperId : undefined}
            {...rest}
            style={{
              width: "100%",
              appearance: "none",
              WebkitAppearance: "none",
              MozAppearance: "none",
              fontFamily: "var(--wb-font-serif)",
              fontSize: "var(--wb-text-base)",
              color: "var(--wb-color-aged-ink)",
              background: "transparent",
              border: "none",
              outline: "none",
              padding: "10px 36px 10px 14px",
              cursor: "pointer",
              ...style,
            }}
          >
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
                {o.hint ? ` — ${o.hint}` : ""}
              </option>
            ))}
          </select>
          <svg
            aria-hidden="true"
            width="10"
            height="6"
            viewBox="0 0 10 6"
            style={{
              position: "absolute",
              right: "14px",
              top: "50%",
              transform: "translateY(-50%)",
              pointerEvents: "none",
            }}
          >
            <path
              d="M1 1l4 4 4-4"
              stroke="var(--wb-color-aged-ink)"
              strokeWidth="1"
              fill="none"
            />
          </svg>
        </div>
        {helperText ? (
          <span
            id={helperId}
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: "var(--wb-text-xs)",
              color: "var(--wb-color-hash-gray)",
              fontStyle: "italic",
            }}
          >
            {helperText}
          </span>
        ) : null}
      </div>
    );
  }
);
Select.displayName = "Select";
