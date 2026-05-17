import "../styles.css";
import { LedgerEntry } from "./LedgerEntry";

export const Stream = () => (
  <div style={{ maxWidth: 960, padding: 24 }}>
    <LedgerEntry
      timestamp="08:14:02"
      entryType="propose"
      hash="a3f9c2"
      summary="Proposed source: subscriptions.csv (1,234 rows, 5 cols)"
      actor="worm"
    />
    <LedgerEntry
      timestamp="08:14:07"
      entryType="execute"
      hash="b41f88"
      summary="Downloaded and profiled subscriptions.csv"
      actor="worm"
      detail={`{
  "rows": 1234,
  "columns": ["customer_id", "plan", "mrr", "start_date", "status"],
  "dtypes": {"customer_id": "int64", "plan": "string", "mrr": "float64"},
  "missing_pct": {"mrr": 0.02}
}`}
    />
    <LedgerEntry
      timestamp="08:14:09"
      entryType="verify"
      hash="c92a0d"
      summary="Schema matched expected shape; classifier score 0.94"
      actor="worm"
    />
    <LedgerEntry
      timestamp="08:14:10"
      entryType="resolve"
      hash="d33f21"
      summary="Landed subscriptions.csv to bronze/; memory_written"
      actor="worm"
    />
    <LedgerEntry
      timestamp="08:16:44"
      entryType="gate_fired"
      hash="dead01"
      summary="pii_redaction gate masked column email before reply"
      actor="gate"
    />
  </div>
);

export const SingleExpandable = () => (
  <div style={{ maxWidth: 960, padding: 24 }}>
    <LedgerEntry
      timestamp="09:02:11"
      entryType="kpi_answered"
      hash="a3f9c2"
      summary="Answered #ops: churn last month = 4.2%"
      actor="worm"
      detail={`SELECT segment, churn_rate
FROM mrr_monthly
WHERE month = '2026-03'
GROUP BY segment;

-- sources: subscriptions × accounts
-- owner: @ricardo (finance)
-- classification: internal`}
    />
  </div>
);
