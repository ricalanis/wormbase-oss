"use client";

import {
  type InputHTMLAttributes,
  type ReactNode,
  forwardRef,
  useId,
} from "react";

export interface InputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  label?: ReactNode;
  helperText?: ReactNode;
  error?: ReactNode;
}

/**
 * Field Notebook input — underlined baseline, serif type, hash-gray helper.
 *
 * No rounded box. No inner shadow. No pastel fill. The field is a rule on
 * paper; you write on the line.
 */
export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, helperText, error, id, style, ...rest }, ref) => {
    const autoId = useId();
    const inputId = id ?? autoId;
    const helperId = `${inputId}-helper`;
    const borderColor = error
      ? "var(--wb-color-sepia-warning)"
      : "var(--wb-color-aged-ink)";

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
            htmlFor={inputId}
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
        <input
          ref={ref}
          id={inputId}
          aria-describedby={helperText || error ? helperId : undefined}
          aria-invalid={error ? true : undefined}
          {...rest}
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: "var(--wb-text-md)",
            color: "var(--wb-color-aged-ink)",
            background: "transparent",
            border: "none",
            borderBottom: `1px solid ${borderColor}`,
            outline: "none",
            padding: "6px 0",
            transition:
              "border-color var(--wb-duration-standard) var(--wb-ease-standard)",
            ...style,
          }}
          onFocus={(e) => {
            if (!error) {
              e.currentTarget.style.borderBottomColor =
                "var(--wb-color-botanical-green)";
            }
            rest.onFocus?.(e);
          }}
          onBlur={(e) => {
            e.currentTarget.style.borderBottomColor = borderColor;
            rest.onBlur?.(e);
          }}
        />
        {error ? (
          <span
            id={helperId}
            role="alert"
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: "var(--wb-text-xs)",
              color: "var(--wb-color-sepia-warning)",
              letterSpacing: "0.02em",
            }}
          >
            {error}
          </span>
        ) : helperText ? (
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
Input.displayName = "Input";
