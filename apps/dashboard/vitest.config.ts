import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

/**
 * Vitest config — L1 unit tests for dashboard components and lib/.
 * Playwright owns L2 (page) tests under tests/e2e/.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@wormbase/design": path.resolve(__dirname, "../../packages/design/src"),
    },
  },
  test: {
    environment: "happy-dom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: [
      "tests/unit/**/*.test.{ts,tsx}",
      "tests/lib/**/*.test.{ts,tsx}",
      "tests/api/**/*.test.{ts,tsx}",
      "tests/components/**/*.test.{ts,tsx}",
      // W6.A2 — multi-tenant isolation sweep over every ledger-client
      // accessor; runs in vitest alongside the existing lib/ tests.
      "tests/multitenant/**/*.test.{ts,tsx}",
      // Block J6 places MCP tests adjacent to the components/page they
      // exercise — keep the brief's collocation while still folding the
      // results into the dashboard L2 JUnit report.
      "components/**/__tests__/**/*.test.{ts,tsx}",
      "app/**/__tests__/**/*.test.{ts,tsx}",
    ],
    // Emit JUnit XML alongside the default reporter so `make qa-report`
    // can fold the dashboard L2 component count into the layer table.
    // Path is relative to repo root (apps/dashboard/ → ../../).
    reporters: ["default", "junit"],
    outputFile: {
      junit: path.resolve(__dirname, "../../.junit/l2-dashboard.xml"),
    },
  },
});
