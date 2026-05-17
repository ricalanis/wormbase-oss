/**
 * HeroDemo — Phase 4 Task 4B replay-in-browser viewer (server entry).
 *
 * The above-the-fold visualization on the landing page. Replaces the
 * Phase 4A static placeholder. Visitors REPLAY a recorded tenant
 * session in-browser and see hash-receipted outputs; clicking "Replay
 * again" re-fires the SSR replay and lands on identical hashes — that
 * is the institutional-AI thesis demonstrated, not asserted.
 *
 * Composition:
 *
 *   - This server component reads a deterministic replay payload via
 *     ``getLandingReplay()`` (canonical demo tenant, fixed
 *     ``until_ts`` window) and hands it to ``HeroDemoClient``.
 *   - The client component scrubs through the payload as a
 *     Slack-thread-style stream, with each row's hash receipt visible.
 *   - The "Replay again" button refetches the same SSR payload at
 *     ``/api/v1/landing/replay`` to demonstrate hash-stability.
 *
 * Demo-tenant note (concern flagged in 4B brief): the helper uses the
 * canonical ``baseworm`` tenant — the one ``make seed`` populates. The
 * 1B.G ``--demo-tenants`` carousel tenants exist for the magic-link
 * flow but carry no chat traffic, so they're not the right fit for a
 * thread preview. If ``baseworm`` has not been seeded, the helper
 * falls back to a deterministic synthesised payload derived from the
 * demo-fixture ``TRACE_ENTRIES`` — same hash semantics.
 */
import { getLandingReplay } from "../../lib/server/landing-replay";
import { HeroDemoClient } from "./HeroDemoClient";

export async function HeroDemo() {
  const replay = await getLandingReplay();
  return <HeroDemoClient initial={replay} />;
}
