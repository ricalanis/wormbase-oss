/**
 * DecisionDetailDrawer — inspect mode renders all fields; record mode
 * validates + POSTs; close handler fires on scrim click (W2.A7).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock, push: vi.fn() }),
}));

import { DecisionDetailDrawer } from "../DecisionDetailDrawer";
import type { DecisionRow } from "../../../lib/ledger-client.types";

beforeEach(() => {
  refreshMock.mockReset();
  vi.unstubAllGlobals();
});

function stubFetch(
  impl: (url: string, init?: RequestInit) => Promise<Response>,
) {
  vi.stubGlobal("fetch", vi.fn(impl) as unknown as typeof fetch);
}

const sampleDecision: DecisionRow = {
  decisionId: "dec_1",
  decisionText: "We decided to push Q3 close to Friday.",
  decisionAt: "2026-04-25T13:00:00Z",
  channelId: "C0FINANCE",
  decidedByPersons: ["p_alice", "p_bob"],
  evidenceMessageIds: ["msg_111", "msg_222"],
  confidence: 0.92,
  receipt: {
    hash: "abc123",
    source: "channel:C0FINANCE",
    owner: "finance",
    classification: "internal",
  },
};

describe("DecisionDetailDrawer · inspect", () => {
  it("renders nothing when open is false", () => {
    render(
      <DecisionDetailDrawer
        decision={sampleDecision}
        open={false}
        mode="inspect"
        onClose={() => undefined}
      />,
    );
    expect(screen.queryByTestId("decision-detail-drawer")).toBeNull();
  });

  it("renders the decision text, channel, deciders, and evidence ids", () => {
    render(
      <DecisionDetailDrawer
        decision={sampleDecision}
        open
        mode="inspect"
        onClose={() => undefined}
      />,
    );
    expect(screen.getByTestId("decision-detail-drawer")).toBeInTheDocument();
    expect(screen.getByTestId("decision-drawer-title").textContent).toContain(
      "Q3 close",
    );
    expect(screen.getByTestId("decision-deciders").children.length).toBe(2);
    expect(screen.getByTestId("decision-evidence-list").children.length).toBe(
      2,
    );
  });

  it("calls onClose when the scrim is clicked", () => {
    const onClose = vi.fn();
    render(
      <DecisionDetailDrawer
        decision={sampleDecision}
        open
        mode="inspect"
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByTestId("decision-drawer-scrim"));
    expect(onClose).toHaveBeenCalled();
  });
});

describe("DecisionDetailDrawer · record", () => {
  it("validates decision_text is required", async () => {
    stubFetch(async () =>
      new Response(JSON.stringify({ ok: true }), { status: 201 }),
    );
    render(
      <DecisionDetailDrawer
        decision={null}
        open
        mode="record"
        onClose={() => undefined}
      />,
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("decision-record-submit"));
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("decision-record-error").textContent,
      ).toContain("decision_text");
    });
  });

  it("posts to /api/v1/decisions and closes on success", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    stubFetch(async (url, init) => {
      calls.push({ url, init });
      return new Response(
        JSON.stringify({ decision_id: "dec_new", entry_ids: [] }),
        { status: 201 },
      );
    });
    const onClose = vi.fn();
    render(
      <DecisionDetailDrawer
        decision={null}
        open
        mode="record"
        onClose={onClose}
      />,
    );
    fireEvent.change(screen.getByTestId("decision-record-text"), {
      target: { value: "Approved: ship the migration on Tuesday." },
    });
    fireEvent.change(screen.getByTestId("decision-record-channel"), {
      target: { value: "C0OPS" },
    });
    fireEvent.change(screen.getByTestId("decision-record-evidence"), {
      target: { value: "msg-1, msg-2" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("decision-record-submit"));
    });

    await waitFor(() => {
      const post = calls.find((c) => c.init?.method === "POST");
      expect(post).toBeTruthy();
      expect(post!.url).toBe("/api/v1/decisions");
      const body = JSON.parse(String(post!.init!.body));
      expect(body.decision_text).toBe(
        "Approved: ship the migration on Tuesday.",
      );
      expect(body.channel_id).toBe("C0OPS");
      expect(body.evidence_message_ids).toEqual(["msg-1", "msg-2"]);
    });

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(refreshMock).toHaveBeenCalled();
  });
});
