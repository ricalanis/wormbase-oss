import {
  getOntologySeeds,
  getPeople,
  getPiiPatterns,
} from "../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";
import { Tier3Client } from "./Tier3Client";

export const metadata = { title: "WormBase · Onboarding Tier 3" };

export default async function Tier3Page() {
  const companyId = await getCurrentCompanyId();
  const [pii, people, seeds] = await Promise.all([
    getPiiPatterns(companyId),
    getPeople(companyId),
    getOntologySeeds(companyId),
  ]);
  return <Tier3Client pii={pii} people={people} seeds={seeds} />;
}
