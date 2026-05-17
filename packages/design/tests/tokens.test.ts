import { describe, it, expect } from "vitest";
import {
  colors,
  colorsCssVariables,
  typography,
  spacing,
  motion,
} from "../src/tokens/index";

describe("Field Notebook color tokens", () => {
  it("locks the warm paper base", () => {
    expect(colors.paper).toBe("#FAF7F0");
  });

  it("locks aged-ink charcoal as primary text", () => {
    expect(colors.agedInk).toBe("#2A2A2A");
  });

  it("locks botanical green as institutional accent", () => {
    expect(colors.botanicalGreen).toBe("#2C5F3E");
  });

  it("locks sepia as warning-only", () => {
    expect(colors.sepiaWarning).toBe("#B8603C");
  });

  it("locks hash-gray for metadata", () => {
    expect(colors.hashGray).toBe("#7A7A7A");
  });

  it("exposes every color as a --wb-color-* CSS variable", () => {
    expect(colorsCssVariables["--wb-color-paper"]).toBe("#FAF7F0");
    expect(colorsCssVariables["--wb-color-aged-ink"]).toBe("#2A2A2A");
    expect(colorsCssVariables["--wb-color-botanical-green"]).toBe("#2C5F3E");
    expect(colorsCssVariables["--wb-color-sepia-warning"]).toBe("#B8603C");
    expect(colorsCssVariables["--wb-color-hash-gray"]).toBe("#7A7A7A");
  });

  it("ports Phase 1B tonal layers (paper-deep, paper-edge, ink-soft, ink-faint)", () => {
    expect(colors.paperDeep).toBe("#F2ECDE");
    expect(colors.paperEdge).toBe("#E8E0CC");
    expect(colors.agedInkSoft).toBe("#4A4842");
    expect(colors.inkFaint).toBe("#A8A49A");
  });

  it("ports Phase 1B botanical depth + classification wash", () => {
    expect(colors.botanicalGreenDeep).toBe("#1F4A2E");
    expect(colors.botanicalGreenSoft).toBe("#E6EDE4");
  });

  it("ports Phase 1B sepia wash (warning soft)", () => {
    expect(colors.sepiaWarningSoft).toBe("#F3E4DA");
  });
});

describe("Field Notebook typography tokens", () => {
  it("leads with Tiempos and falls back through editorial serifs", () => {
    expect(typography.fontFamily.serif).toContain("Tiempos Text");
    expect(typography.fontFamily.serif).toContain("Source Serif 4");
    expect(typography.fontFamily.serif).toContain("GT Super");
  });

  it("leads with Berkeley Mono and falls back through distinctive monos", () => {
    expect(typography.fontFamily.mono).toContain("Berkeley Mono");
    expect(typography.fontFamily.mono).toContain("Tuesday Mono");
    expect(typography.fontFamily.mono).toContain("JetBrains Mono");
  });

  it("uses a 1.25 ratio type scale from 12px to 64px", () => {
    expect(typography.ratio).toBe(1.25);
    expect(typography.scale.xs).toBe("12px");
    expect(typography.scale["4xl"]).toBe("64px");
  });

  it("defines institutional weights 400–700", () => {
    expect(typography.weight.regular).toBe(400);
    expect(typography.weight.bold).toBe(700);
  });
});

describe("Field Notebook spacing tokens", () => {
  it("uses a 4px base grid", () => {
    expect(spacing["1"]).toBe("4px");
  });

  it("exposes the 2/4/6/8/12/16/24/32/48/64 scale", () => {
    expect(spacing["0.5"]).toBe("2px");
    expect(spacing["1"]).toBe("4px");
    expect(spacing["1.5"]).toBe("6px");
    expect(spacing["2"]).toBe("8px");
    expect(spacing["3"]).toBe("12px");
    expect(spacing["4"]).toBe("16px");
    expect(spacing["6"]).toBe("24px");
    expect(spacing["8"]).toBe("32px");
    expect(spacing["12"]).toBe("48px");
    expect(spacing["16"]).toBe("64px");
  });
});

describe("Field Notebook motion tokens", () => {
  it("defines a breathing ease curve", () => {
    expect(motion.easing.breathing).toBe(
      "cubic-bezier(0.45, 0.05, 0.55, 0.95)"
    );
  });

  it("sets stagger-entry at 80ms", () => {
    expect(motion.duration.staggerEntry).toBe(80);
  });

  it("caps breathing amplitude at ±0.5%", () => {
    expect(motion.breathingAmplitude).toBe(0.005);
  });

  it("runs a 3-second breathing cycle", () => {
    expect(motion.duration.breathing).toBe(3000);
  });
});
