import { NextResponse } from "next/server";
import { upsertChannelTalkativeness } from "../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import type { Talkativeness } from "../../../../lib/ledger-client.types";

export async function POST(req: Request) {
  const body = (await req.json()) as {
    channelId: string;
    talkativeness: Talkativeness;
  };
  const companyId = await getCurrentCompanyId();
  const receipt = await upsertChannelTalkativeness(
    companyId,
    body.channelId,
    body.talkativeness
  );
  return NextResponse.json({ ok: true, receipt });
}
