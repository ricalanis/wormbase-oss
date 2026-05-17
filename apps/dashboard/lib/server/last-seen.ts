/**
 * Phase 3 Task 3A — "Since you logged off" boundary tracking.
 *
 * The Worm-Activity Digest Tile on /dashboard counts ledger events
 * since the current Person's last visit. Without a `Person.last_seen_at`
 * column on the projected `persons` table — and per the task scope:
 * "no new entry kinds, no new projections" — we track the boundary
 * via a per-tenant signed-session adjacent cookie.
 *
 * The boundary is **two-phase** per render:
 *
 *   1. On the first read of a session, return the previous value (so
 *      the digest reads "since you logged off"); on subsequent reads
 *      the value continues to advance.
 *   2. After the read, the cookie is bumped to "now" so the next
 *      visit reads from this session's most-recent timestamp.
 *
 * This is a UX session marker — it never writes to the ledger and
 * never affects any projection. If the cookie is missing the
 * digest falls back to "since install" (null sentinel), which is
 * the correct first-visit behavior.
 *
 * Cookie name: `wormbase-last-seen-{tenantSlug}` (per-tenant; switching
 * tenants is treated as a new session). HttpOnly, SameSite=Lax,
 * 30-day max age — long enough for daily users to keep a stable
 * boundary without leaking into multi-week silences.
 */
import { cookies } from "next/headers";

const COOKIE_PREFIX = "wormbase-last-seen-";
const MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

/**
 * Read the previous "last seen" timestamp for the given tenant, then
 * bump the cookie to "now". Returns the previous value or `null` if
 * this is the first visit on this device (no cookie yet).
 *
 * Safe to call from RSCs. Outside a request scope (static generation,
 * tests without next/headers), returns `null` and skips the bump.
 */
export async function readAndBumpLastSeen(
  tenantSlug: string,
  now: Date = new Date(),
): Promise<string | null> {
  let store: Awaited<ReturnType<typeof cookies>> | null;
  try {
    store = await cookies();
  } catch {
    return null;
  }
  if (!store) return null;
  const name = COOKIE_PREFIX + tenantSlug;
  const previous = store.get(name)?.value ?? null;
  const nowIso = now.toISOString();
  try {
    store.set({
      name,
      value: nowIso,
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: MAX_AGE_SECONDS,
    });
  } catch {
    // Some Next test harnesses run cookies() in read-only mode (RSC
    // outside an action). The previous value is still useful for the
    // current render; the next render will re-attempt the bump.
  }
  // Treat empty / malformed cookie values as "first visit" rather
  // than passing junk into the ledger query. The activity helper
  // accepts `null` and falls back to "since install".
  if (!previous) return null;
  // ISO-8601 sanity check — guard against tampered cookies.
  if (Number.isNaN(Date.parse(previous))) return null;
  return previous;
}
