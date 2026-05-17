/**
 * AskTheWormFloater + VoicePanel tests (W3.A12, W7.A5).
 *
 * Covers the load-bearing UX contracts:
 *
 *   - The floater renders bottom-right and toggles a slide-in panel.
 *   - The panel disables the mic and shows a graceful-degrade message
 *     when the Web Speech API is unavailable (Firefox path).
 *   - Submitting a transcript POSTs to the proxy, renders the answer,
 *     hash receipt, and a `/trace?seq=N` link (sister A10's filter).
 *   - When the proxy returns 503, the panel surfaces an honest
 *     "service unavailable" banner with retry — no fixture answer.
 *   - The Web Speech API path streams interim transcripts into the
 *     visible textarea before the user submits.
 *   - When the panel render itself throws (W7.A5), the localized
 *     `VoiceErrorBoundary` catches the error and renders a compact
 *     fallback panel; the floater button stays alive.
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

import { AskTheWormFloater } from "../AskTheWormFloater";
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
  start() {
    this.started = true;
  }
  stop() {
    this.stopped = true;
    this.onend?.();
  }
  /** Helper for tests to feed a result event. */
  emit(transcript: string, isFinal: boolean) {
    this.onresult?.({
      resultIndex: 0,
      results: [
        {
          isFinal,
          length: 1,
          0: { transcript },
        } as unknown as { isFinal: boolean; length: number; [k: number]: { transcript: string } },
      ],
    } as never);
  }
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AskTheWormFloater", () => {
  it("renders the floating button collapsed by default and toggles the panel", () => {
    render(
      <AskTheWormFloater speechRecognitionFactory={() => null} />,
    );
    const btn = screen.getByTestId("ask-the-worm-floater");
    expect(btn).toBeInTheDocument();
    expect(btn.getAttribute("data-open")).toBe("false");
    expect(screen.queryByTestId("voice-panel")).not.toBeInTheDocument();

    fireEvent.click(btn);
    expect(btn.getAttribute("data-open")).toBe("true");
    expect(screen.getByTestId("voice-panel")).toBeInTheDocument();

    fireEvent.click(btn);
    expect(btn.getAttribute("data-open")).toBe("false");
    expect(screen.queryByTestId("voice-panel")).not.toBeInTheDocument();
  });
});

describe("VoicePanel — graceful Firefox degrade", () => {
  it("disables the mic and shows the unavailable message when STT factory returns null", () => {
    render(
      <VoicePanel
        open
        onClose={() => undefined}
        speechRecognitionFactory={() => null}
      />,
    );
    const mic = screen.getByTestId("voice-mic-toggle");
    expect((mic as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("voice-support-status").textContent).toMatch(
      /browser STT unavailable/i,
    );
    // The textarea is still usable.
    expect(screen.getByTestId("voice-transcript")).toBeInTheDocument();
  });
});

describe("VoicePanel — Chrome happy path", () => {
  it("streams interim transcript and submits the final text to /api/v1/voice/ask", async () => {
    const recog = new FakeRecognition();
    const ask = vi.fn().mockResolvedValue({
      answer: "Q3 net revenue was four point two million dollars.",
      hashReceipt: "a".repeat(64),
      ledgerSeq: 247,
      model: "kimi-k2.6:cloud",
      sessionId: "dashboard-baseworm-anonymous",
    });

    render(
      <VoicePanel
        open
        onClose={() => undefined}
        ask={ask}
        speechRecognitionFactory={() => recog}
      />,
    );

    // Click mic — recognition starts.
    fireEvent.click(screen.getByTestId("voice-mic-toggle"));
    expect(recog.started).toBe(true);

    // Stream an interim, then a final result.
    recog.emit("what's our churn", false);
    await waitFor(() =>
      expect(
        (screen.getByTestId("voice-transcript") as HTMLTextAreaElement).value,
      ).toContain("what's our churn"),
    );
    recog.emit("what's our churn?", true);
    await waitFor(() =>
      expect(
        (screen.getByTestId("voice-transcript") as HTMLTextAreaElement).value,
      ).toMatch(/what's our churn\?/),
    );

    // Submit.
    fireEvent.click(screen.getByTestId("voice-submit"));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    expect(ask.mock.calls[0][0]).toMatch(/what's our churn\?/);

    // Answer renders with hash receipt + trace link.
    await waitFor(() =>
      expect(screen.getByTestId("voice-answer")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("voice-answer-text").textContent).toMatch(
      /four point two million dollars/i,
    );
    expect(screen.getByTestId("voice-hash-receipt").textContent).toMatch(
      /sha256/,
    );
    const link = screen.getByTestId("voice-trace-link") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/trace?seq=247");
  });
});

describe("VoicePanel — service unavailable", () => {
  it("renders the honest 503 banner with retry when the proxy errors", async () => {
    const ask = vi
      .fn()
      .mockRejectedValue(new Error("voice-agent service did not respond"));

    render(
      <VoicePanel
        open
        onClose={() => undefined}
        ask={ask}
        speechRecognitionFactory={() => null}
      />,
    );

    // Type into the textarea (Firefox-style flow).
    fireEvent.change(screen.getByTestId("voice-transcript"), {
      target: { value: "what's our churn?" },
    });
    fireEvent.click(screen.getByTestId("voice-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("voice-error")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("voice-error").textContent).toMatch(
      /service unavailable/i,
    );
    expect(screen.getByTestId("voice-error").textContent).toMatch(
      /voice-agent service did not respond/i,
    );
    // No fixture answer rendered.
    expect(screen.queryByTestId("voice-answer")).not.toBeInTheDocument();

    // Retry resets to idle so the user can ask again.
    fireEvent.click(screen.getByTestId("voice-retry"));
    expect(screen.queryByTestId("voice-error")).not.toBeInTheDocument();
  });
});

describe("VoicePanel — empty submit guard", () => {
  it("does not call ask() when transcript is empty", () => {
    const ask = vi.fn();
    render(
      <VoicePanel
        open
        onClose={() => undefined}
        ask={ask}
        speechRecognitionFactory={() => null}
      />,
    );
    const submit = screen.getByTestId("voice-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.click(submit);
    expect(ask).not.toHaveBeenCalled();
  });
});

describe("AskTheWormFloater — speech-init error containment (W7.A5)", () => {
  it("does not crash the floater when speech-init throws — panel renders graceful fallback", () => {
    // Silence the React render-error log: the boundary surfaces a
    // console.error by design and we don't want that to fail any
    // strict-error setup.
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);

    // Factory throws synchronously on every call — simulates a
    // locked-down origin where `new webkitSpeechRecognition()`
    // raises a SecurityError. The panel's own try/catch should
    // catch this and render the not-allowed fallback; the
    // VoiceErrorBoundary is the second-line backstop.
    const ExplodingFactory = (): SpeechRecognitionLike => {
      throw new Error("kaboom: synthetic speech-init render error");
    };

    render(
      <AskTheWormFloater
        initialOpen
        speechRecognitionFactory={ExplodingFactory}
      />,
    );

    // The floater button is alive — no white-screen crash.
    expect(screen.getByTestId("ask-the-worm-floater")).toBeInTheDocument();
    // Either the panel handled it (init-fallback rendered) OR the
    // boundary caught it (voice-panel-error rendered). At least one
    // honest surface must be visible — never a silent void.
    const handled =
      screen.queryByTestId("voice-init-fallback") ??
      screen.queryByTestId("voice-panel-error");
    expect(handled).not.toBeNull();

    errSpy.mockRestore();
  });
});
