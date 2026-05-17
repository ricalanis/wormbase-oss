/**
 * Phase 4 Task 4E — standalone /security route.
 *
 * Verifies the public unauthenticated `/security` page surfaces the
 * architectural proof points that back the pitch ("auditable, hash-receipted,
 * multi-tenant institutional AI"). The page is honest — "in progress" beats
 * "certified", and every claim is sourced to a contract test, a doctrine
 * document, or a code path the reader can audit.
 *
 * Each proof point gets a `data-testid="proof-<slug>"` panel; the test
 * checks the slug is present and that the deep-link to the underlying
 * artifact (when applicable) is wired.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import SecurityPage from "../../app/security/page";

describe("SecurityPage (/security standalone route)", () => {
  it("renders the masthead linking back to home for direct visitors", () => {
    render(<SecurityPage />);
    const home = screen.getByTestId("security-page-home");
    expect(home).toHaveAttribute("href", "/");
  });

  it("renders the security headline + plate kicker", () => {
    render(<SecurityPage />);
    expect(screen.getByTestId("security-section")).toBeInTheDocument();
    expect(screen.getByTestId("security-headline")).toBeInTheDocument();
  });

  it("surfaces multi-tenant isolation proof with contract-test citation", () => {
    render(<SecurityPage />);
    const panel = screen.getByTestId("proof-multi-tenant-isolation");
    expect(panel).toBeInTheDocument();
    // Cite the contract test path so a reviewer can audit it directly.
    expect(panel).toHaveTextContent(
      "tests/multitenant/test_cross_tenant_data_leak_python.py",
    );
    // Honest pass-status; not a marketing claim.
    expect(panel).toHaveTextContent(/passing/i);
  });

  it("surfaces replay determinism (hash-stability) proof", () => {
    render(<SecurityPage />);
    const panel = screen.getByTestId("proof-replay-determinism");
    expect(panel).toBeInTheDocument();
    // Hash example must be visible — the receipt culture surfaced.
    expect(panel).toHaveTextContent(/hash/i);
  });

  it("surfaces hash-chained ledger proof linking to the doctrine", () => {
    render(<SecurityPage />);
    const panel = screen.getByTestId("proof-hash-chained-ledger");
    expect(panel).toBeInTheDocument();
    // Cite the doctrine spec so the reader can audit PEVR + the chain.
    expect(panel).toHaveTextContent(/PEVR/i);
    expect(panel).toHaveTextContent(
      "docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md",
    );
  });

  it("surfaces PII handling via governance gates with code citation", () => {
    render(<SecurityPage />);
    const panel = screen.getByTestId("proof-pii-handling");
    expect(panel).toBeInTheDocument();
    // Cite the gates module so reviewers can audit the redaction path.
    expect(panel).toHaveTextContent(
      "packages/governance/src/wormbase_governance/gates.py",
    );
    expect(panel).toHaveTextContent(/redact/i);
  });

  it("surfaces SOC-2 status as honestly in-progress, not certified", () => {
    render(<SecurityPage />);
    const panel = screen.getByTestId("proof-soc2");
    expect(panel).toBeInTheDocument();
    // Honest claim: copy must say "in progress" and explicitly disclaim
    // certification ("not SOC-2 certified" / "not certified"). It must
    // NOT make a positive certification claim.
    expect(panel).toHaveTextContent(/in progress/i);
    expect(panel).toHaveTextContent(/not\s+(?:SOC-?2\s+)?certified/i);
    // The kicker numeral can render adjacent to "SOC-2", so the panel
    // text must not begin with a positive certification claim like
    // "WormBase is SOC-2 certified" — we assert the plain phrase is
    // never present without a "not" preceding it within a few tokens.
    const text = panel.textContent ?? "";
    expect(/(?<!not\s)(?<!not\s\w{1,30}\s)is\s+SOC-?2\s+certified/i.test(text))
      .toBe(false);
  });

  it("surfaces data export / right-to-delete substrate path", () => {
    render(<SecurityPage />);
    const panel = screen.getByTestId("proof-export-delete");
    expect(panel).toBeInTheDocument();
    // The substrate supports it; the export tooling itself is roadmap.
    expect(panel).toHaveTextContent(/export/i);
    expect(panel).toHaveTextContent(/delete/i);
  });

  it("surfaces encryption posture (TLS in transit + at-rest)", () => {
    render(<SecurityPage />);
    const panel = screen.getByTestId("proof-encryption");
    expect(panel).toBeInTheDocument();
    expect(panel).toHaveTextContent(/TLS/);
    expect(panel).toHaveTextContent(/at rest|at-rest/i);
  });

  it("surfaces inference data flow (Kimi remote / cache locality)", () => {
    render(<SecurityPage />);
    const panel = screen.getByTestId("proof-inference-data-flow");
    expect(panel).toBeInTheDocument();
    expect(panel).toHaveTextContent(/Kimi/);
    expect(panel).toHaveTextContent(/cache/i);
    // Cite the router source so reviewers can audit the data flow.
    expect(panel).toHaveTextContent(
      "packages/inference-router/src/wormbase_inference/router.py",
    );
  });

  it("includes a contact line for security disclosures", () => {
    render(<SecurityPage />);
    const link = screen.getByTestId("security-contact");
    // mailto: link to security@wormbase.io for honest disclosure path.
    const href = link.getAttribute("href") ?? "";
    expect(href.startsWith("mailto:")).toBe(true);
    expect(href).toContain("security@wormbase.io");
  });

  it("composes the channel capability matrix below the proof points (W2-B)", () => {
    render(<SecurityPage />);
    // The matrix section + its WhatsApp row are part of the page surface.
    expect(screen.getByTestId("channel-capability-matrix")).toBeInTheDocument();
    expect(screen.getByTestId("capability-row-whatsapp")).toBeInTheDocument();
  });
});
