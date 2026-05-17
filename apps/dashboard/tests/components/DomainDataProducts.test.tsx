/**
 * DomainDataProducts — renders cards keyed by domain with freshness badges.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import {
  DomainDataProducts,
  classifyFreshness,
} from "../../components/domains/DomainDataProducts";
import type {
  DataProductRow,
  DomainRow,
} from "../../lib/ledger-client.types";

const DOMAIN_FINANCE: DomainRow = {
  domainId: "d-fin",
  label: "Finance",
  classification: "internal",
  ownerPersonId: "p1",
  owner: "Carol",
  resourceCount: 2,
  receipt: {
    hash: "h",
    source: "ledger",
    owner: "p1",
    classification: "internal",
  },
} as never;

const DOMAIN_PRODUCT: DomainRow = {
  domainId: "d-prod",
  label: "Product",
  classification: "internal",
  ownerPersonId: "p2",
  owner: "Bob",
  resourceCount: 0,
  receipt: {
    hash: "h",
    source: "ledger",
    owner: "p2",
    classification: "internal",
  },
} as never;

function dp(over: Partial<DataProductRow> = {}): DataProductRow {
  return {
    dataProductId: "dp1",
    tenantId: "t",
    name: "Q3 Net Revenue",
    kind: "report",
    status: "generated",
    requestedByPersonId: "p1",
    domainId: "d-fin",
    generatedAt: null,
    contentHash: null,
    contentsUri: null,
    receipt: {
      hash: "h",
      source: "ledger",
      owner: "p1",
      classification: "internal",
    },
    ...over,
  };
}

describe("classifyFreshness", () => {
  it("returns green for <7 days old", () => {
    const oneDayAgo = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
    expect(classifyFreshness(oneDayAgo)).toBe("green");
  });

  it("returns amber for 7-30 days old", () => {
    const fifteenDaysAgo = new Date(
      Date.now() - 15 * 24 * 3600 * 1000,
    ).toISOString();
    expect(classifyFreshness(fifteenDaysAgo)).toBe("amber");
  });

  it("returns red for >30 days old", () => {
    const fiftyDaysAgo = new Date(
      Date.now() - 50 * 24 * 3600 * 1000,
    ).toISOString();
    expect(classifyFreshness(fiftyDaysAgo)).toBe("red");
  });

  it("returns never when generatedAt is null", () => {
    expect(classifyFreshness(null)).toBe("never");
  });
});

describe("DomainDataProducts", () => {
  it("renders one card per domain", () => {
    render(
      <DomainDataProducts
        domains={[DOMAIN_FINANCE, DOMAIN_PRODUCT]}
        dataProducts={[]}
      />,
    );
    expect(
      screen.getByTestId("domain-data-product-card-d-fin"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("domain-data-product-card-d-prod"),
    ).toBeInTheDocument();
  });

  it("groups data products by domain id", () => {
    const products = [
      dp({ dataProductId: "dp-fin-1", name: "Q3", domainId: "d-fin" }),
      dp({ dataProductId: "dp-fin-2", name: "Runway", domainId: "d-fin" }),
      dp({ dataProductId: "dp-prod-1", name: "DAU", domainId: "d-prod" }),
    ];
    render(
      <DomainDataProducts
        domains={[DOMAIN_FINANCE, DOMAIN_PRODUCT]}
        dataProducts={products}
      />,
    );
    const finCard = screen.getByTestId("domain-data-product-card-d-fin");
    expect(finCard).toHaveTextContent("Q3");
    expect(finCard).toHaveTextContent("Runway");
    expect(finCard).not.toHaveTextContent("DAU");
  });

  it("links each row to /data-products/{id}", () => {
    const products = [dp({ dataProductId: "dp-fin-1", name: "Q3" })];
    render(
      <DomainDataProducts
        domains={[DOMAIN_FINANCE]}
        dataProducts={products}
      />,
    );
    const link = screen.getByText("Q3").closest("a");
    expect(link).toHaveAttribute("href", "/data-products/dp-fin-1");
  });

  it("renders the deep-link to /data-products?domain_id=", () => {
    render(
      <DomainDataProducts domains={[DOMAIN_FINANCE]} dataProducts={[]} />,
    );
    const link = screen.getByText(/0 products →/);
    expect(link.closest("a")).toHaveAttribute(
      "href",
      "/data-products?domain_id=d-fin",
    );
  });
});
