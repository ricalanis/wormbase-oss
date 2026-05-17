import {
  getProposedBusinessDefs,
  getChannels,
  getDomains,
  getPeople,
} from "../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";
import { Tier2Client } from "./Tier2Client";

export const metadata = { title: "WormBase · Onboarding Tier 2" };

export default async function Tier2Page() {
  const companyId = await getCurrentCompanyId();
  const [defs, channels, domains, people] = await Promise.all([
    getProposedBusinessDefs(companyId),
    getChannels(companyId),
    getDomains(companyId),
    getPeople(companyId),
  ]);
  return (
    <Tier2Client
      defs={defs}
      channels={channels}
      domains={domains}
      people={people}
    />
  );
}
