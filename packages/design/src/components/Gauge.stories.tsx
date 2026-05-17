import "../styles.css";
import { Gauge } from "./Gauge";

export const Single = () => (
  <div style={{ padding: 40 }}>
    <Gauge label="Ontology" value={34} staggerIndex={0} />
  </div>
);

export const SixAxis = () => (
  <div
    style={{
      display: "grid",
      gridTemplateColumns: "repeat(3, 1fr)",
      gap: 24,
      padding: 40,
    }}
  >
    {[
      ["Ontology", 18],
      ["Schema", 22],
      ["Business Definitions", 14],
      ["KPI Relational", 28],
      ["Conversational", 10],
      ["Operational", 12],
    ].map(([label, value], i) => (
      <Gauge
        key={label as string}
        label={label as string}
        value={value as number}
        staggerIndex={i}
      />
    ))}
  </div>
);

export const Full = () => (
  <div style={{ padding: 40 }}>
    <Gauge label="Reproducibility" value={100} instant />
  </div>
);
