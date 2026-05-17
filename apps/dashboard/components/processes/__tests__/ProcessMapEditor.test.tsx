/**
 * ProcessMapEditor — opens on trigger; validates required fields;
 * supports add/remove step; POSTs to /api/v1/processes; closes on
 * success (W2.A7).
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

import { ProcessMapEditor } from "../ProcessMapEditor";

beforeEach(() => {
  refreshMock.mockReset();
  vi.unstubAllGlobals();
});

function stubFetch(
  impl: (url: string, init?: RequestInit) => Promise<Response>,
) {
  vi.stubGlobal("fetch", vi.fn(impl) as unknown as typeof fetch);
}

describe("ProcessMapEditor", () => {
  it("opens the modal when the trigger is clicked", () => {
    render(<ProcessMapEditor />);
    expect(screen.queryByTestId("process-editor-modal")).toBeNull();
    fireEvent.click(screen.getByTestId("process-editor-open"));
    expect(screen.getByTestId("process-editor-modal")).toBeInTheDocument();
  });

  it("starts with two empty step rows and supports add", () => {
    render(<ProcessMapEditor />);
    fireEvent.click(screen.getByTestId("process-editor-open"));
    expect(screen.getByTestId("process-editor-step-0")).toBeInTheDocument();
    expect(screen.getByTestId("process-editor-step-1")).toBeInTheDocument();
    expect(screen.queryByTestId("process-editor-step-2")).toBeNull();
    fireEvent.click(screen.getByTestId("process-editor-add-step"));
    expect(screen.getByTestId("process-editor-step-2")).toBeInTheDocument();
  });

  it("validates process name is required", async () => {
    stubFetch(async () =>
      new Response(JSON.stringify({ ok: true }), { status: 201 }),
    );
    render(<ProcessMapEditor />);
    fireEvent.click(screen.getByTestId("process-editor-open"));
    fireEvent.change(screen.getByTestId("process-editor-actor-0"), {
      target: { value: "Bob" },
    });
    fireEvent.change(screen.getByTestId("process-editor-action-0"), {
      target: { value: "exports" },
    });
    fireEvent.change(screen.getByTestId("process-editor-actor-1"), {
      target: { value: "Alice" },
    });
    fireEvent.change(screen.getByTestId("process-editor-action-1"), {
      target: { value: "reviews" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("process-editor-submit"));
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("process-editor-error").textContent,
      ).toContain("process name");
    });
  });

  it("requires at least two complete steps", async () => {
    stubFetch(async () =>
      new Response(JSON.stringify({ ok: true }), { status: 201 }),
    );
    render(<ProcessMapEditor />);
    fireEvent.click(screen.getByTestId("process-editor-open"));
    fireEvent.change(screen.getByTestId("process-editor-name"), {
      target: { value: "Q3 close" },
    });
    // Only fill step 0; step 1 stays empty.
    fireEvent.change(screen.getByTestId("process-editor-actor-0"), {
      target: { value: "Bob" },
    });
    fireEvent.change(screen.getByTestId("process-editor-action-0"), {
      target: { value: "exports" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("process-editor-submit"));
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("process-editor-error").textContent,
      ).toContain("two complete steps");
    });
  });

  it("posts to /api/v1/processes with the canonical body and closes", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    stubFetch(async (url, init) => {
      calls.push({ url, init });
      return new Response(
        JSON.stringify({ process_id: "proc_1", entry_ids: [] }),
        { status: 201 },
      );
    });
    render(<ProcessMapEditor />);
    fireEvent.click(screen.getByTestId("process-editor-open"));
    fireEvent.change(screen.getByTestId("process-editor-name"), {
      target: { value: "Q3 close" },
    });
    fireEvent.change(screen.getByTestId("process-editor-domain"), {
      target: { value: "finance" },
    });
    fireEvent.change(screen.getByTestId("process-editor-actor-0"), {
      target: { value: "Bob" },
    });
    fireEvent.change(screen.getByTestId("process-editor-action-0"), {
      target: { value: "exports" },
    });
    fireEvent.change(screen.getByTestId("process-editor-actor-1"), {
      target: { value: "Alice" },
    });
    fireEvent.change(screen.getByTestId("process-editor-action-1"), {
      target: { value: "reviews" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("process-editor-submit"));
    });

    await waitFor(() => {
      const post = calls.find((c) => c.init?.method === "POST");
      expect(post).toBeTruthy();
      expect(post!.url).toBe("/api/v1/processes");
      const body = JSON.parse(String(post!.init!.body));
      expect(body.process_name).toBe("Q3 close");
      expect(body.domain).toBe("finance");
      expect(body.steps).toHaveLength(2);
      expect(body.steps[0].order).toBe(1);
      expect(body.steps[0].actor).toBe("Bob");
      expect(body.steps[0].action).toBe("exports");
      expect(body.steps[1].order).toBe(2);
    });

    await waitFor(() => {
      expect(screen.queryByTestId("process-editor-modal")).toBeNull();
    });
    expect(refreshMock).toHaveBeenCalled();
  });
});
