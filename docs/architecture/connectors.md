# Connectors — capability honesty and promotion bar

Every `Connector` declares two capability-honesty fields alongside its
`kind`, `capability`, and `classification_hints`:

- `status: ConnectorStatus` — one of `"production"`, `"preview"`,
  `"coming_soon"`.
- `status_note: str` — a short user-facing explanation (≤ 120 chars
  preferred, ≤ 200 enforced) shown verbatim in the dashboard's
  connector picker (D4) and in any "Coming soon" / "Preview" UX.

These fields exist because **connectors are surface area in the
onboarding wizard.** Skeletons returning empty discoveries are
proof-of-abstraction value, not bugs — but the picker UI must label
them honestly so a prospective user clicking "Notion" sees "Coming
soon — connector skeleton ready, full implementation in v1.5" instead
of an empty form that pretends to work.

## The three statuses

| Status | Definition | Picker UX |
|---|---|---|
| `production` | Every Connector method (`discover`, `profile`, `sample`, and `watch` where applicable) is wired against the real platform. Has at least one integration test against a real or recorded fixture. | Green `Production` pill. Card renders full color. Click → config form → real OAuth / connection flow. |
| `preview` | Some methods stubbed but enough is implemented to be useful (e.g. `discover` works, `sample` is bounded). The connector can be used at limited fidelity. | Amber `Preview` pill. Card renders full color. Click → config form prepended by an info banner explaining what works and what doesn't. |
| `coming_soon` | Skeleton only. `discover` returns `[]`; `profile`, `sample`, `watch` raise `NotImplementedError`. | Gray `Coming soon` pill. Card visually muted (50% opacity), `cursor: not-allowed`. Click → modal explaining the timeline + a "Notify me when ready" CTA. **Does NOT route to the config form.** |

## Promotion bar

A connector promotes to the next tier only when:

- **Skeleton → Preview**: at least one operational method (`discover`,
  `profile`, or `sample`) is wired against the real platform AND tested
  against a recorded fixture. The connector must be useful to an admin
  who connects it — even if only for the lineage view.
- **Preview → Production**: every Connector Protocol method is wired,
  AND there is at least one integration test against the real platform
  (gated behind a CI secret), AND the `not_implemented_reason` field is
  removed from the class.

## Day-one inventory (2026-04-26)

| Kind | Status | Notes |
|---|---|---|
| `csv_local` | production | Local-disk CSV; no network. Drop-and-profile entry point. |
| `postgres` | production | asyncpg; information_schema + pg_stat. |
| `snowflake` | production | snowflake-connector-python; INFORMATION_SCHEMA. |
| `s3_csv` | production | aioboto3; Range-bounded GetObject. |
| `http_csv` | production | httpx; Range-bounded GET. |
| `stripe` | production | httpx + REST; canonical object types. |
| `bigquery` | coming_soon | google-cloud-bigquery integration in v1.5. |
| `salesforce` | coming_soon | Connected App OAuth + describeSObject in v1.5. |
| `hubspot` | coming_soon | HubSpot CRM API in v1.5. |
| `gsheets` | coming_soon | Google Sheets API v4 in v1.5. |
| `notion` | coming_soon | Notion API in v1.5 (on-thesis priority). |
| `linear` | coming_soon | Linear GraphQL API in v1.5 (on-thesis priority). |

## Cross-language sync

The TS catalog at `apps/dashboard/lib/connectors-catalog.ts` mirrors
this metadata. When promoting a connector's status, update **both**
sides in the same change:

- Python: `packages/connectors/src/wormbase_connectors/<kind>.py` —
  the class-level `status` and `status_note`.
- TypeScript: `apps/dashboard/lib/connectors-catalog.ts` — the entry's
  `status` and `statusNote` fields.

Both sides have parametrized tests
(`packages/connectors/tests/test_connector_status.py` and
`apps/dashboard/tests/lib/connectors-catalog.test.ts`) that pin the
expected status per kind. The tests fail loudly on drift.
