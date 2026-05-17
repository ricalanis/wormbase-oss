import "../styles.css";
import { Page } from "./Page";
import { Card } from "./Card";

export const Empty = () => (
  <Page subtitle="dashboard · day 0">
    <Card title="Nothing here yet">
      <p style={{ margin: 0 }}>
        The lake is empty. Drop a file in #data, DM me credentials, or mention
        a data source in channel — I'll wire things up as I go.
      </p>
    </Card>
  </Page>
);

export const WithHeaderRight = () => (
  <Page
    subtitle="dashboard · day 7"
    headerRight={
      <span
        className="wb-mono"
        style={{ fontSize: 12, color: "var(--wb-color-hash-gray)" }}
      >
        tenant / democorp · ledger /#a3f9c2
      </span>
    }
  >
    <Card eyebrow="PROJECTION" title="Knowledge ramp">
      <p style={{ margin: 0 }}>Six axes, six gauges. Breathing, not blinking.</p>
    </Card>
  </Page>
);
