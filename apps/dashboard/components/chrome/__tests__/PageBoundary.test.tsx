/**
 * PageBoundary — combines error + suspense boundaries (W3.A14).
 *
 * Tests:
 *   - happy path renders children
 *   - throwing children get caught and the error surface renders
 *   - suspending children show the skeleton fallback
 *   - the error surface honors the surface label
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

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

import { PageBoundary } from "../PageBoundary";

afterEach(() => {
  cleanup();
});

interface ResourceController<T> {
  read(): T;
  resolve(value: T): void;
}

function makeResource<T>(): ResourceController<T> {
  let status: "pending" | "resolved" = "pending";
  let result: T;
  let resolveOuter!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolveOuter = r;
  });
  promise.then((v) => {
    status = "resolved";
    result = v;
  });
  return {
    read() {
      if (status === "pending") throw promise;
      return result;
    },
    resolve(v) {
      resolveOuter(v);
    },
  };
}

describe("PageBoundary", () => {
  it("renders children on the happy path", () => {
    render(
      <PageBoundary surface="people">
        <p>roster ok</p>
      </PageBoundary>,
    );
    expect(screen.getByText("roster ok")).toBeInTheDocument();
  });

  it("catches an error in a child and renders the editorial surface", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    function Bomb(): React.ReactElement {
      throw new Error("boom");
    }
    render(
      <PageBoundary surface="kpis">
        <Bomb />
      </PageBoundary>,
    );
    expect(screen.getByTestId("page-error-boundary")).toBeInTheDocument();
    expect(screen.getByText(/We couldn't load kpis/)).toBeInTheDocument();
  });

  it("shows the skeleton when a child suspends", () => {
    const r = makeResource<string>();
    function Suspending() {
      return <p>{r.read()}</p>;
    }
    render(
      <PageBoundary>
        <Suspending />
      </PageBoundary>,
    );
    expect(screen.getByTestId("page-skeleton")).toBeInTheDocument();
  });
});
