import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { WormMark, Wordmark, Lockup, Rule } from "../src/components/index";

describe("WormMark", () => {
  it("renders an SVG with seal + worm + arched wordmark", () => {
    const { container } = render(<WormMark size={120} />);
    const svg = container.querySelector("svg[data-wormmark]")!;
    expect(svg).toBeTruthy();
    expect(svg.getAttribute("viewBox")).toBe("0 0 300 300");
    // seal: outer + inner circle
    expect(container.querySelectorAll("circle[r='142']").length).toBe(1);
    expect(container.querySelectorAll("circle[r='130']").length).toBe(1);
    // worm path
    expect(container.querySelector("path")).toBeTruthy();
    // arched wordmark text
    expect(container.querySelector("textPath")?.textContent).toBe("WORMBASE");
  });

  it("supports outline mode (transparent fill)", () => {
    const { container } = render(<WormMark mode="outline" />);
    const svg = container.querySelector("svg[data-wormmark]")!;
    expect(svg.getAttribute("data-mode")).toBe("outline");
  });

  it("supports negative mode (ink fill)", () => {
    const { container } = render(<WormMark mode="negative" />);
    const svg = container.querySelector("svg[data-wormmark]")!;
    expect(svg.getAttribute("data-mode")).toBe("negative");
  });

  it("hides arch + ticks when requested (favicon mode)", () => {
    const { container } = render(<WormMark size={32} showArc={false} ticks={false} />);
    expect(container.querySelector("textPath")).toBeNull();
    expect(container.querySelector("g[data-ticks]")).toBeNull();
  });

  it("renders accessible aria-label", () => {
    const { container } = render(<WormMark title="Specimen 001" />);
    expect(container.querySelector("svg")?.getAttribute("aria-label")).toBe(
      "Specimen 001"
    );
  });
});

describe("Wordmark", () => {
  it("renders WORMBASE in serif with rule", () => {
    const { container, getByText } = render(<Wordmark height={32} />);
    const wordmark = getByText("WORMBASE");
    expect(wordmark.style.fontSize).toBe("32px");
    // rule beneath
    const rule = container.querySelectorAll("span")[2];
    expect(rule).toBeTruthy();
  });

  it("can hide the rule", () => {
    const { container } = render(<Wordmark rule={false} />);
    // the parent + the WORMBASE span = 2 spans only when rule=false
    const inlineRule = container.querySelector("[aria-hidden='true']");
    expect(inlineRule).toBeNull();
  });
});

describe("Lockup", () => {
  it("renders horizontal orientation by default with receipt tagline", () => {
    const { container, getByText } = render(<Lockup />);
    expect(container.querySelector("[data-lockup][data-orientation='horizontal']")).toBeTruthy();
    expect(getByText(/INSTITUTIONAL DATA AGENT/)).toBeTruthy();
  });

  it("renders stacked orientation with shorter tagline", () => {
    const { container, getByText } = render(<Lockup orientation="stacked" />);
    expect(container.querySelector("[data-lockup][data-orientation='stacked']")).toBeTruthy();
    expect(getByText("INSTITUTIONAL DATA AGENT")).toBeTruthy();
  });

  it("hides the receipt when withReceipt=false", () => {
    const { queryByText } = render(<Lockup withReceipt={false} />);
    expect(queryByText(/INSTITUTIONAL DATA AGENT/)).toBeNull();
  });
});

describe("Rule", () => {
  it("renders thin variant by default", () => {
    const { container } = render(<Rule />);
    const r = container.querySelector("[data-rule]")!;
    expect(r.getAttribute("data-rule")).toBe("thin");
  });

  it("renders all four variants", () => {
    const variants = ["thin", "strong", "double", "dashed"] as const;
    for (const v of variants) {
      const { container } = render(<Rule variant={v} />);
      expect(container.querySelector(`[data-rule='${v}']`)).toBeTruthy();
    }
  });

  it("is decorative (aria-hidden) by default", () => {
    const { container } = render(<Rule />);
    expect(container.querySelector("[data-rule]")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("becomes a separator when label is provided", () => {
    const { container } = render(<Rule label="end of section" />);
    const r = container.querySelector("[data-rule]")!;
    expect(r.getAttribute("role")).toBe("separator");
    expect(r.getAttribute("aria-label")).toBe("end of section");
  });
});
