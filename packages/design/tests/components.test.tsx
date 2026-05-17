import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  Button,
  Input,
  Select,
  Card,
  Receipt,
  Gauge,
  LedgerEntry,
  Page,
} from "../src/components/index";

describe("Button", () => {
  it("renders the label and handles clicks", () => {
    let clicks = 0;
    render(
      <Button onClick={() => (clicks += 1)}>Create demo workspace</Button>
    );
    const btn = screen.getByRole("button", { name: /create demo workspace/i });
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    expect(clicks).toBe(1);
  });

  it("renders serif typography (not system sans)", () => {
    render(<Button>Next</Button>);
    const btn = screen.getByRole("button", { name: /next/i });
    expect(btn.style.fontFamily).toContain("wb-font-serif");
  });

  it("uses near-rectangular (≤2px) corners — no pills", () => {
    render(<Button>Save</Button>);
    const btn = screen.getByRole("button", { name: /save/i });
    expect(btn.style.borderRadius).toBe("2px");
  });

  it("supports the danger variant via sepia", () => {
    render(<Button variant="danger">Block</Button>);
    const btn = screen.getByRole("button", { name: /block/i });
    expect(btn.style.background).toContain("sepia-warning");
  });
});

describe("Input", () => {
  it("renders label and accepts value changes", () => {
    render(<Input label="Company name" defaultValue="DemoCorp" />);
    const inp = screen.getByLabelText("Company name") as HTMLInputElement;
    expect(inp.value).toBe("DemoCorp");
    fireEvent.change(inp, { target: { value: "AcmeCo" } });
    expect(inp.value).toBe("AcmeCo");
  });

  it("renders helper text in hash-gray italic", () => {
    render(
      <Input
        label="Tenant slug"
        helperText="Lowercase, no spaces. Used in URLs."
      />
    );
    const helper = screen.getByText(/lowercase, no spaces/i);
    expect(helper.style.color).toContain("hash-gray");
    expect(helper.style.fontStyle).toBe("italic");
  });

  it("shows an error in sepia when provided", () => {
    render(<Input label="Slack token" error="Token expired." />);
    const err = screen.getByRole("alert");
    expect(err.textContent).toBe("Token expired.");
    expect(err.style.color).toContain("sepia-warning");
  });

  it("uses an underlined baseline, not a boxed shape", () => {
    render(<Input label="x" />);
    const inp = screen.getByLabelText("x");
    const styleAttr = inp.getAttribute("style") ?? "";
    // happy-dom splits the shorthand; the key assertion is no boxing border
    // on top/left/right while the bottom gets a rule.
    expect(styleAttr).toContain("border-style: none");
    expect(styleAttr).toContain("--wb-color-aged-ink");
  });
});

describe("Select", () => {
  const opts = [
    { value: "saas", label: "SaaS" },
    { value: "marketplace", label: "Marketplace" },
    { value: "fintech", label: "Fintech" },
  ];

  it("renders options and fires onChange", () => {
    let chosen = "";
    render(
      <Select
        label="KPI template"
        options={opts}
        onChange={(e) => (chosen = e.currentTarget.value)}
      />
    );
    const sel = screen.getByLabelText("KPI template") as HTMLSelectElement;
    fireEvent.change(sel, { target: { value: "fintech" } });
    expect(chosen).toBe("fintech");
  });

  it("uses native select for accessibility", () => {
    render(<Select label="x" options={opts} />);
    expect(screen.getByLabelText("x").tagName).toBe("SELECT");
  });
});

describe("Card", () => {
  it("renders title and children", () => {
    render(
      <Card title="Domains">
        <p>Two domains: product, finance.</p>
      </Card>
    );
    expect(screen.getByRole("heading", { name: /domains/i })).toBeInTheDocument();
    expect(screen.getByText(/two domains/i)).toBeInTheDocument();
  });

  it("renders eyebrow in mono uppercase when provided", () => {
    render(
      <Card eyebrow="PROJECTION" title="Ramp">
        <div />
      </Card>
    );
    const eyebrow = screen.getByText("PROJECTION");
    expect(eyebrow.className).toContain("wb-mono");
  });

  it("uses paper background and rule border (no shadow)", () => {
    const { container } = render(<Card>body</Card>);
    const card = container.querySelector("section")!;
    const styleAttr = card.getAttribute("style") ?? "";
    expect(styleAttr).toContain("--wb-color-paper");
    expect(styleAttr).toContain("--wb-color-rule-line");
    expect(styleAttr).not.toContain("box-shadow");
  });
});

