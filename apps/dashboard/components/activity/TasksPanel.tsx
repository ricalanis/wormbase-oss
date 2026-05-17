import { Receipt } from "../../lib/receipts";
import type { TaskRow } from "../../lib/ledger-client.types";

export function TasksPanel({ tasks }: { tasks: TaskRow[] }) {
  if (tasks.length === 0) {
    return (
      <p
        data-testid="tasks-panel-empty"
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        No pending tasks — once the worm starts proposing follow-ups they
        land here with a Receipt.
      </p>
    );
  }

  return (
    <ul
      data-testid="tasks-panel"
      style={{
        padding: 0,
        margin: 0,
        listStyle: "none",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      {tasks.map((t) => (
        <li
          key={t.taskId}
          data-testid={`task-${t.taskId}`}
          data-kind={t.kind}
          style={{
            border: "1px solid var(--wb-color-paper-edge)",
            borderLeft:
              t.kind === "propose"
                ? "3px solid var(--wb-color-hash-gray)"
                : "3px solid var(--wb-color-botanical-green)",
            padding: 12,
            display: "grid",
            gridTemplateColumns: "120px 1fr 280px",
            gap: 12,
            alignItems: "center",
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            {t.kind} · {t.due ? `due ${t.due}` : "no due"}
          </span>
          <span
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 14,
              color: "var(--wb-color-aged-ink)",
            }}
          >
            {t.description}
          </span>
          <Receipt
            hash={t.receipt.hash}
            source={t.receipt.source}
            owner={t.receipt.owner}
            classification={t.receipt.classification}
            compact
          />
        </li>
      ))}
    </ul>
  );
}
