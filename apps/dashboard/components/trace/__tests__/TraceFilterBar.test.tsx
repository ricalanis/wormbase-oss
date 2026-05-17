/**
 * TraceFilterBar — URL-encoded filter contract (W2.A10).
 *
 * The filter state lives on the query string so a copy-paste of the URL
 * reproduces the filtered view. We assert that:
 *   - blurring an input pushes a `router.replace` with the new query
 *   - the clear button drops every filter param
 *   - the active-count badge reflects the number of populated params
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { TraceFilterBar } from "../TraceFilterBar";

const replaceMock = vi.fn();
const searchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  usePathname: () => "/trace",
  useSearchParams: () => ({
    get: (k: string) => searchParams.get(k),
    toString: () => searchParams.toString(),
  }),
}));

describe("TraceFilterBar", () => {
  beforeEach(() => {
    replaceMock.mockClear();
    Array.from(searchParams.keys()).forEach((k) => searchParams.delete(k));
  });

  it("publishes the channel filter to the URL on blur", () => {
    render(<TraceFilterBar />);
    const input = screen.getByTestId("trace-filter-channel") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "C0123" } });
    fireEvent.blur(input);
    expect(replaceMock).toHaveBeenCalledTimes(1);
    expect(replaceMock.mock.calls[0][0]).toMatch(/channel_id=C0123/);
  });

  it("publishes the person filter to the URL on blur", () => {
    render(<TraceFilterBar />);
    const input = screen.getByTestId("trace-filter-person") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "p_42" } });
    fireEvent.blur(input);
    expect(replaceMock).toHaveBeenCalledWith(expect.stringMatching(/person_id=p_42/));
  });

  it("the clear button replaces with bare pathname when filters are active", () => {
    searchParams.set("kind", "source_proposed");
    render(<TraceFilterBar />);
    const clear = screen.getByTestId("trace-filter-clear");
    expect(clear).not.toBeDisabled();
    fireEvent.click(clear);
    expect(replaceMock).toHaveBeenCalledWith("/trace");
  });

  it("the clear button is disabled when no filters are set", () => {
    render(<TraceFilterBar />);
    const clear = screen.getByTestId("trace-filter-clear");
    expect(clear).toBeDisabled();
    expect(clear).toHaveTextContent("clear (0)");
  });
});
