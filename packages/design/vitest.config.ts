import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "happy-dom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    // Emit JUnit XML alongside the default reporter so `make qa-report`
    // can fold the design-system L2 component count into the layer table.
    reporters: ["default", "junit"],
    outputFile: {
      junit: path.resolve(__dirname, "../../.junit/l2-design.xml"),
    },
  },
});
