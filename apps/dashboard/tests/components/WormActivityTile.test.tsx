/**
 * WS5 S1 — WormActivityTile.
 *
 * Two paths:
 *   - empty (total=0)        → renders the honest "Nothing yet" message
 *   - populated (total>0)    → renders one counter per non-zero family,
 *                              each linking to /activity?filter=<family>
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { WormActivityTile } from "../../components/dashboard/WormActivityTile";
import type { WormActivitySummary } from "../../lib/ledger-client";

const EMPTY: WormActivitySummary = {
  sinceTs: null,
  total: 0,
  byFamily: {
    chat: 0,
    files: 0,
    kpis: 0,
    decisions: 0,
    sources: 0,
    proactivity: 0,
    artifacts: 0,
    drift: 0,
    experiments: 0,
    recurring_questions: 0,
    position_proposals: 0,
    topics: 0,
  },
};

const POPULATED: WormActivitySummary = {
  sinceTs: "2026-04-25T10:00:00Z",
  total: 12,
  byFamily: {
    chat: 8,
    files: 1,
    kpis: 2,
    decisions: 1,
    sources: 0,
    proactivity: 0,
    artifacts: 0,
    drift: 0,
    experiments: 0,
    recurring_questions: 0,
    position_proposals: 0,
    topics: 0,
  },
};

const POPULATED_PHASE3: WormActivitySummary = {
  sinceTs: "2026-04-30T08:00:00Z",
  total: 13,
  byFamily: {
    chat: 0,
    files: 0,
    kpis: 0,
    decisions: 0,
    sources: 0,
    proactivity: 0,
    artifacts: 2,
    drift: 3,
    experiments: 4,
    recurring_questions: 1,
    position_proposals: 2,
    topics: 1,
  },
};

describe("WormActivityTile (WS5 S1)", () => {
  it("renders the honest empty state when total = 0", () => {
    render(<WormActivityTile summary={EMPTY} />);
    const tile = screen.getByTestId("worm-activity-tile");
    expect(tile.getAttribute("data-state")).toBe("empty");
    expect(screen.getByText(/Nothing yet/)).toBeTruthy();
    expect(screen.getByText(/team starts chatting/)).toBeTruthy();
  });

  it("renders one counter per non-zero family, with route to /activity?filter=", () => {
    render(<WormActivityTile summary={POPULATED} />);
    const tile = screen.getByTestId("worm-activity-tile");
    expect(tile.getAttribute("data-state")).toBe("populated");
    // Non-zero families render.
    expect(screen.getByTestId("worm-activity-family-chat")).toBeTruthy();
    expect(screen.getByTestId("worm-activity-family-files")).toBeTruthy();
    expect(screen.getByTestId("worm-activity-family-kpis")).toBeTruthy();
    expect(screen.getByTestId("worm-activity-family-decisions")).toBeTruthy();
    // Zero families do NOT render.
    expect(screen.queryByTestId("worm-activity-family-sources")).toBeNull();
    expect(screen.queryByTestId("worm-activity-family-proactivity")).toBeNull();
    expect(screen.queryByTestId("worm-activity-family-artifacts")).toBeNull();
  });

  it("each non-zero counter links to /activity?filter=<family>", () => {
    render(<WormActivityTile summary={POPULATED} />);
    const chatLink = screen.getByTestId("worm-activity-link-chat") as HTMLAnchorElement;
    expect(chatLink.tagName.toLowerCase()).toBe("a");
    expect(chatLink.getAttribute("href")).toBe("/activity?filter=chat");
    const filesLink = screen.getByTestId("worm-activity-link-files") as HTMLAnchorElement;
    expect(filesLink.getAttribute("href")).toBe("/activity?filter=files");
    const kpisLink = screen.getByTestId("worm-activity-link-kpis") as HTMLAnchorElement;
    expect(kpisLink.getAttribute("href")).toBe("/activity?filter=kpis");
  });

  it("renders the count text for each non-zero family", () => {
    render(<WormActivityTile summary={POPULATED} />);
    const chat = screen.getByTestId("worm-activity-family-chat");
    expect(chat.textContent).toContain("8");
    expect(chat.textContent).toContain("messages");
    const files = screen.getByTestId("worm-activity-family-files");
    expect(files.textContent).toContain("1");
    expect(files.textContent).toContain("files");
  });

  it("shows the total count in the headline", () => {
    render(<WormActivityTile summary={POPULATED} />);
    expect(screen.getByText(/did 12 things/)).toBeTruthy();
  });

  it("uses singular phrasing when total = 1", () => {
    render(
      <WormActivityTile
        summary={{
          ...EMPTY,
          total: 1,
          byFamily: { ...EMPTY.byFamily, chat: 1 },
        }}
      />,
    );
    expect(screen.getByText(/did 1 thing(?!s)/)).toBeTruthy();
  });

  it("formats sinceTs as compact UTC", () => {
    render(<WormActivityTile summary={POPULATED} />);
    // 2026-04-25T10:00:00Z → "since 2026-04-25 10:00Z"
    const tile = screen.getByTestId("worm-activity-tile");
    expect(tile.textContent).toContain("2026-04-25 10:00Z");
  });

  // ── Phase 3 Task 3A — "since you logged off" digest ────────────────────
  // Five new families surface gold-artifact-producing worm activity that the
  // P2.1 validation gap audit (2026-04-27) flagged as missing from the
  // first-daily-moment-of-value tile: lake-maintainer drift signals,
  // research-loop experiment resolutions, process-extractor recurring
  // questions, identity-tracker position proposals, and topic clusters.
  describe("Phase 3 — Phase 3A digest categories", () => {
    it("renders all five new families when each has activity", () => {
      render(<WormActivityTile summary={POPULATED_PHASE3} />);
      const tile = screen.getByTestId("worm-activity-tile");
      expect(tile.getAttribute("data-state")).toBe("populated");
      expect(screen.getByTestId("worm-activity-family-drift")).toBeTruthy();
      expect(screen.getByTestId("worm-activity-family-experiments")).toBeTruthy();
      expect(
        screen.getByTestId("worm-activity-family-recurring_questions"),
      ).toBeTruthy();
      expect(
        screen.getByTestId("worm-activity-family-position_proposals"),
      ).toBeTruthy();
      expect(screen.getByTestId("worm-activity-family-topics")).toBeTruthy();
    });

    it("position_proposals routes to /people/proposals (per spec deep-link)", () => {
      render(<WormActivityTile summary={POPULATED_PHASE3} />);
      const link = screen.getByTestId(
        "worm-activity-link-position_proposals",
      ) as HTMLAnchorElement;
      expect(link.getAttribute("href")).toBe("/people/proposals");
    });

    it("drift routes to /sources?filter=drift (lake-maintainer surface)", () => {
      render(<WormActivityTile summary={POPULATED_PHASE3} />);
      const link = screen.getByTestId(
        "worm-activity-link-drift",
      ) as HTMLAnchorElement;
      expect(link.getAttribute("href")).toBe("/sources?filter=drift");
    });

    it("experiments routes to /research (research-worm surface)", () => {
      render(<WormActivityTile summary={POPULATED_PHASE3} />);
      const link = screen.getByTestId(
        "worm-activity-link-experiments",
      ) as HTMLAnchorElement;
      expect(link.getAttribute("href")).toBe("/research");
    });

    it("recurring_questions routes to /processes (process-worm surface)", () => {
      render(<WormActivityTile summary={POPULATED_PHASE3} />);
      const link = screen.getByTestId(
        "worm-activity-link-recurring_questions",
      ) as HTMLAnchorElement;
      expect(link.getAttribute("href")).toBe("/processes");
    });

    it("topics routes to /topics (just shipped Phase 2B)", () => {
      render(<WormActivityTile summary={POPULATED_PHASE3} />);
      const link = screen.getByTestId(
        "worm-activity-link-topics",
      ) as HTMLAnchorElement;
      expect(link.getAttribute("href")).toBe("/topics");
    });

    it("renders the count text with intent-conveying labels", () => {
      render(<WormActivityTile summary={POPULATED_PHASE3} />);
      const drift = screen.getByTestId("worm-activity-family-drift");
      expect(drift.textContent).toContain("3");
      expect(drift.textContent?.toLowerCase()).toContain("drift");
      const exp = screen.getByTestId("worm-activity-family-experiments");
      expect(exp.textContent).toContain("4");
      expect(exp.textContent?.toLowerCase()).toContain("experiment");
      const pp = screen.getByTestId("worm-activity-family-position_proposals");
      expect(pp.textContent).toContain("2");
      expect(pp.textContent?.toLowerCase()).toContain("position");
    });

    it("zero-counts collapse for new families just like legacy ones", () => {
      render(<WormActivityTile summary={POPULATED} />);
      // POPULATED has the legacy four; the new five should not render.
      expect(screen.queryByTestId("worm-activity-family-drift")).toBeNull();
      expect(
        screen.queryByTestId("worm-activity-family-experiments"),
      ).toBeNull();
      expect(
        screen.queryByTestId("worm-activity-family-recurring_questions"),
      ).toBeNull();
      expect(
        screen.queryByTestId("worm-activity-family-position_proposals"),
      ).toBeNull();
      expect(screen.queryByTestId("worm-activity-family-topics")).toBeNull();
    });
  });
});
