/**
 * SignNotebookButton — sign + signature receipt UX (W2.A8).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { SignNotebookButton } from "../../components/notebooks/SignNotebookButton";

const NB_ID = "22222222-2222-2222-2222-222222222222";
const RUN_ID = "33333333-3333-3333-3333-333333333333";
const OWNER = "44444444-4444-4444-4444-444444444444";

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SignNotebookButton", () => {
  it("renders the sign CTA with the version in the label", () => {
    render(
      <SignNotebookButton
        notebookId={NB_ID}
        runId={RUN_ID}
        ownerPersonId={OWNER}
        version="2"
        reloadOnSuccess={false}
      />,
    );
    expect(screen.getByTestId("sign-button").textContent).toMatch(
      /Sign as canonical · v2/i,
    );
  });

  it("disables the button when there is no run to sign and surfaces the hint", () => {
    render(
      <SignNotebookButton
        notebookId={NB_ID}
        runId={null}
        ownerPersonId={OWNER}
        reloadOnSuccess={false}
      />,
    );
    const btn = screen.getByTestId("sign-button");
    expect(btn).toBeDisabled();
    expect(screen.getByTestId("sign-needs-run").textContent).toMatch(
      /run the notebook before signing/i,
    );
  });

  it("renders the already-signed state with the existing receipt", () => {
    render(
      <SignNotebookButton
        notebookId={NB_ID}
        runId={RUN_ID}
        ownerPersonId={OWNER}
        version="1"
        alreadySigned
        existingSignatureHash="cafebabe1234567890cafebabe1234567890cafebabe1234567890cafebabe12"
        reloadOnSuccess={false}
      />,
    );
    const btn = screen.getByTestId("sign-button");
    expect(btn).toBeDisabled();
    expect(btn.textContent).toMatch(/Signed · v1/i);
    expect(screen.getByTestId("sign-existing-receipt").textContent).toContain(
      "cafebabe12345678",
    );
  });

  it("posts to /api/v1/notebooks/{id}/sign and surfaces the receipt on success", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        notebook_id: NB_ID,
        signature_receipt: {
          notebook_id: NB_ID,
          run_id: RUN_ID,
          owner_person_id: OWNER,
          version: "1",
          signed_by: "55555555-5555-5555-5555-555555555555",
          signature_hash:
            "deadbeef" + "0".repeat(56),
          entry_ids: ["e1", "e2", "e3", "e4"],
        },
        entry_ids: ["e1", "e2", "e3", "e4"],
      }),
      text: async () => "",
    });
    vi.stubGlobal("fetch", fetchSpy);

    render(
      <SignNotebookButton
        notebookId={NB_ID}
        runId={RUN_ID}
        ownerPersonId={OWNER}
        version="1"
        reloadOnSuccess={false}
      />,
    );
    fireEvent.click(screen.getByTestId("sign-button"));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(1);
    });
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe(`/api/v1/notebooks/${NB_ID}/sign`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toMatchObject({
      run_id: RUN_ID,
      owner_person_id: OWNER,
      version: "1",
    });

    const receipt = await screen.findByTestId("sign-receipt");
    expect(receipt.textContent).toContain("signed");
    expect(receipt.textContent).toContain("deadbeef");
  });

  it("surfaces the error message on a non-2xx response", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ error: "no_session" }),
      text: async () => "no_session",
    });
    vi.stubGlobal("fetch", fetchSpy);

    render(
      <SignNotebookButton
        notebookId={NB_ID}
        runId={RUN_ID}
        ownerPersonId={OWNER}
        reloadOnSuccess={false}
      />,
    );
    fireEvent.click(screen.getByTestId("sign-button"));

    const err = await screen.findByTestId("sign-error");
    expect(err.textContent).toContain("401");
  });
});
