/**
 * Hardcoded connector catalog for the dashboard's /sources/new picker.
 *
 * D4 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * Cross-language schema sync (Python registry → TS picker) is post-
 * Thursday. For now this list is the source of truth for the picker UI
 * only — actual source connection still happens via the Python
 * connectors registry on the worm-core side. The 12 day-one kinds
 * mirror packages/connectors/src/wormbase_connectors/ exactly:
 *
 *   csv_local, postgres, snowflake, bigquery, s3_csv, http_csv,
 *   stripe, salesforce, hubspot, gsheets, notion, linear
 *
 * IMPORTANT — capability honesty: each entry carries a ``status``
 * ("production" | "preview" | "coming_soon") + a ``statusNote``. These
 * MUST be kept in sync with the Python ``Connector.status`` /
 * ``Connector.status_note`` declarations. If you promote a skeletal
 * connector to production, update both sides in the same change.
 *
 * Status grading:
 *   - production: every Connector method (discover, profile, sample,
 *     watch where applicable) is wired against the real platform.
 *   - preview: some methods stubbed but enough is implemented to be
 *     useful (e.g. discover works but sample is bounded).
 *   - coming_soon: skeleton only; discover returns []; profile/sample
 *     raise NotImplementedError. Picker mutes the card and routes to a
 *     "Notify me" modal instead of the config form.
 */

export type CapabilityFlag = "discover" | "profile" | "sample" | "watch";

export type ConnectorStatus = "production" | "preview" | "coming_soon";

export interface ConnectorJsonField {
  name: string;
  label: string;
  type: "string" | "password" | "number" | "boolean";
  required?: boolean;
  placeholder?: string;
  description?: string;
}

export interface ConnectorCatalogEntry {
  kind: string;
  label: string;
  description: string;
  capabilities: CapabilityFlag[];
  fields: ConnectorJsonField[];
  status: ConnectorStatus;
  statusNote: string;
  /**
   * @deprecated Use ``status`` instead. Retained for back-compat with
   * existing tests and props that already key off this boolean — true
   * when status === "production", false otherwise.
   */
  ready: boolean;
}

