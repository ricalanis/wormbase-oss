"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { WormMark } from "@wormbase/design";
import { ClassificationOverlayToggle } from "../classification/ClassificationOverlayToggle";
import { navItemsForRole, type NavRole } from "../../lib/role-nav";

export interface SidebarProps {
  /** Tenancy role of the resolved current Person. The server RSC layout
   *  passes this through; absent it we render the admin (full) nav as a
   *  back-compat default. */
  role?: NavRole;
}

export function Sidebar({ role = "admin" }: SidebarProps) {
  const pathname = usePathname() ?? "";
  const items = navItemsForRole(role);
  return (
    <nav
      aria-label="primary"
      data-testid="sidebar"
      style={{
        position: "sticky",
        top: 0,
        height: "100vh",
        width: 240,
        flex: "0 0 240px",
        borderRight: "1px solid var(--wb-color-botanical-green)",
        background: "var(--wb-color-paper)",
        display: "flex",
        flexDirection: "column",
        padding: "20px 16px 24px",
        gap: 20,
        boxSizing: "border-box",
      }}
    >
      <Link
        href="/"
        aria-label="WormBase home"
        style={{
          textDecoration: "none",
          color: "inherit",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <WormMark size={40} showArc={false} ticks={false} />
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontWeight: 600,
            fontSize: 18,
            letterSpacing: "-0.01em",
          }}
        >
          WormBase
        </span>
      </Link>

      <span
        className="wb-mono"
        style={{
          fontSize: 9,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
          borderTop: "1px solid var(--wb-color-paper-edge)",
          paddingTop: 12,
        }}
      >
        Field Notebook · Vol. I
      </span>

      <ul
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "flex",
          flexDirection: "column",
          gap: 2,
        }}
      >
        {items.map((item) => {
          const active =
            pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href));
          // Observer mode (readOnly === true) renders muted; admin/installer/
          // member render in normal ink.
          const muted = item.readOnly === true;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                data-testid={`nav-${item.href.replace(/\//g, "-").replace(/^-/, "")}`}
                data-active={active ? "true" : "false"}
                data-readonly={muted ? "true" : "false"}
                style={{
                  display: "block",
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 15,
                  padding: "8px 4px",
                  color: muted
                    ? "var(--wb-color-hash-gray)"
                    : active
                      ? "var(--wb-color-aged-ink)"
                      : "var(--wb-color-aged-ink-soft)",
                  textDecoration: active ? "underline" : "none",
                  textUnderlineOffset: 4,
                  textDecorationColor: "var(--wb-color-botanical-green)",
                  textDecorationThickness: 2,
                  borderLeft: active
                    ? "2px solid var(--wb-color-botanical-green)"
                    : "2px solid transparent",
                  paddingLeft: 8,
                }}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>

      <div style={{ marginTop: "auto" }}>
        <ClassificationOverlayToggle />
      </div>
    </nav>
  );
}
