import "../styles.css";
import { Select } from "./Select";

const templates = [
  { value: "saas", label: "SaaS" },
  { value: "marketplace", label: "Marketplace" },
  { value: "fintech", label: "Fintech" },
];

export const Default = () => (
  <div style={{ maxWidth: 420 }}>
    <Select label="KPI tree template" options={templates} defaultValue="saas" />
  </div>
);

export const WithHelper = () => (
  <div style={{ maxWidth: 420 }}>
    <Select
      label="KPI tree template"
      options={templates}
      helperText="Templates seed the ontology. You can adjust later in Tier 2."
    />
  </div>
);
