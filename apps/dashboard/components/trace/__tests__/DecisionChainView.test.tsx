/**
 * DecisionChainView — vertical chain visualisation tests (Phase 3 Task 3C).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  act,
  waitFor,
} from "@testing-library/react";
import { DecisionChainView } from "../DecisionChainView";
import type { DecisionChain } from "../../../lib/decision-chain";

const fullChain: DecisionChain = {
  decision: {
    kind: "decision_recorded",
    entryHash: "decisionhash00000000000000000000",
    entrySeq: "100",
    ts: "2026-04-30T08:00:00Z",
    summary: "Push Q3 close to Friday (channel C0FINANCE)",
    payload: { decision_id: "dec-q3-close", channel_id: "C0FINANCE" },
    linkHref: "/decisions",
    inferred: false,
  },
  processMap: {
    kind: "process_map_proposed",
    entryHash: "processhash000000000000000000000",
    entrySeq: "90",
    ts: "2026-04-29T14:00:00Z",
    summary: "Q3 close · 2 steps · finance",
    payload: { process_id: "proc-q3-close" },
    linkHref: "/processes",
    inferred: false,
  },
  kpi: {
    kind: "kpi_node",
    entryHash: "kpihash00000000000000000000000000",
    entrySeq: "80",
    ts: "2026-04-29T10:00:00Z",
    summary: "Q3 revenue = SUM(amount)",
    payload: { id: "revenue.q3" },
    linkHref: "/kpis",
    inferred: false,
  },
  source: {
    kind: "source_proposed",
    entryHash: "sourcehash0000000000000000000000",
    entrySeq: "70",
    ts: "2026-04-28T12:00:00Z",
    summary: "csv · s3://wormbase/finance/q3.csv",
    payload: { source_id: "src-finance-csv" },
    linkHref: "/sources",
    inferred: false,
  },
  bronze: {
    kind: "source_bronzed",
    entryHash: "bronzehash0000000000000000000000",
    entrySeq: "75",
    ts: "2026-04-28T12:05:00Z",
    summary: "1,024 bytes · 0 rows · sha256:abc",
    payload: { source_id: "src-finance-csv" },
    linkHref: "/sources",
    inferred: false,
  },
  missing: [],
};

describe("DecisionChainView · resolved chain", () => {
  it("renders all five chain steps", () => {
    render(<DecisionChainView chain={fullChain} />);
    expect(screen.getByTestId("chain-step-decision_recorded")).toBeInTheDocument();
    expect(screen.getByTestId("chain-step-process_map_proposed")).toBeInTheDocument();
    expect(screen.getByTestId("chain-step-kpi_node")).toBeInTheDocument();
    expect(screen.getByTestId("chain-step-source_proposed")).toBeInTheDocument();
    expect(screen.getByTestId("chain-step-source_bronzed")).toBeInTheDocument();
  });

  it("each step shows seq + summary + copy button", () => {
    render(<DecisionChainView chain={fullChain} />);
    expect(screen.getByText("seq#100")).toBeInTheDocument();
    expect(screen.getByText("seq#75")).toBeInTheDocument();
    expect(
      screen.getByTestId("chain-summary-decision_recorded").textContent,
    ).toContain("Push Q3 close to Friday");
    expect(screen.getByTestId("chain-copy-decision_recorded")).toBeInTheDocument();
    expect(screen.getByTestId("chain-copy-source_bronzed")).toBeInTheDocument();
  });

  it("renders deep-links for each step (open + filter /trace)", () => {
    render(<DecisionChainView chain={fullChain} />);
    expect(
      screen.getByTestId("chain-link-decision_recorded").getAttribute("href"),
    ).toBe("/decisions");
    expect(
      screen.getByTestId("chain-trace-source_bronzed").getAttribute("href"),
    ).toBe("/trace?kind=source_bronzed");
  });

  it("flags rows as resolved via data-resolved", () => {
    const { container } = render(<DecisionChainView chain={fullChain} />);
    const rows = container.querySelectorAll(
      "[data-testid^='chain-row-']",
    );
    expect(rows.length).toBe(5);
    rows.forEach((row) => {
      expect(row.getAttribute("data-resolved")).toBe("true");
    });
  });
});

describe("DecisionChainView · platform badge (W4-B)", () => {
  it("badges the decision step with Slack when channel_id is C-prefixed", () => {
    render(<DecisionChainView chain={fullChain} />);
    const badge = screen.getByTestId("chain-platform-decision_recorded");
    expect(badge).toBeInTheDocument();
    expect(badge.getAttribute("data-platform")).toBe("slack");
  });

  it("badges with WhatsApp when payload carries platform=whatsapp explicitly", () => {
    const whatsappChain: DecisionChain = {
      ...fullChain,
      decision: {
        ...fullChain.decision!,
        payload: {
          decision_id: "dec-wa",
          channel_id: "5215555550000@s.whatsapp.net",
          platform: "whatsapp",
        },
      },
    };
    render(<DecisionChainView chain={whatsappChain} />);
    const badge = screen.getByTestId("chain-platform-decision_recorded");
    expect(badge.getAttribute("data-platform")).toBe("whatsapp");
    expect(badge.getAttribute("data-platform-status")).toBe("preview");
  });

  it("renders no badge for legacy entries without platform or channel_id", () => {
    const legacyChain: DecisionChain = {
      ...fullChain,
      decision: {
        ...fullChain.decision!,
        // Legacy pre-provenance entry — no platform, no channel_id.
        payload: { decision_id: "dec-legacy" },
      },
    };
    render(<DecisionChainView chain={legacyChain} />);
    expect(
      screen.queryByTestId("chain-platform-decision_recorded"),
    ).toBeNull();
  });

  it("renders no badge on data-bronze steps that have no channel context", () => {
    // The source_bronzed step is data bronze (file-source bytes), not
    // chat bronze — its payload has source_id + bytes + rows but no
    // channel/platform. The badge must stay silent rather than fabricate.
    render(<DecisionChainView chain={fullChain} />);
    expect(screen.queryByTestId("chain-platform-source_bronzed")).toBeNull();
  });
});

describe("DecisionChainView · partial chain", () => {
  it("renders the missing-step pill when an intermediate step is absent", () => {
    const partial: DecisionChain = {
      ...fullChain,
      processMap: null,
      missing: ["process_map_proposed"],
    };
    render(<DecisionChainView chain={partial} />);
    expect(
      screen.getByTestId("chain-step-missing-process_map_proposed"),
    ).toBeInTheDocument();
    // Resolved row should still surround the missing one
    expect(
      screen.getByTestId("chain-row-process_map_proposed").getAttribute(
        "data-resolved",
      ),
    ).toBe("false");
    expect(
      screen.getByTestId("chain-row-decision_recorded").getAttribute(
        "data-resolved",
      ),
    ).toBe("true");
  });

  it("annotates inferred steps with 'inferred link'", () => {
    const inferredChain: DecisionChain = {
      ...fullChain,
      kpi: { ...fullChain.kpi!, inferred: true },
    };
    render(<DecisionChainView chain={inferredChain} />);
    const header = screen
      .getByTestId("chain-step-kpi_node")
      .querySelector("header");
    expect(header?.textContent ?? "").toMatch(/inferred link/i);
  });
});

describe("DecisionChainView · copy-to-clipboard", () => {
  it("copies the full hash on click and surfaces the 'copied' confirmation", async () => {
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    render(<DecisionChainView chain={fullChain} />);
    const btn = screen.getByTestId("chain-copy-decision_recorded");
    await act(async () => {
      fireEvent.click(btn);
    });

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(
        "decisionhash00000000000000000000",
      );
    });
    expect(btn.getAttribute("data-state")).toBe("copied");
    expect(btn.textContent ?? "").toContain("copied");
  });

  it("renders a shortened hash on the button face by default", () => {
    render(<DecisionChainView chain={fullChain} />);
    const btn = screen.getByTestId("chain-copy-source_proposed");
    expect(btn.textContent ?? "").toMatch(/^#sourcehash00/);
    expect(btn.getAttribute("title") ?? "").toContain(
      "sourcehash0000000000000000000000",
    );
  });
});
