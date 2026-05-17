/**
 * PageErrorBoundary — catches render errors inside a tab and surfaces an
 * honest "we couldn't load this — try again" panel (W3.A14).
 *
 * Tests:
 *   - happy path: renders children when no error fires
 *   - error path: catches the throw and renders the editorial surface
 *   - retry: clicking "Try again" remounts the children with a fresh key
 *   - /trace deep link is rendered with the configured query
 *   - surface label drives the headline copy
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
    [k: string]: unknown;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { PageErrorBoundary } from "../PageErrorBoundary";

function Bomb({ shouldThrow }: { shouldThrow: boolean }): React.ReactElement {
  if (shouldThrow) {
    throw new Error("kaboom: ledger fetch failed");
  }
  return <p data-testid="bomb-ok">ok</p>;
}

beforeEach(() => {
  // Silence the React error log for the throw path; the boundary itself
  // logs to console.error too, which we don't want to assert on.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

describe("PageErrorBoundary", () => {
  it("renders children when no error fires", () => {
    render(
      <PageErrorBoundary>
        <Bomb shouldThrow={false} />
      </PageErrorBoundary>,
    );
    expect(screen.getByTestId("bomb-ok")).toBeInTheDocument();
    expect(screen.queryByTestId("page-error-boundary")).toBeNull();
  });

  it("renders the editorial surface when a child throws", () => {
    render(
      <PageErrorBoundary surface="sources">
        <Bomb shouldThrow={true} />
      </PageErrorBoundary>,
    );
    expect(screen.getByTestId("page-error-boundary")).toBeInTheDocument();
    expect(screen.getByText(/We couldn't load sources/)).toBeInTheDocument();
    expect(screen.getByTestId("page-error-detail")).toHaveTextContent(
      "kaboom: ledger fetch failed",
    );
  });

  it("uses generic copy when no surface is provided", () => {
    render(
      <PageErrorBoundary>
        <Bomb shouldThrow={true} />
      </PageErrorBoundary>,
    );
    expect(
      screen.getByText(/We couldn't load this surface/),
    ).toBeInTheDocument();
  });

  it("renders the /trace deep link with the configured query", () => {
    render(
      <PageErrorBoundary traceQuery="?kind=error&surface=sources">
        <Bomb shouldThrow={true} />
      </PageErrorBoundary>,
    );
    const link = screen.getByTestId("page-error-trace-link") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/trace?kind=error&surface=sources");
  });

  it("renders a default /trace link when no query is given", () => {
    render(
      <PageErrorBoundary>
        <Bomb shouldThrow={true} />
      </PageErrorBoundary>,
    );
    const link = screen.getByTestId("page-error-trace-link") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/trace");
  });

  it("retry clears the error and remounts the children", () => {
    let shouldThrow = true;
    function Conditional(): React.ReactElement {
      if (shouldThrow) {
        throw new Error("first failure");
      }
      return <p data-testid="recovered">recovered</p>;
    }
    render(
      <PageErrorBoundary>
        <Conditional />
      </PageErrorBoundary>,
    );
    expect(screen.getByTestId("page-error-boundary")).toBeInTheDocument();
    // Flip the bomb off, then click retry — boundary state resets and the
    // children re-render successfully.
    shouldThrow = false;
    fireEvent.click(screen.getByTestId("page-error-retry"));
    expect(screen.getByTestId("recovered")).toBeInTheDocument();
    expect(screen.queryByTestId("page-error-boundary")).toBeNull();
  });

  it("respects a custom testId", () => {
    render(
      <PageErrorBoundary testId="custom-error">
        <Bomb shouldThrow={true} />
      </PageErrorBoundary>,
    );
    expect(screen.getByTestId("custom-error")).toBeInTheDocument();
  });
});
