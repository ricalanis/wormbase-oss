/**
 * VoicePanel — graceful-degradation tests (W7.A5).
 *
 * Covers the explicit speech-API failure modes the panel must
 * survive without crashing or silently failing:
 *
 *   - Browser without `SpeechRecognition` constructor (Firefox).
 *   - Factory throws at construction (locked-down HTTPS origin).
 *   - `recognition.start()` throws (transient or post-init block).
 *   - `onerror` event with `service-not-allowed` / `not-allowed`
 *     (HTTPS-tunnel cert/permission issue).
 *   - `onerror` event with any other code (generic failure + retry).
 *
 * In every failure mode the user sees an explicit, on-thesis
 * explanation and the textarea remains fully functional. The textarea
 * is the universal fallback — never disabled by voice state.
 */
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { VoicePanel, type SpeechRecognitionLike } from "../VoicePanel";

class FakeRecognition implements SpeechRecognitionLike {
  continuous = false;
  interimResults = false;
  lang = "";
  onresult: SpeechRecognitionLike["onresult"] = null;
  onerror: SpeechRecognitionLike["onerror"] = null;
  onend: SpeechRecognitionLike["onend"] = null;
  started = false;
  stopped = false;
  /** When set, `start()` throws this error (used to test post-init failure). */
  startError: Error | null = null;
  start() {
    if (this.startError) throw this.startError;
    this.started = true;
  }
  stop() {
    this.stopped = true;
    this.onend?.();
  }
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("VoicePanel — speech-API graceful degradation", () => {
  it("shows the unsupported fallback when the factory returns null (Firefox path)", () => {
    render(
      <VoicePanel
        open
        onClose={() => undefined}
        speechRecognitionFactory={() => null}
      />,
    );

    const fallback = screen.getByTestId("voice-init-fallback");
    expect(fallback).toBeInTheDocument();
    expect(fallback.getAttribute("data-mode")).toBe("unsupported");
    expect(fallback.textContent).toMatch(/voice no disponible en este navegador/i);
    // Mic disabled, textarea still functional.
    expect((screen.getByTestId("voice-mic-toggle") as HTMLButtonElement).disabled).toBe(true);
    const textarea = screen.getByTestId("voice-transcript") as HTMLTextAreaElement;
    expect(textarea.disabled).toBe(false);
  });

  it("shows the not-allowed fallback when the factory throws at construction (HTTPS-tunnel path)", () => {
    render(
      <VoicePanel
        open
        onClose={() => undefined}
        speechRecognitionFactory={() => {
          throw new Error("SecurityError: speech-api blocked on this origin");
        }}
      />,
    );

    const fallback = screen.getByTestId("voice-init-fallback");
    expect(fallback).toBeInTheDocument();
    expect(fallback.getAttribute("data-mode")).toBe("not-allowed");
    expect(fallback.textContent).toMatch(/voice no disponible en este origen/i);
    // The error detail surfaces the underlying exception.
    expect(screen.getByTestId("voice-init-detail").textContent).toMatch(
      /securityerror.*speech-api blocked/i,
    );
    // Mic disabled, textarea still functional.
    expect((screen.getByTestId("voice-mic-toggle") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId("voice-transcript") as HTMLTextAreaElement).disabled).toBe(false);
  });

  it("falls back to the failed mode and keeps text input usable when start() throws", async () => {
    const recog = new FakeRecognition();
    recog.startError = new Error("InvalidStateError: already started");
    const ask = vi.fn().mockResolvedValue({
      answer: "fallback answer",
      hashReceipt: null,
      ledgerSeq: null,
      model: null,
      sessionId: null,
    });

    render(
      <VoicePanel
        open
        onClose={() => undefined}
        ask={ask}
        speechRecognitionFactory={() => recog}
      />,
    );

    // Probe succeeded — mic is initially enabled.
    const mic = screen.getByTestId("voice-mic-toggle") as HTMLButtonElement;
    expect(mic.disabled).toBe(false);

    // Click mic — start() throws, panel surfaces the failed fallback.
    fireEvent.click(mic);

    await waitFor(() => {
      expect(screen.getByTestId("voice-init-fallback")).toBeInTheDocument();
    });
    expect(screen.getByTestId("voice-init-fallback").getAttribute("data-mode")).toBe(
      "failed",
    );
    // Retry button is offered for the recoverable case.
    expect(screen.getByTestId("voice-init-retry")).toBeInTheDocument();

    // Text input remains usable — the user can still type and submit.
    const textarea = screen.getByTestId("voice-transcript") as HTMLTextAreaElement;
    expect(textarea.disabled).toBe(false);
    fireEvent.change(textarea, { target: { value: "type-only fallback works" } });
    fireEvent.click(screen.getByTestId("voice-submit"));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    expect(ask.mock.calls[0][0]).toMatch(/type-only fallback works/);
  });

  it("classifies onerror service-not-allowed as the not-allowed fallback", async () => {
    const recog = new FakeRecognition();
    render(
      <VoicePanel
        open
        onClose={() => undefined}
        speechRecognitionFactory={() => recog}
      />,
    );
    fireEvent.click(screen.getByTestId("voice-mic-toggle"));
    expect(recog.started).toBe(true);

    // Simulate the HTTPS-tunnel onerror.
    recog.onerror?.({ error: "service-not-allowed" });

    await waitFor(() => {
      expect(screen.getByTestId("voice-init-fallback")).toBeInTheDocument();
    });
    expect(screen.getByTestId("voice-init-fallback").getAttribute("data-mode")).toBe(
      "not-allowed",
    );
    // Error detail carries the raw code so devs can grep for it.
    expect(screen.getByTestId("voice-init-detail").textContent).toMatch(
      /service-not-allowed/,
    );
    // Textarea still usable.
    expect((screen.getByTestId("voice-transcript") as HTMLTextAreaElement).disabled).toBe(false);
  });

  it("classifies a generic onerror code as the failed fallback with retry", async () => {
    const recog = new FakeRecognition();
    render(
      <VoicePanel
        open
        onClose={() => undefined}
        speechRecognitionFactory={() => recog}
      />,
    );
    fireEvent.click(screen.getByTestId("voice-mic-toggle"));

    recog.onerror?.({ error: "audio-capture" });

    await waitFor(() => {
      expect(screen.getByTestId("voice-init-fallback")).toBeInTheDocument();
    });
    expect(screen.getByTestId("voice-init-fallback").getAttribute("data-mode")).toBe(
      "failed",
    );
    expect(screen.getByTestId("voice-init-retry")).toBeInTheDocument();
  });

  it("renders KPI citation chip when ask() returns a kpi_node citation (P13)", async () => {
    // Simulates the MCP-routed happy path: voice-agent looked up the
    // KPI through worm-core's MCP server and returned the seq of the
    // most recent emit_kpi_node entry. The panel must render the KPI
    // name + ledger row in the trace link, and the link's
    // citation-kind data attribute must mark it as a KPI citation
    // (so demo-time visual checks can confirm the wire fired).
    const ask = vi.fn().mockResolvedValue({
      answer: "Q3 net revenue is the most recent ledger entry I have.",
      hashReceipt: "b".repeat(64),
      ledgerSeq: 419,
      model: "kimi-k2.6:cloud",
      sessionId: "dashboard-baseworm-anonymous",
      citationKind: "kpi_node",
      kpi: {
        id: "kpi-q3-net-revenue",
        name: "Q3 Net Revenue",
        formula: "sum(invoices.net_amount)",
        unit: "USD",
        ownerPosition: "CFO",
        status: "active",
      },
    });

    render(
      <VoicePanel
        open
        onClose={() => undefined}
        ask={ask}
        speechRecognitionFactory={() => null}
      />,
    );

    fireEvent.change(screen.getByTestId("voice-transcript"), {
      target: { value: "what's the current value of Q3 net revenue?" },
    });
    fireEvent.click(screen.getByTestId("voice-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("voice-answer")).toBeInTheDocument(),
    );

    const link = screen.getByTestId("voice-trace-link") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/trace?seq=419");
    expect(link.getAttribute("data-citation-kind")).toBe("kpi_node");
    expect(link.textContent).toMatch(/Q3 Net Revenue/);
    expect(link.textContent).toMatch(/ledger row 419/);

    // KPI metadata chip — name + formula + unit visible.
    const kpiMeta = screen.getByTestId("voice-kpi-meta");
    expect(kpiMeta.textContent).toMatch(/Q3 Net Revenue/);
    expect(kpiMeta.textContent).toMatch(/sum\(invoices\.net_amount\)/);
    expect(kpiMeta.textContent).toMatch(/\(USD\)/);
  });

  it("falls back to chat_sent citation kind when no KPI hit (P13)", async () => {
    // Non-KPI question: voice-agent does NOT route through MCP and
    // the citation falls back to the chat_sent ledger row. The link
    // still works; the citation-kind chip records that nothing fancy
    // happened.
    const ask = vi.fn().mockResolvedValue({
      answer: "Hello.",
      hashReceipt: null,
      ledgerSeq: 42,
      model: "kimi-k2.6:cloud",
      sessionId: "s",
      citationKind: "chat_sent",
      kpi: null,
    });

    render(
      <VoicePanel
        open
        onClose={() => undefined}
        ask={ask}
        speechRecognitionFactory={() => null}
      />,
    );

    fireEvent.change(screen.getByTestId("voice-transcript"), {
      target: { value: "hi worm" },
    });
    fireEvent.click(screen.getByTestId("voice-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("voice-answer")).toBeInTheDocument(),
    );
    const link = screen.getByTestId("voice-trace-link") as HTMLAnchorElement;
    expect(link.getAttribute("data-citation-kind")).toBe("chat_sent");
    expect(link.getAttribute("href")).toBe("/trace?seq=42");
    expect(screen.queryByTestId("voice-kpi-meta")).not.toBeInTheDocument();
  });

  it("textarea is never disabled by speech state", () => {
    // Run through every init mode: factory-null, factory-throws,
    // working-then-error. In each, the textarea must stay enabled.
    const cases: Array<() => SpeechRecognitionLike | null> = [
      () => null,
      () => {
        throw new Error("origin blocked");
      },
    ];
    for (const factory of cases) {
      const { unmount } = render(
        <VoicePanel
          open
          onClose={() => undefined}
          speechRecognitionFactory={factory}
        />,
      );
      const textarea = screen.getByTestId("voice-transcript") as HTMLTextAreaElement;
      expect(textarea.disabled).toBe(false);
      unmount();
    }
  });
});
