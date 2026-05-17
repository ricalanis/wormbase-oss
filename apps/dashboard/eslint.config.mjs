// ESLint flat config — Path 6 (full ESLint adoption).
//
// Adopts the Next.js v15 core-web-vitals + typescript baseline via FlatCompat
// (Next 15 still ships .eslintrc-style config). Rule deltas are documented
// inline; each disable/relax records WHY it lives, not just what it does.
//
// Invoked from package.json: `lint:next` → eslint . --max-warnings=0
// which then composes with the existing anti-pattern + typecheck steps.
import { FlatCompat } from "@eslint/eslintrc";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

const config = [
  {
    // Mirror tsconfig excludes + ESLint-irrelevant artifacts. Without this
    // the next/typescript preset tries to type-check `.next/`, build
    // outputs, and the lint-rules harness, which dwarfs the real surface.
    ignores: [
      ".next/**",
      "node_modules/**",
      "design-exports/**",
      "test-results/**",
      "playwright-report/**",
      "public/**",
      "scripts/**", // tsx-run scripts (anti-pattern lint, etc.); not part of the Next bundle
      "next-env.d.ts",
      "tsconfig.tsbuildinfo",
      // Generated / vendored
      "**/*.d.ts",
    ],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    rules: {
      // ---- Rules we keep at "error" (catch real bugs) ----
      // react-hooks/rules-of-hooks — inherited at "error" from next/core-web-vitals.
      // @next/next/no-html-link-for-pages — inherited at "error".
      //
      // ---- Rules at "error" (post-final-wave promotion) ----
      // no-explicit-any was held at warn during the Path 6 ESLint adoption
      // because at-the-time the dashboard had pre-existing ``any`` debt
      // across server actions and ledger-projection adapters. The Wave 6
      // ESLint Strategy-A cleanup already typed every adjacent surface
      // (SubscriptionRow, AgentSummary, etc.) so the empirical violation
      // count at the v2.B promotion gate was zero. Promote to error: a
      // future ``any`` introduction is now a CI block, not a warning that
      // accumulates silently.
      "@typescript-eslint/no-explicit-any": "error",
      // Unused vars are common in pattern-match-style destructuring across
      // server actions; underscore-prefix is the existing convention.
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // React hooks exhaustive-deps — warn (Next default). Several existing
      // components intentionally omit deps to avoid loops; promoting to
      // error would be wrong without per-case review.
      "react-hooks/exhaustive-deps": "warn",
      // The dashboard ships <img> in landing + visual demo surfaces where
      // next/image's required width/height props don't fit the layout
      // (e.g. inline icons, design-export SVGs). Warn, don't block.
      "@next/next/no-img-element": "warn",
      // The landing page intentionally uses <a> anchors for cross-app
      // links to documentation hosted on the same origin (the docs aren't
      // part of the Next router). Warn, don't block.
      "@next/next/no-html-link-for-pages": "warn",
      // ts-comment escape hatches are sometimes the right answer for
      // third-party type holes (pg row narrowing, FormData typing). Warn.
      "@typescript-eslint/ban-ts-comment": "warn",
      // Empty interfaces are used as marker types in a few places (e.g.
      // server-action shape extensions). Warn, not block.
      "@typescript-eslint/no-empty-object-type": "warn",
      // Server actions occasionally use `Function` as a wide-cast escape
      // hatch when forwarding form handlers. Warn.
      "@typescript-eslint/no-unsafe-function-type": "warn",
      // react/no-unescaped-entities flags literal apostrophes in JSX text
      // content (e.g. "We've" / "you're"). React HTML-encodes these
      // automatically; the rule is a strict-XHTML-era holdover that
      // produces no runtime / a11y / parsing bugs in modern React.
      // Fixing all instances would mean editing user-visible copy strings
      // in 16 production surfaces to use `&apos;` / `&rsquo;`, which
      // increases the risk of typos in copy without behavioral benefit.
      // The rule is widely disabled in production Next.js apps for this
      // reason (Next's own docs do not recommend it).
      "react/no-unescaped-entities": "off",
    },
  },
  {
    // Test files routinely use ``any`` to shape mock fixtures and stub
    // module surfaces. Disable a-few targeted rules in tests so the
    // signal-to-noise stays high in production code.
    files: ["**/__tests__/**/*.{ts,tsx}", "tests/**/*.{ts,tsx}", "**/*.test.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unused-vars": "off",
      "@typescript-eslint/ban-ts-comment": "off",
      "react-hooks/rules-of-hooks": "off", // some tests render hook-using components in test-only wrappers
      "@next/next/no-img-element": "off",
      // Tests sometimes use React.createElement(Component, { children: ... })
      // as a compact way to compose providers + children in dynamic imports.
      // Acceptable test pattern; not a runtime concern in test isolation.
      "react/no-children-prop": "off",
    },
  },
];

export default config;
