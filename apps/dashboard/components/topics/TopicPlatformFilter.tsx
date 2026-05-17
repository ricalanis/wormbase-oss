"use client";
/**
 * TopicPlatformFilter — All / Slack / WhatsApp chip set above /topics list.
 *
 * Reads ``?platform=`` from the URL; defaults to "all" (no filter clause,
 * Slack rendering byte-identical to pre-filter behaviour). Clicking a chip
 * replaces the URL with the new value while preserving any other query
 * params; the /topics server page reads the resolved slug, threads it
 * into ``getTopics(companyId, limit, platform)``, and re-renders.
 *
 * Status tone mirrors W1's PlatformDescriptor.status — preview platforms
 * (WhatsApp today) carry the sepia tone used elsewhere on the dashboard
 * to flag preview surfaces; production platforms (Slack) use the
 * botanical-green tone. The "All" chip uses the muted aged-ink default.
 *
 * Bookmarkable URL state — cross-cutting surfaces (e.g. /people/proposals
 * deep-linking to topics from a person's WhatsApp messages) can construct
 * ``/topics?platform=whatsapp`` directly.
 *
 * Editorial chrome: small uppercase wb-mono labels, square corners, no
 * icons. Sepia rule under the active chip per the same convention as
 * AudienceTabs on /research.
 */

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";
import {
  PLATFORMS,
  type PlatformDescriptor,
  type PlatformSlug,
} from "../../lib/platform-status";

export type TopicPlatformFilterValue = "all" | PlatformSlug;

const FILTER_KEYS: ReadonlyArray<TopicPlatformFilterValue> = [
  "all",
  "slack",
  "whatsapp",
];

function isFilterValue(v: string): v is TopicPlatformFilterValue {
  return (FILTER_KEYS as readonly string[]).includes(v);
}

/**
 * Resolve a raw search-param value to a TopicPlatformFilterValue.
 *
 * Defaults to ``"all"`` for any unknown value (forward-compat: a future
 * Discord chip won't crash a bookmarked ``?platform=discord`` link;
 * it just lands on All until the chip ships).
 */
export function resolveTopicPlatformFilter(
  raw: string | string[] | undefined,
): TopicPlatformFilterValue {
  const candidate = typeof raw === "string" ? raw : Array.isArray(raw) ? raw[0] : "";
  return candidate && isFilterValue(candidate) ? candidate : "all";
}

interface ChipMeta {
  key: TopicPlatformFilterValue;
  label: string;
  descriptor: PlatformDescriptor | null;
}

function buildChips(): ChipMeta[] {
  const slack = PLATFORMS.find((p) => p.platform === "slack") ?? null;
  const whatsapp = PLATFORMS.find((p) => p.platform === "whatsapp") ?? null;
  return [
    { key: "all", label: "All", descriptor: null },
    {
      key: "slack",
      label: slack?.label ?? "Slack",
      descriptor: slack,
    },
    {
      key: "whatsapp",
      label: whatsapp?.label ?? "WhatsApp",
      descriptor: whatsapp,
    },
  ];
}

export interface TopicPlatformFilterProps {
  /** Override the resolved value (defaults to ?platform= → "all"). */
  current?: TopicPlatformFilterValue;
}

export function TopicPlatformFilter({ current }: TopicPlatformFilterProps) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const resolved =
    current ?? resolveTopicPlatformFilter(params.get("platform") ?? undefined);

  const select = useCallback(
    (next: TopicPlatformFilterValue) => {
      const qp = new URLSearchParams(params.toString());
      if (next === "all") qp.delete("platform");
      else qp.set("platform", next);
      const qs = qp.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname);
    },
    [params, pathname, router],
  );

  const chips = buildChips();

  return (
    <nav
      data-testid="topic-platform-filter"
      aria-label="Filter topics by platform"
      style={{
        display: "flex",
        gap: 0,
        borderBottom: "1px solid var(--wb-color-rule-line)",
      }}
    >
      {chips.map((chip) => {
        const isActive = resolved === chip.key;
        const tone = chipTone(chip.descriptor?.status ?? null, isActive);
        const tooltip = chip.descriptor?.statusNote;
        return (
          <button
            key={chip.key}
            type="button"
            role="tab"
            aria-selected={isActive}
            data-testid={`topic-platform-chip-${chip.key}`}
            data-active={isActive ? "true" : "false"}
            data-status={chip.descriptor?.status ?? "all"}
            onClick={() => select(chip.key)}
            title={tooltip}
            style={{
              padding: "10px 18px",
              border: "none",
              borderBottom: `2px solid ${
                isActive ? tone.activeRule : "transparent"
              }`,
              background: "transparent",
              fontFamily: "var(--wb-font-mono)",
              fontSize: 11,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: isActive ? tone.activeFg : "var(--wb-color-hash-gray)",
              cursor: "pointer",
              marginBottom: -1,
            }}
          >
            {chip.label}
          </button>
        );
      })}
    </nav>
  );
}

interface ChipTone {
  activeFg: string;
  activeRule: string;
}

function chipTone(
  status: PlatformDescriptor["status"] | null,
  _isActive: boolean,
): ChipTone {
  switch (status) {
    case "preview":
      return {
        activeFg: "var(--wb-color-sepia-warning-deep)",
        activeRule: "var(--wb-color-sepia-warning)",
      };
    case "production":
      return {
        activeFg: "var(--wb-color-aged-ink)",
        activeRule: "var(--wb-color-botanical-green-deep)",
      };
    case "coming_soon":
      return {
        activeFg: "var(--wb-color-hash-gray)",
        activeRule: "var(--wb-color-paper-edge)",
      };
    default:
      // "All" — no descriptor; muted aged-ink rule.
      return {
        activeFg: "var(--wb-color-aged-ink)",
        activeRule: "var(--wb-color-aged-ink)",
      };
  }
}
