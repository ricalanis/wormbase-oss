/**
 * DataProductSections — three sections inside PersonDetailDrawer (F5).
 *
 * Mocks the three GET calls and asserts that requested / consumed / authored
 * sections each render a row.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import { DataProductSections } from "../../components/people/DataProductSections";

const PERSON_ID = "11111111-1111-1111-1111-111111111111";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("DataProductSections", () => {
  it("renders three section headings", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ dataProducts: [] }))
      .mockResolvedValueOnce(jsonResponse({ consumption: [] }))
      .mockResolvedValueOnce(jsonResponse({ notebooks: [] }));
    render(<DataProductSections personId={PERSON_ID} />);
    await waitFor(() => {
      expect(
        screen.getByText("Data products requested"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText("Data products consumed")).toBeInTheDocument();
    expect(screen.getByText("Notebooks authored")).toBeInTheDocument();
  });

  it("renders rows when fetches resolve with data", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          dataProducts: [
            {
              dataProductId: "dp1",
              tenantId: "t",
              name: "Q3 Net Revenue",
              kind: "report",
              status: "generated",
              requestedByPersonId: PERSON_ID,
              domainId: null,
              generatedAt: null,
              contentHash: null,
              contentsUri: null,
              receipt: { hash: "h", source: "s", owner: "o", classification: "internal" },
            },
          ],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          consumption: [
            {
              consumptionId: "c1",
              dataProductId: "dp1",
              tenantId: "t",
              personId: PERSON_ID,
              surface: "dashboard",
              channel: null,
              ts: "2026-04-26T10:00:00Z",
            },
          ],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          notebooks: [
            {
              notebookId: "nb1",
              tenantId: "t",
              name: "CFO autoresearch",
              kernel: "python_local",
              status: "published",
              ownerPersonId: PERSON_ID,
              domainId: null,
              latestRunId: null,
              latestPublishedRunId: null,
              version: "1",
              cells: [],
              receipt: { hash: "h", source: "s", owner: "o", classification: "internal" },
            },
          ],
        }),
      );
    render(<DataProductSections personId={PERSON_ID} />);
    await waitFor(() => {
      expect(screen.getByText("Q3 Net Revenue")).toBeInTheDocument();
    });
    expect(screen.getByText("CFO autoresearch")).toBeInTheDocument();
    // Consumption row carries the truncated id
    expect(screen.getByText(/dp1/)).toBeInTheDocument();
  });
});