export const CONNECTOR_CATALOG: ConnectorCatalogEntry[] = [
  {
    kind: "csv_local",
    label: "Local CSV file",
    description:
      "A CSV file dropped in a worm-watched channel or attached via the dashboard. PII filename hints flagged automatically.",
    capabilities: ["discover", "profile", "sample"],
    fields: [
      {
        name: "path",
        label: "File path",
        type: "string",
        required: true,
        placeholder: "/lake/raw/sales-q3.csv",
      },
    ],
    status: "production",
    statusNote:
      "Drop a file in any worm-watched channel; we profile it on landing.",
    ready: true,
  },
  {
    kind: "postgres",
    label: "Postgres",
    description:
      "Any Postgres-compatible database. Discovery walks information_schema; profiling reads pg_stat for cheap row counts.",
    capabilities: ["discover", "profile", "sample"],
    fields: [
      {
        name: "dsn",
        label: "DSN",
        type: "password",
        required: true,
        placeholder: "postgres://user:pass@host:5432/db",
      },
    ],
    status: "production",
    statusNote:
      "Production-grade. Discover walks information_schema; profile reads pg_stat; sample via SELECT … LIMIT n.",
    ready: true,
  },
  {
    kind: "snowflake",
    label: "Snowflake",
    description:
      "Warehouse-grade analytics source. Connector samples via SQL LIMIT; rows-on-disk via INFORMATION_SCHEMA.",
    capabilities: ["discover", "profile", "sample"],
    fields: [
      { name: "account", label: "Account", type: "string", required: true },
      { name: "username", label: "Username", type: "string", required: true },
      { name: "password", label: "Password", type: "password", required: true },
      { name: "database", label: "Database", type: "string", required: true },
      { name: "warehouse", label: "Warehouse", type: "string", required: false },
    ],
    status: "production",
    statusNote:
      "Production-grade. Discover via INFORMATION_SCHEMA.TABLES; profile + sample via the snowflake-connector-python executor bridge.",
    ready: true,
  },
  {
    kind: "bigquery",
    label: "BigQuery",
    description:
      "Google Cloud BigQuery. Service-account JSON for auth; discovery walks INFORMATION_SCHEMA.TABLES.",
    capabilities: ["discover", "profile", "sample"],
    fields: [
      { name: "project_id", label: "Project ID", type: "string", required: true },
      {
        name: "service_account_json",
        label: "Service account JSON",
        type: "password",
        required: true,
      },
    ],
    status: "coming_soon",
    statusNote:
      "Connector skeleton — google-cloud-bigquery integration lands in v1.5.",
    ready: false,
  },
  {
    kind: "s3_csv",
    label: "S3 CSV",
    description:
      "CSV files in an S3 bucket (or S3-compatible store). Profiling reads object metadata + first-N rows.",
    capabilities: ["discover", "profile", "sample"],
    fields: [
      { name: "bucket", label: "Bucket", type: "string", required: true },
      { name: "prefix", label: "Prefix", type: "string", required: false },
      { name: "access_key_id", label: "Access key id", type: "password", required: true },
      { name: "secret_access_key", label: "Secret access key", type: "password", required: true },
    ],
    status: "production",
    statusNote:
      "Production-grade. Discover lists CSV/CSV.gz keys via list_objects_v2; profile + sample via Range-bounded GetObject.",
    ready: true,
  },
  {
    kind: "http_csv",
    label: "HTTP CSV",
    description:
      "A CSV exposed at an HTTP(S) URL — public statistics, internal tools, etc. No discovery; one resource per URL.",
    capabilities: ["profile", "sample"],
    fields: [
      { name: "url", label: "URL", type: "string", required: true },
      {
        name: "auth_header",
        label: "Auth header (optional)",
        type: "password",
        required: false,
      },
    ],
    status: "production",
    statusNote:
      "Production-grade. One URL = one resource; profile + sample via Range-bounded GET.",
    ready: true,
  },
  {
    kind: "stripe",
    label: "Stripe",
    description:
      "SaaS API connector for payments + invoices. Discovery enumerates the Stripe object types; profiling samples /list endpoints.",
    capabilities: ["discover", "profile", "sample", "watch"],
    fields: [
      { name: "api_key", label: "API key", type: "password", required: true },
    ],
    status: "production",
    statusNote:
      "Production-grade. Discover enumerates Stripe object types; profile + sample via the canonical /v1/<object> list endpoints.",
    ready: true,
  },
  {
    kind: "salesforce",
    label: "Salesforce",
    description:
      "CRM data via Salesforce REST API. OAuth required; discovery walks /sobjects.",
    capabilities: ["discover", "profile", "sample"],
    fields: [
      { name: "instance_url", label: "Instance URL", type: "string", required: true },
      { name: "access_token", label: "Access token", type: "password", required: true },
    ],
    status: "coming_soon",
    statusNote:
      "Connector skeleton — Connected App OAuth + describeSObject lands in v1.5.",
    ready: false,
  },
  {
    kind: "hubspot",
    label: "HubSpot",
    description:
      "Marketing + CRM data via HubSpot API. Discovery walks /properties; profiling reads /list.",
    capabilities: ["discover", "profile", "sample"],
    fields: [
      { name: "api_key", label: "API key", type: "password", required: true },
    ],
    status: "coming_soon",
    statusNote:
      "Connector skeleton — HubSpot CRM API integration lands in v1.5.",
    ready: false,
  },
  {
    kind: "gsheets",
    label: "Google Sheets",
    description:
      "A specific Google Sheet, by spreadsheet ID. Service-account auth.",
    capabilities: ["profile", "sample"],
    fields: [
      { name: "spreadsheet_id", label: "Spreadsheet ID", type: "string", required: true },
      {
        name: "service_account_json",
        label: "Service account JSON",
        type: "password",
        required: true,
      },
    ],
    status: "coming_soon",
    statusNote:
      "Connector skeleton — Google Sheets API v4 integration lands in v1.5.",
    ready: false,
  },
  {
    kind: "notion",
    label: "Notion",
    description:
      "Notion databases via Notion API. Discovery enumerates accessible databases; profiling reads schemas.",
    capabilities: ["discover", "profile", "sample"],
    fields: [
      { name: "integration_token", label: "Integration token", type: "password", required: true },
    ],
    status: "coming_soon",
    statusNote:
      "Connector skeleton — Notion API integration lands in v1.5 (on-thesis priority).",
    ready: false,
  },
  {
    kind: "linear",
    label: "Linear",
    description:
      "Linear issues, cycles, and projects via the Linear GraphQL API. Captures issue-tracker signal as a first-class data source.",
    capabilities: ["discover", "profile", "sample"],
    fields: [
      { name: "api_key", label: "API key", type: "password", required: true },
    ],
    status: "coming_soon",
    statusNote:
      "Connector skeleton — Linear GraphQL API integration lands in v1.5 (on-thesis priority).",
    ready: false,
  },
];

export function getConnectorByKind(
  kind: string,
): ConnectorCatalogEntry | undefined {
  return CONNECTOR_CATALOG.find((c) => c.kind === kind);
}
