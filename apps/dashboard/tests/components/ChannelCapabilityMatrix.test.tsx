/**
 * Phase W2-B (2026-05-07) — channel capability matrix on /security.
 *
 * Tests the matrix surfaces every supported channel with its transport,
 * capability set, and compliance posture. Reads from the canonical
 * `PLATFORMS` array — the matrix stays in lockstep with W1's pinned-mirror
 * contract test on `lib/platform-status.ts`. When a new platform graduates
 * capabilities upstream, the row updates without code change.
 */
import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { ChannelCapabilityMatrix } from "../../components/landing/ChannelCapabilityMatrix";

describe("ChannelCapabilityMatrix (/security capability matrix)", () => {
  it("renders the matrix section with a labelled headline", () => {
    render(<ChannelCapabilityMatrix />);
    const section = screen.getByTestId("channel-capability-matrix");
    expect(section).toBeInTheDocument();
    expect(
      screen.getByTestId("channel-capability-matrix-headline"),
    ).toBeInTheDocument();
  });

  it("renders the Slack row at production status with full capability set", () => {
    render(<ChannelCapabilityMatrix />);
    const row = screen.getByTestId("capability-row-slack");
    expect(row).toBeInTheDocument();
    expect(within(row).getByText("Slack")).toBeInTheDocument();
    expect(row.textContent).toContain("OAuth bot");
    // Slack capability list is hand-rolled in the matrix today (descriptor
    // doesn't yet carry an opt-in capabilities array); the matrix lists
    // ingest + send + dm + file_upload editorially.
    expect(row.textContent).toMatch(/ingest/);
    expect(row.textContent).toMatch(/send/);
    expect(row.textContent).toMatch(/dm/);
    expect(row.textContent).toMatch(/file_upload/);
    expect(row.textContent).toMatch(/Production/i);
    expect(row.textContent).toMatch(/SOC-?2/i);
  });

  it("renders the WhatsApp row at preview status with the post-C-wave capability set from the canonical descriptor", () => {
    render(<ChannelCapabilityMatrix />);
    const row = screen.getByTestId("capability-row-whatsapp");
    expect(row).toBeInTheDocument();
    expect(within(row).getByText("WhatsApp")).toBeInTheDocument();
    expect(row.textContent).toContain("OpenClaw Baileys");
    // Capabilities read from the descriptor — C-wave landed
    // {ingest, dm, send}.
    expect(row.textContent).toMatch(/ingest/);
    expect(row.textContent).toMatch(/dm/);
    expect(row.textContent).toMatch(/send/);
    expect(row.textContent).toMatch(/Preview/i);
    expect(row.textContent).toMatch(/Baileys ToS/i);
    expect(row.textContent).toMatch(/test number/i);
  });

  it("renders Discord and Teams as a grouped 'Coming soon' stub row", () => {
    render(<ChannelCapabilityMatrix />);
    const row = screen.getByTestId("capability-row-stubs");
    expect(row).toBeInTheDocument();
    expect(row.textContent).toMatch(/Discord/);
    expect(row.textContent).toMatch(/Teams/);
    expect(row.textContent).toMatch(/Stub adapters/);
    expect(row.textContent).toMatch(/Coming soon/);
  });

  it("surfaces the WhatsApp ingest preview-pricing one-line note", () => {
    render(<ChannelCapabilityMatrix />);
    const note = screen.getByTestId("capability-matrix-pricing-note");
    expect(note).toBeInTheDocument();
    expect(note.textContent).toMatch(/WhatsApp ingest/i);
    expect(note.textContent).toMatch(/free/i);
    expect(note.textContent).toMatch(/preview/i);
    expect(note.textContent).toMatch(/production/i);
  });

  it("renders capability strings as monospaced code chips", () => {
    render(<ChannelCapabilityMatrix />);
    const row = screen.getByTestId("capability-row-whatsapp");
    const code = row.querySelector("code");
    expect(code).not.toBeNull();
    expect(code?.textContent).toContain("ingest");
  });
});
