/**
 * PostgresHealthCard — three-state render contract (W2.A10).
 *
 * Acceptance: Postgres-down state renders an honest red banner. The card
 * exposes `data-postgres-down` so e2e tests can assert the banner state
 * without scraping styles.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { PostgresHealthCard } from "../PostgresHealthCard";

describe("PostgresHealthCard", () => {
  it("renders the green ok state with latency + version", () => {
    render(
      <PostgresHealthCard
        health={{
          status: "ok",
          latencyMs: 4.2,
          message: "SELECT 1 returned within the timeout.",
          version: "PostgreSQL 16.2",
        }}
      />,
    );
    const card = screen.getByTestId("ops-postgres-health");
    expect(card.getAttribute("data-status")).toBe("ok");
    expect(card.getAttribute("data-postgres-down")).toBe("false");
    expect(screen.getByText(/Postgres is healthy/i)).toBeInTheDocument();
    expect(screen.getByText(/PostgreSQL 16.2/)).toBeInTheDocument();
    expect(screen.getByText(/4.2 ms/)).toBeInTheDocument();
  });

  it("renders the red down banner when status === down", () => {
    render(
      <PostgresHealthCard
        health={{
          status: "down",
          latencyMs: null,
          message: "OperationalError: could not connect to server",
          version: null,
        }}
      />,
    );
    const card = screen.getByTestId("ops-postgres-health");
    expect(card.getAttribute("data-status")).toBe("down");
    expect(card.getAttribute("data-postgres-down")).toBe("true");
    expect(screen.getByText(/Postgres is unreachable/i)).toBeInTheDocument();
    expect(
      screen.getByText(/could not connect to server/i),
    ).toBeInTheDocument();
  });

  it("renders the degraded amber state with the supplied message", () => {
    render(
      <PostgresHealthCard
        health={{
          status: "degraded",
          latencyMs: 1820,
          message: "Probe latency above threshold.",
          version: "PostgreSQL 16",
        }}
      />,
    );
    const card = screen.getByTestId("ops-postgres-health");
    expect(card.getAttribute("data-status")).toBe("degraded");
    expect(card.getAttribute("data-postgres-down")).toBe("false");
    expect(screen.getByText(/Postgres is degraded/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Probe latency above threshold/i),
    ).toBeInTheDocument();
  });
});
