import "../styles.css";
import { Card } from "./Card";

export const Default = () => (
  <div style={{ maxWidth: 520 }}>
    <Card title="Domains">
      <p style={{ margin: 0 }}>
        Two domains currently resolved: <em>Product</em> (owner @alice) and{" "}
        <em>Finance</em> (owner @ricardo). Classifications inherit from domain
        defaults.
      </p>
    </Card>
  </div>
);

export const WithEyebrow = () => (
  <div style={{ maxWidth: 520 }}>
    <Card eyebrow="PROJECTION · ramp" title="Ontology">
      <p style={{ margin: 0 }}>
        34% — 17 concepts confirmed of 50 seeded. Gaps: <em>dunning</em>,{" "}
        <em>cohort</em>, <em>churn vintage</em>.
      </p>
    </Card>
  </div>
);

export const Dense = () => (
  <div style={{ maxWidth: 520 }}>
    <Card density="dense" title="Today's gate fires">
      <ul style={{ margin: 0, paddingLeft: 20 }}>
        <li>pii_redaction fired on answer #c0ffee</li>
        <li>interjection_budget fired in #data (4→3 remaining)</li>
      </ul>
    </Card>
  </div>
);