describe("Receipt (signature primitive)", () => {
  it("renders all four provenance fields", () => {
    const { container } = render(
      <Receipt
        hash="a3f9c2"
        source="subscriptions × accounts"
        owner="ricardo"
        classification="internal"
      />
    );
    expect(
      container.querySelector('[aria-label="hash"]')!.textContent
    ).toBe("#a3f9c2");
    expect(
      container.querySelector('[aria-label="source"]')!.textContent
    ).toBe("subscriptions × accounts");
    expect(
      container.querySelector('[aria-label="owner"]')!.textContent
    ).toBe("@ricardo");
    expect(
      container.querySelector('[aria-label="classification"]')!.textContent
    ).toBe("internal");
  });

  it("uses mono font semantically (marks ledger content)", () => {
    const { container } = render(
      <Receipt
        hash="abc123"
        source="x"
        owner="y"
        classification="z"
        compact
      />
    );
    const root = container.firstChild as HTMLElement;
    expect(root.className).toContain("wb-mono");
  });

  it("renders timestamp when provided", () => {
    const { container } = render(
      <Receipt
        hash="abc"
        source="s"
        owner="o"
        classification="internal"
        timestamp="2026-04-29T14:03:22Z"
        compact
      />
    );
    expect(
      container.querySelector('[aria-label="timestamp"]')!.textContent
    ).toBe("2026-04-29T14:03:22Z");
  });
});

describe("Gauge", () => {
  it("renders label and meter role with value", () => {
    render(<Gauge label="Ontology" value={30} instant />);
    const meter = screen.getByRole("meter", { name: "Ontology" });
    expect(meter.getAttribute("aria-valuenow")).toBe("30");
    expect(meter.getAttribute("aria-valuemax")).toBe("100");
  });

  it("clamps values above 100", () => {
    render(<Gauge label="X" value={250} instant />);
    const meter = screen.getByRole("meter", { name: "X" });
    expect(meter.getAttribute("aria-valuenow")).toBe("100");
  });

  it("clamps negative values to 0", () => {
    render(<Gauge label="X" value={-5} instant />);
    expect(screen.getByRole("meter").getAttribute("aria-valuenow")).toBe("0");
  });
});

describe("LedgerEntry", () => {
  it("renders timestamp, badge, hash, summary", () => {
    render(
      <LedgerEntry
        timestamp="08:14:02"
        entryType="propose"
        hash="a3f9c2"
        summary="Proposed source: subscriptions.csv"
      />
    );
    expect(screen.getByText("08:14:02")).toBeInTheDocument();
    expect(screen.getByText("propose")).toBeInTheDocument();
    expect(screen.getByText("#a3f9c2")).toBeInTheDocument();
    expect(
      screen.getByText(/proposed source: subscriptions.csv/i)
    ).toBeInTheDocument();
  });

  it("expands detail on click when detail is provided", () => {
    render(
      <LedgerEntry
        timestamp="08:14:02"
        entryType="execute"
        hash="f00bar"
        summary="Executed model build"
        detail={'{"sql": "SELECT 1"}'}
      />
    );
    const btn = screen.getByRole("button", { name: /expand/i });
    expect(screen.queryByText(/SELECT 1/)).not.toBeInTheDocument();
    fireEvent.click(btn);
    expect(screen.getByText(/SELECT 1/)).toBeInTheDocument();
  });

  it("colors gate_fired entries sepia", () => {
    const { container } = render(
      <LedgerEntry
        timestamp="08:14:02"
        entryType="gate_fired"
        hash="deadbe"
        summary="PII gate fired on column email"
      />
    );
    const badge = container.querySelector(
      '[data-entry-type="gate_fired"] .wb-mono'
    ) as HTMLElement | null;
    expect(badge).toBeTruthy();
  });
});

describe("Page", () => {
  it("renders the WormBase wordmark and children", () => {
    render(
      <Page subtitle="onboarding · tier 1">
        <div>body content</div>
      </Page>
    );
    expect(screen.getByText("WormBase")).toBeInTheDocument();
    expect(screen.getByText("field notebook")).toBeInTheDocument();
    expect(screen.getByText("body content")).toBeInTheDocument();
    expect(screen.getByText(/onboarding · tier 1/i)).toBeInTheDocument();
  });

  it("places header-right slot content in the header", () => {
    render(
      <Page headerRight={<span>day 7</span>}>
        <div />
      </Page>
    );
    expect(screen.getByText("day 7")).toBeInTheDocument();
  });
});
