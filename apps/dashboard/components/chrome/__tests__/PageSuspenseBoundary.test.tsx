/**
 * PageSuspenseBoundary — wraps children in `<Suspense>` with the editorial
 * PageSkeleton fallback (W3.A14).
 *
 * Tests:
 *   - default fallback is the PageSkeleton (operator never sees blank)
 *   - custom fallback overrides the default
 *   - synchronous children render without showing the fallback
 *   - suspending children show the fallback until they resolve
 *
 * We use the classic React 18 Suspense throw-a-promise pattern (compatible
 * with the dashboard's React 18.3.1 dep — `use()` lands in 19).
 */
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { Suspense } from "react";

import { PageSuspenseBoundary } from "../PageSuspenseBoundary";

afterEach(() => {
  cleanup();
});

interface ResourceController<T> {
  read(): T;
  resolve(value: T): void;
}

function makeResource<T>(): ResourceController<T> {
  let status: "pending" | "resolved" | "rejected" = "pending";
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

describe("PageSuspenseBoundary", () => {
  it("renders synchronous children directly", () => {
    render(
      <PageSuspenseBoundary>
        <p>direct content</p>
      </PageSuspenseBoundary>,
    );
    expect(screen.getByText("direct content")).toBeInTheDocument();
    expect(screen.queryByTestId("page-skeleton")).toBeNull();
  });

  it("uses PageSkeleton as default fallback when children suspend", async () => {
    const r = makeResource<string>();
    function Suspending() {
      const value = r.read();
      return <p>{value}</p>;
    }

    render(
      <PageSuspenseBoundary>
        <Suspending />
      </PageSuspenseBoundary>,
    );
    expect(screen.getByTestId("page-skeleton")).toBeInTheDocument();
    r.resolve("resolved");
    await waitFor(() => {
      expect(screen.getByText("resolved")).toBeInTheDocument();
    });
  });

  it("respects a custom fallback element", () => {
    const r = makeResource<string>();
    function Suspending() {
      return <p>{r.read()}</p>;
    }
    render(
      <PageSuspenseBoundary fallback={<p data-testid="custom-fb">wait</p>}>
        <Suspending />
      </PageSuspenseBoundary>,
    );
    expect(screen.getByTestId("custom-fb")).toBeInTheDocument();
    expect(screen.queryByTestId("page-skeleton")).toBeNull();
  });

  it("forwards skeletonProps to the default fallback", () => {
    const r = makeResource<string>();
    function Suspending() {
      return <p>{r.read()}</p>;
    }
    render(
      <PageSuspenseBoundary skeletonProps={{ eyebrow: "loading sources" }}>
        <Suspending />
      </PageSuspenseBoundary>,
    );
    expect(screen.getByText("loading sources")).toBeInTheDocument();
  });

  it("nests Suspense correctly for parent boundaries", async () => {
    const r = makeResource<string>();
    function Suspending() {
      return <p>{r.read()}</p>;
    }
    render(
      <Suspense fallback={<p>parent fallback</p>}>
        <PageSuspenseBoundary>
          <Suspending />
        </PageSuspenseBoundary>
      </Suspense>,
    );
    // Inner boundary catches the suspense first
    expect(screen.getByTestId("page-skeleton")).toBeInTheDocument();
    expect(screen.queryByText("parent fallback")).toBeNull();
    r.resolve("done");
    await waitFor(() => {
      expect(screen.getByText("done")).toBeInTheDocument();
    });
  });
});
