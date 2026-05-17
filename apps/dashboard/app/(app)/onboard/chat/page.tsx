/**
 * /onboard/chat — channel-adapter marketplace
 * (Onboarding Sub-wave B, 2026-05-30).
 *
 * Lists every channel adapter the dashboard knows about (Slack,
 * WhatsApp, Discord, Teams, Signal, …) with capability + status
 * badges and the per-tenant install count. Production / preview rows
 * link to the existing OAuth flow at /channels/connect/<platform>;
 * coming_soon rows are muted with a "Notify me (v1.5)" badge.
 */
import Link from "next/link";
import type { JSX } from "react";

import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { CapabilityBadges } from "../../../../components/onboard/CapabilityBadges";
import type {
  CapabilityStatus,
} from "../../../../components/onboard/CapabilityBadges";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import { getOnboardChat } from "../../../../lib/onboard";
import type {
  OnboardChatRow,
} from "../../../../lib/onboard";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";

export const metadata = { title: "WormBase · Onboard · Chat" };

export const dynamic = "force-dynamic";

function statusToCapability(s: OnboardChatRow["status"]): CapabilityStatus {
  switch (s) {
    case "production":
      return "production";
    case "preview":
      return "preview";
    case "coming_soon":
      return "coming_soon";
  }
}

export default async function OnboardChatPage(): Promise<JSX.Element> {
  const companyId = await getCurrentCompanyId();
  const view = await getOnboardChat(companyId);
  const rows = view.rows;
  const connectedCount = rows.filter((r) => r.connected).length;
  return (
    <PageBoundary
      surface="onboard chat"
      traceQuery="?surface=onboard.chat"
    >
      <header
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            @onboard chat · channel adapters
          </span>
          <h1
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 30,
              fontWeight: 500,
            }}
          >
            Chat · {rows.length} adapters · {connectedCount} connected
          </h1>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
              maxWidth: 720,
            }}
          >
            Connect the worm to every chat surface the company already
            uses. The worm lurks first, speaks later — see the talkativeness
            dial on /channels per install.
          </p>
        </div>
        <Link
          href="/channels"
          data-testid="onboard-chat-channels-link"
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            padding: "8px 16px",
            border: "1px solid var(--wb-color-aged-ink)",
            background: "var(--wb-color-paper)",
            color: "var(--wb-color-aged-ink)",
            textDecoration: "none",
          }}
        >
          Manage on /channels
        </Link>
      </header>

      {rows.length === 0 ? (
        <EmptyState
          testId="onboard-chat-empty"
          eyebrow="no channel adapters"
          title="No channel adapters registered."
          description="The dashboard couldn't load the channel-adapter descriptors. Verify the build."
          cta={{ label: "See /channels", href: "/channels" }}
        />
      ) : (
        <ul
          data-testid="onboard-chat-rows"
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            border: "1px solid var(--wb-color-paper-edge)",
            borderTop: "none",
          }}
        >
          {rows.map((row) => (
            <li
              key={row.platform}
              data-testid={`onboard-chat-row-${row.platform}`}
              style={{
                display: "grid",
                gridTemplateColumns:
                  "minmax(160px, 200px) 1fr minmax(140px, 180px)",
                gap: 12,
                alignItems: "baseline",
                padding: "12px 14px",
                borderTop: "1px solid var(--wb-color-paper-edge)",
                background: "var(--wb-color-paper)",
                opacity: row.status === "coming_soon" ? 0.7 : 1,
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <strong
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontSize: 15,
                  }}
                >
                  {row.label}
                </strong>
                <code
                  className="wb-mono"
                  style={{
                    fontSize: 11,
                    color: "var(--wb-color-hash-gray)",
                  }}
                >
                  {row.platform}
                </code>
              </div>
              <CapabilityBadges
                kind="channel"
                id={row.platform}
                status={statusToCapability(row.status)}
                capabilities={row.capabilities}
                statusNote={row.statusNote}
              />
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                {row.status === "coming_soon" ? (
                  <span
                    className="wb-mono"
                    style={{
                      fontSize: 10,
                      letterSpacing: "0.1em",
                      textTransform: "uppercase",
                      color: "var(--wb-color-hash-gray)",
                    }}
                  >
                    Notify me (v1.5)
                  </span>
                ) : (
                  <Link
                    href={`/channels/connect/${row.platform}`}
                    data-testid={`onboard-chat-connect-${row.platform}`}
                    className="wb-mono"
                    style={{
                      fontSize: 10,
                      letterSpacing: "0.1em",
                      textTransform: "uppercase",
                      padding: "6px 12px",
                      border: "1px solid var(--wb-color-aged-ink)",
                      background: row.connected
                        ? "var(--wb-color-paper)"
                        : "var(--wb-color-aged-ink)",
                      color: row.connected
                        ? "var(--wb-color-aged-ink)"
                        : "var(--wb-color-paper)",
                      textDecoration: "none",
                    }}
                  >
                    {row.connected
                      ? `Connected · ${row.installCount}`
                      : "Add"}
                  </Link>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </PageBoundary>
  );
}
