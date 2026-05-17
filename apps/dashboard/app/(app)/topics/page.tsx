import { getTopics } from "../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";
import { TopicsList } from "../../../components/topics/TopicsList";
import {
  TopicPlatformFilter,
  resolveTopicPlatformFilter,
  type TopicPlatformFilterValue,
} from "../../../components/topics/TopicPlatformFilter";
import { EmptyState } from "../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../components/chrome/PageBoundary";
import { platformBySlug } from "../../../lib/platform-status";

export const metadata = { title: "WormBase · Topics" };

export const dynamic = "force-dynamic";

/**
 * /topics — silver-conversations cluster view.
 *
 * The biggest unclaimed differentiator per the business audit: Read.ai
 * does meeting topics; nobody does chat topics; Fivetran admits they
 * can't sessionize chat. v1 is naive — one topic per (channel,
 * top-keyword) pair, top-keyword = simple TF over whitespace tokens
 * minus a small stopword allowlist. The projection-builder service
 * (WS4) will swap this for a proper clustering pass.
 *
 * W4-A (2026-05-07) — platform facet. ``?platform=<slug>`` filters the
 * topics list to entries whose underlying ``chat_received`` channel id
 * is platform-shaped (WhatsApp jids vs Slack channel ids). Default
 * ``all`` is byte-identical to pre-filter behaviour.
 */
export default async function TopicsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const filter: TopicPlatformFilterValue = resolveTopicPlatformFilter(
    params.platform,
  );
  const companyId = await getCurrentCompanyId();
  const topics = await getTopics(
    companyId,
    20,
    filter === "all" ? undefined : filter,
  );

  const filteredLabel =
    filter === "all" ? null : platformBySlug(filter)?.label ?? filter;

  return (
    <PageBoundary surface="topics" traceQuery="?surface=topics">
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Pl. XII · Conversation lake · live
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 34,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
        >
          Topics across your conversations · {topics.length}
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
          Each card clusters recent chatter in a connected channel into a
          working topic — the same conversation lake the worm reads when it
          extracts decisions, processes, and recurring questions. Ordered
          by message volume.
        </p>
      </header>

      <TopicPlatformFilter current={filter} />

      {topics.length === 0 ? (
        filteredLabel ? (
          <EmptyState
            testId={`topics-empty-${filter}`}
            eyebrow={`no ${filter} topics yet`}
            title={`No topics from ${filteredLabel} yet.`}
            description={
              `The worm hasn't surfaced any topic clusters from ${filteredLabel} ` +
              `chatter in the conversation lake. Connect ${filteredLabel} or wait ` +
              `for the next bronze cascade — silver topic clusters land within a ` +
              `minute of the first wire event from the platform.`
            }
            cta={{ label: "Connect a chat platform", href: "/channels" }}
            secondaryCta={{ label: "See raw activity", href: "/activity" }}
          />
        ) : (
          <EmptyState
            testId="topics-empty"
            eyebrow="no topics yet"
            title="No conversations yet."
            description={
              "The worm starts surfacing topics as your team chats in connected " +
              "channels. Drop the worm into 1-2 channels to begin — silver " +
              "topic clusters land within a minute of the first wire event."
            }
            cta={{ label: "Connect a chat platform", href: "/channels" }}
            secondaryCta={{ label: "See raw activity", href: "/activity" }}
          />
        )
      ) : (
        <TopicsList topics={topics} />
      )}
    </PageBoundary>
  );
}
