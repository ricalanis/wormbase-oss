/**
 * ProposeKpiModal — opens on trigger; validates label is required;
 * POSTs to /api/v1/kpis/propose; closes on success; surfaces server
 * error on 4xx/5xx (W2.A7).
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

import { ProposeKpiModal } from "../ProposeKpiModal";

beforeEach(() => {
  refreshMock.mockReset();
  vi.unstubAllGlobals();
});

function stubFetch(
  impl: (url: string, init?: RequestInit) => Promise<Response>,
) {
  vi.stubGlobal("fetch", vi.fn(impl) as unknown as typeof fetch);
}

describe("ProposeKpiModal", () => {
  it("opens the modal when the trigger button is clicked", () => {
    render(<ProposeKpiModal />);
    expect(screen.queryByTestId("propose-kpi-modal")).toBeNull();
    fireEvent.click(screen.getByTestId("propose-kpi-open"));
    expect(screen.getByTestId("propose-kpi-modal")).toBeInTheDocument();
  });

  it("validates label is required", async () => {
    stubFetch(async () =>
      new Response(JSON.stringify({ ok: true }), { status: 201 }),
    );
    render(<ProposeKpiModal />);
    fireEvent.click(screen.getByTestId("propose-kpi-open"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("propose-kpi-submit"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("propose-kpi-error").textContent).toContain(
        "label",
      );
    });
  });

  it("posts to /api/v1/kpis/propose with the canonical body and closes", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    stubFetch(async (url, init) => {
      calls.push({ url, init });
      return new Response(
        JSON.stringify({ kpi_id: "kpi_1", entry_ids: [] }),
        { status: 201 },
      );
    });
    render(<ProposeKpiModal />);
    fireEvent.click(screen.getByTestId("propose-kpi-open"));
    fireEvent.change(screen.getByTestId("propose-kpi-label"), {
      target: { value: "Q3 net revenue" },
    });
    fireEvent.change(screen.getByTestId("propose-kpi-formula"), {
      target: { value: "sum(revenue)" },
    });
    fireEvent.change(screen.getByTestId("propose-kpi-unit"), {
      target: { value: "currency_usd" },
    });
    fireEvent.change(screen.getByTestId("propose-kpi-owner-position"), {
      target: { value: "CFO" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("propose-kpi-submit"));
    });

    await waitFor(() => {
      const post = calls.find((c) => c.init?.method === "POST");
      expect(post).toBeTruthy();
      expect(post!.url).toBe("/api/v1/kpis/propose");
      const body = JSON.parse(String(post!.init!.body));
      expect(body.label).toBe("Q3 net revenue");
      expect(body.formula).toBe("sum(revenue)");
      expect(body.unit).toBe("currency_usd");
      expect(body.owner_position).toBe("CFO");
      expect(body.proposed_by).toBe("dashboard-admin");
    });

    await waitFor(() => {
      expect(screen.queryByTestId("propose-kpi-modal")).toBeNull();
    });
    expect(refreshMock).toHaveBeenCalled();
  });

  it("keeps the modal open and surfaces the server message on 502", async () => {
    stubFetch(async () =>
      new Response(
        JSON.stringify({ error: "worm_core_error", message: "boom" }),
        { status: 502 },
      ),
    );
    render(<ProposeKpiModal />);
    fireEvent.click(screen.getByTestId("propose-kpi-open"));
    fireEvent.change(screen.getByTestId("propose-kpi-label"), {
      target: { value: "Anything" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("propose-kpi-submit"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("propose-kpi-error").textContent).toContain(
        "boom",
      );
    });
    expect(screen.getByTestId("propose-kpi-modal")).toBeInTheDocument();
    expect(refreshMock).not.toHaveBeenCalled();
  });
});
