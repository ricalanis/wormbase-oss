/**
 * Opaque-secret connector classification.
 *
 * Mirrors ``wormbase_core.source_handle_provider.OPAQUE_AUTH_HANDLE_ASSEMBLERS``
 * (the Python registry that classifies which connector kinds need a
 * ``CredentialBroker``-resolved secret payload at sampling time vs which
 * reconstruct from the proposed URI alone).
 *
 * Drift-pinned: when the Python registry adds a new opaque-secret
 * connector kind (e.g. ``notion``, ``linear``, ``mcp:*``), append it
 * here too. The dashboard ``CredentialRefInput`` component renders only
 * when the configured kind is in this set, so a drift would silently
 * leave new opaque kinds without an operator UI to paste their broker
 * slot key. Tracked by ``tests/unit/opaque-secret-connectors.test.ts``.
 *
 * URI-shaped connectors (``csv_local``, ``postgres``, ``snowflake``,
 * ``bigquery``, ``s3_csv``, ``http_csv``) are intentionally NOT in this
 * set — their auth handle is reconstructable from the proposed URI and
 * they never call the broker.
 */

export const OPAQUE_SECRET_CONNECTOR_KINDS = [
  "stripe",
  "salesforce",
  "hubspot",
  "gsheets",
] as const;

export type OpaqueSecretConnectorKind =
  (typeof OPAQUE_SECRET_CONNECTOR_KINDS)[number];

export function isOpaqueSecretKind(
  kind: string | null | undefined
): kind is OpaqueSecretConnectorKind {
  if (!kind) return false;
  return (OPAQUE_SECRET_CONNECTOR_KINDS as readonly string[]).includes(kind);
}
