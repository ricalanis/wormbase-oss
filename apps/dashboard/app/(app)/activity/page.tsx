import {
  getConversations,
  getInsights,
  getTasks,
} from "../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";
import { ConversationsFeed } from "../../../components/activity/ConversationsFeed";
import { TasksPanel } from "../../../components/activity/TasksPanel";
import { InsightsPanel } from "../../../components/activity/InsightsPanel";
import { PageBoundary } from "../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · Activity & Insights" };

export default async function ActivityPage() {
  const companyId = await getCurrentCompanyId();
  const [conversations, tasks, insights] = await Promise.all([
    getConversations(companyId),
    getTasks(companyId),
    getInsights(companyId),
  ]);

  return (
    <PageBoundary surface="activity" traceQuery="?surface=activity">
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
          Pl. XI · Conversations as data
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
          Activity & Insights
        </h1>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          A field-notebook transcript of channel activity, the worm's pending
          tasks, and the gold marts it has surfaced as insights. Explicitly not a
          chat-bubble UI — every line is receipted.
        </p>
      </header>

      <section data-testid="activity-conversations">
        <h2
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 20,
            fontWeight: 600,
            letterSpacing: "-0.005em",
            margin: "0 0 12px",
            borderBottom: "3px double var(--wb-color-aged-ink)",
            paddingBottom: 6,
          }}
        >
          Conversations
        </h2>
        <ConversationsFeed messages={conversations} />
      </section>

      <section data-testid="activity-tasks">
        <h2
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 20,
            fontWeight: 600,
            letterSpacing: "-0.005em",
            margin: "0 0 12px",
            borderBottom: "3px double var(--wb-color-aged-ink)",
            paddingBottom: 6,
          }}
        >
          Tasks
        </h2>
        <TasksPanel tasks={tasks} />
      </section>

      <section data-testid="activity-insights">
        <h2
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 20,
            fontWeight: 600,
            letterSpacing: "-0.005em",
            margin: "0 0 12px",
            borderBottom: "3px double var(--wb-color-aged-ink)",
            paddingBottom: 6,
          }}
        >
          Process insights
        </h2>
        <InsightsPanel insights={insights} />
      </section>
    </PageBoundary>
  );
}
