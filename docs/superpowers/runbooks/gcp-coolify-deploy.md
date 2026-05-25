# GCP + Coolify Cloud Deploy Runbook

> One-tenant production substrate for WormBase on Google Cloud, managed via
> Coolify Cloud (or any remote Coolify). Reusable for any fork — every value
> is parameterised.
>
> Footprint: ~2 GB RAM, <1 vCPU steady. **~$40/mo** (no credits); free for
> ~7 months on standard GCP $300 trial credit.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│ GCP project: ${GCP_PROJECT}                                      │
│ Region:      ${GCP_REGION}      Zone: ${GCP_ZONE}                │
│                                                                  │
│   ┌─────────────────────────┐    ┌──────────────────────────┐    │
│   │ Compute Engine VM       │    │ Cloud SQL Postgres 16    │    │
│   │ wormbase-prod           │◀──▶│ wormbase-prod-db         │    │
│   │ e2-medium · debian-12   │    │ db-f1-micro · private IP │    │
│   │ Docker via Coolify      │    │ pgvector 0.8.x · PITR    │    │
│   │ static ext IP           │    └──────────────────────────┘    │
│   └─────────────────────────┘    ┌──────────────────────────┐    │
│       ▲                          │ GCS bucket               │    │
│       │ ssh (key auth)           │ gs://${OBJECT_BUCKET}    │    │
│       │                          │ object storage           │    │
│       │                          └──────────────────────────┘    │
│       │                          ┌──────────────────────────┐    │
│       │                          │ Secret Manager           │    │
│       │                          │ wormbase-prod-*          │    │
│       │                          └──────────────────────────┘    │
└───────┼──────────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────┐
│ Coolify Cloud        │  ← git push to ricalanis/wormbase-oss triggers deploy
│ (managed, off-VM)    │
└──────────────────────┘
```

External SaaS (unchanged by this deploy): Slack, WhatsApp (via OpenClaw),
Kimi/Ollama Cloud, ElevenLabs, Fireflies, Read.AI.

---

## Prerequisites

- A GCP project with billing enabled. ($300 trial credit is enough.)
- `gcloud` CLI installed + authenticated as a project owner.
- A managed Coolify account (Coolify Cloud, or self-hosted — same UX).
- An SSH key registered in Coolify (the same one you use for any other server).
- The OSS repo forked / cloned. This guide assumes `github.com/ricalanis/wormbase-oss`.

---

## Step 0 — Set defaults for everything

Pick your project ID and region. The guide uses these placeholders; substitute
your own throughout. (`us-central1` is a reasonable default for North-America
deploys; `us-central1-b` is the cheapest zone with broad service availability.)

```bash
export GCP_PROJECT=your-project-id
export GCP_REGION=us-central1
export GCP_ZONE=us-central1-b

gcloud config set project "$GCP_PROJECT"
gcloud config set compute/region "$GCP_REGION"
gcloud config set compute/zone "$GCP_ZONE"
```

Confirm billing is on:

```bash
gcloud billing projects describe "$GCP_PROJECT" --format="value(billingEnabled)"
# expected: True
```

Enable the APIs:

```bash
gcloud services enable \
  compute.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  cloudresourcemanager.googleapis.com \
  servicenetworking.googleapis.com
```

---

## Step 1 — Reserve a static external IP

WhatsApp's Baileys pairing and ElevenLabs webhooks both hit your VM by IP /
hostname. A static IP means re-pairing isn't required across reboots.

```bash
gcloud compute addresses create wormbase-prod-ip \
  --region "$GCP_REGION" \
  --description "Static external IP for wormbase-prod VM"

# Capture the IP:
export VM_EXTERNAL_IP=$(gcloud compute addresses describe wormbase-prod-ip \
  --region "$GCP_REGION" --format="value(address)")
echo "VM external IP: $VM_EXTERNAL_IP"
```

---

## Step 2 — Set up private services access (for Cloud SQL private IP)

This puts Cloud SQL on a VPC-peered private range — no public Postgres
exposure. The VM and Postgres talk over Google's internal backbone.

```bash
gcloud compute addresses create wormbase-sql-private-range \
  --global --purpose=VPC_PEERING --prefix-length=20 --network=default \
  --description "Reserved range for Cloud SQL private services access"

gcloud services vpc-peerings connect \
  --service=servicenetworking.googleapis.com \
  --ranges=wormbase-sql-private-range \
  --network=default
```

---

## Step 3 — Provision Cloud SQL Postgres (takes 5-10 min)

```bash
# Generate a strong root password
SQL_ROOT_PASSWORD=$(openssl rand -base64 24 | tr -d "=+/")

gcloud sql instances create wormbase-prod-db \
  --database-version=POSTGRES_16 \
  --edition=ENTERPRISE \
  --tier=db-f1-micro \
  --region="$GCP_REGION" \
  --network=default \
  --no-assign-ip \
  --root-password="$SQL_ROOT_PASSWORD" \
  --storage-type=SSD \
  --storage-size=10GB \
  --backup \
  --backup-start-time=08:00 \
  --enable-point-in-time-recovery \
  --async

# Wait for it to come up (poll every ~30s):
while [ "$(gcloud sql instances describe wormbase-prod-db --format='value(state)')" != "RUNNABLE" ]; do
  echo "Cloud SQL state: $(gcloud sql instances describe wormbase-prod-db --format='value(state)') — waiting..."
  sleep 30
done

# Grab the private IP
export SQL_PRIVATE_IP=$(gcloud sql instances describe wormbase-prod-db \
  --format="value(ipAddresses[0].ipAddress)")
echo "Cloud SQL private IP: $SQL_PRIVATE_IP"
```

Stash the root password in Secret Manager immediately:

```bash
echo -n "$SQL_ROOT_PASSWORD" | \
  gcloud secrets create wormbase-prod-db-root-password \
    --replication-policy=automatic --data-file=-
```

---

## Step 4 — Create the wormbase database + user

```bash
# Strong per-app user password
DB_USER_PASSWORD=$(openssl rand -base64 24 | tr -d "=+/")

# Database + user
gcloud sql databases create wormbase --instance=wormbase-prod-db
gcloud sql users create wormbase --instance=wormbase-prod-db \
  --password="$DB_USER_PASSWORD"

# Stash + compose DSN
echo -n "$DB_USER_PASSWORD" | \
  gcloud secrets create wormbase-prod-db-user-password \
    --replication-policy=automatic --data-file=-

WORMBASE_DSN="postgresql+asyncpg://wormbase:${DB_USER_PASSWORD}@${SQL_PRIVATE_IP}:5432/wormbase"
echo -n "$WORMBASE_DSN" | \
  gcloud secrets create wormbase-prod-ledger-dsn \
    --replication-policy=automatic --data-file=-
```

(Postgres extension + schema-ownership grants are done from the VM in step 9 —
they need a Postgres client and the VM is the easiest place to install one.)

---

## Step 5 — Other Google-side substrate

```bash
# Object storage (replaces LocalStack)
gcloud storage buckets create gs://wormbase-prod-objects \
  --location="$GCP_REGION" \
  --uniform-bucket-level-access \
  --public-access-prevention

# Artifact Registry (for container images if you build remotely later)
gcloud artifacts repositories create wormbase \
  --repository-format=docker --location="$GCP_REGION" \
  --description="WormBase production container images"
```

---

## Step 6 — Firewall (SSH-only; everything else via Coolify's tunnel)

We open SSH from Cloud IAP for ops emergencies AND from the public internet for
Coolify Cloud (key-only — Debian disables password auth by default).

```bash
# IAP-only SSH for ops console access
gcloud compute firewall-rules create wormbase-iap-ssh \
  --direction=INGRESS --action=ALLOW --rules=tcp:22 \
  --source-ranges=35.235.240.0/20 \
  --target-tags=wormbase-prod \
  --description="Allow SSH via Cloud IAP (ops)"

# Public SSH for Coolify Cloud (key-only auth by OS default)
gcloud compute firewall-rules create wormbase-public-ssh \
  --direction=INGRESS --action=ALLOW --rules=tcp:22 \
  --source-ranges=0.0.0.0/0 \
  --target-tags=wormbase-prod \
  --description="Coolify Cloud SSH deploys"
```

If you have specific Coolify Cloud source IPs, narrow the public rule. Coolify's
docs publish their egress IPs when available.

---

## Step 7 — Provision the VM

```bash
gcloud compute instances create wormbase-prod \
  --zone="$GCP_ZONE" \
  --machine-type=e2-medium \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=50GB \
  --boot-disk-type=pd-balanced \
  --boot-disk-device-name=wormbase-prod-boot \
  --address=wormbase-prod-ip \
  --tags=wormbase-prod \
  --metadata=enable-oslogin=FALSE \
  --scopes=https://www.googleapis.com/auth/cloud-platform \
  --description="WormBase production"
```

**Why `enable-oslogin=FALSE`:** Coolify Cloud uses plain SSH key auth against
`/root/.ssh/authorized_keys`. OS Login requires Google-issued SSH certs that
Coolify doesn't support.

---

## Step 8 — Install Docker + enable root SSH key auth

SSH in via IAP (no public SSH key needed yet):

```bash
gcloud compute ssh wormbase-prod --tunnel-through-iap --zone="$GCP_ZONE" \
  --command="curl -fsSL https://get.docker.com | sudo sh && sudo systemctl enable --now docker && docker --version"
```

Enable root SSH login (key-only — Debian default `PermitRootLogin no` is too strict for Coolify):

```bash
gcloud compute ssh wormbase-prod --tunnel-through-iap --zone="$GCP_ZONE" --command="
sudo sed -i 's/^PermitRootLogin no/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sudo systemctl restart ssh
sudo mkdir -p /root/.ssh && sudo chmod 700 /root/.ssh
sudo sh -c '> /root/.ssh/authorized_keys'
"
```

Add the Coolify SSH public key (paste your key in place of the placeholder):

```bash
COOLIFY_PUB_KEY="ssh-ed25519 AAAA... your-coolify-key-here"
gcloud compute ssh wormbase-prod --tunnel-through-iap --zone="$GCP_ZONE" --command="
sudo sh -c 'echo \"$COOLIFY_PUB_KEY\" > /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys'
"
```

**Where to get the Coolify public key:** in your Coolify dashboard, go to
**Settings → Private Keys**, open the key you'll use, copy the **public** half.
If Coolify only shows the private key, derive the public locally with
`ssh-keygen -y -f path/to/private.key`.

---

## Step 9 — Enable pgvector + transfer schema ownership

From the VM (it has private-IP access to Cloud SQL):

```bash
SQL_ROOT_PASSWORD=$(gcloud secrets versions access latest --secret=wormbase-prod-db-root-password)
SQL_PRIVATE_IP=$(gcloud sql instances describe wormbase-prod-db --format="value(ipAddresses[0].ipAddress)")

gcloud compute ssh wormbase-prod --tunnel-through-iap --zone="$GCP_ZONE" --command="
sudo apt-get update -qq && sudo apt-get install -y -qq postgresql-client
PGPASSWORD='$SQL_ROOT_PASSWORD' psql -h $SQL_PRIVATE_IP -U postgres -d wormbase <<'EOF'
CREATE EXTENSION IF NOT EXISTS vector;
GRANT wormbase TO postgres;
ALTER SCHEMA public OWNER TO wormbase;
GRANT ALL ON SCHEMA public TO wormbase;
GRANT CREATE ON DATABASE wormbase TO wormbase;
EOF
"
```

Verify (should print `vector` extension version + `wormbase` as the current user):

```bash
DB_USER_PASSWORD=$(gcloud secrets versions access latest --secret=wormbase-prod-db-user-password)
gcloud compute ssh wormbase-prod --tunnel-through-iap --zone="$GCP_ZONE" --command="
PGPASSWORD='$DB_USER_PASSWORD' psql -h $SQL_PRIVATE_IP -U wormbase -d wormbase \
  -c '\\\\dx vector' -c 'SELECT current_user, current_database();'
"
```

---

## Step 10 — Add the VM to Coolify Cloud

In the Coolify dashboard:

1. **Servers → + Add Server → Add Server by IP Address**
2. Fill in:
   - **Name:** `wormbase-prod-gcp` (or anything memorable)
   - **IP Address:** the value of `$VM_EXTERNAL_IP` from Step 1
   - **Port:** `22`
   - **User:** `root`
   - **Private Key:** the same one whose public half you installed in Step 8
3. Click **Continue**, then **Validate Server**.

Coolify should report Docker version, kernel info, and disk usage. If
validation fails:

- **"Permission denied (publickey)"** — the public key in `/root/.ssh/authorized_keys` doesn't match the Coolify private key. Re-do Step 8.
- **"Connection refused"** — public SSH firewall rule (Step 6) didn't land. Verify with `gcloud compute firewall-rules list --filter='name~wormbase'`.
- **"Docker not found"** — Step 8 first half (the `get.docker.com` install) didn't run successfully.

---

## Step 11 — Create the WormBase project in Coolify

1. **Projects → + New Project**
   - Name: `wormbase-prod`
2. **+ New Resource** → **Private Repository (with GitHub App)** (use the GitHub App you've registered in Coolify; if none, register one against `${GITHUB_REPO}`)
   - Server: `wormbase-prod-gcp`
   - Repository: `${GITHUB_REPO}` (e.g. `your-org/wormbase-oss`)
   - Branch: `main`
   - Build Pack: **Docker Compose**
   - Docker Compose Location: `infra/docker-compose.yml`
3. Coolify parses the compose and lists the services.

### 11a — Suspend the services we don't need

Toggle **Exclude from Deployment** on:

| Service | Reason |
|---|---|
| `postgres` | Cloud SQL replaces it |
| `vault` | Secret Manager replaces it |
| `hermes` | Profile-gated; safe to suspend |
| `channel-adapter-hermes-spike` | Companion to hermes |
| `localstack` | GCS replaces it |
| `localstack-init` | Companion to localstack |
| `sim-harness` | Dev/test only |
| `tunnel` | Coolify owns ingress |

Keep enabled: `openclaw`, `worm-core`, `channel-adapter`, `voice-agent`, `dashboard`.

### 11b — Set environment variables

Go to **Environment Variables** for the project and add:

```
# Required — connection to your Cloud SQL Postgres
WORMBASE_LEDGER_DSN=<paste output of: gcloud secrets versions access latest --secret=wormbase-prod-ledger-dsn>

# Required — tenant + silent mode
WORMBASE_TENANT_ID=<your-tenant-slug>
WORMBASE_SILENT_MODE=1

# Required — operational tokens
OPENCLAW_ADMIN_TOKEN=<generate-strong-random>
WORMBASE_LEDGER_API_TOKEN=<generate-strong-random>
OLLAMA_API_KEY=<your-ollama-cloud-key>

# Object storage (the worm-core code uses boto3 against an S3-compatible endpoint;
# Sprint 2: swap to native GCS client. For now LocalStack vars work locally and you
# can point boto3 at GCS S3-compat via storage.googleapis.com if you wire HMAC keys)
WORMBASE_OBJECT_STORE_URI=gs://wormbase-prod-objects/

# WhatsApp tenant block (substitute your tenant slug in the var names)
WHATSAPP_ENABLED_<TENANT_UPPER>=true
WHATSAPP_DM_POLICY_<TENANT_UPPER>=pairing
WHATSAPP_GROUP_POLICY_<TENANT_UPPER>=allowlist
WHATSAPP_GROUP_ALLOW_FROM_<TENANT_UPPER>=<group-jid-once-known>
WORMBASE_WHATSAPP_BOT_PHONE_<TENANT_UPPER>=<your-bot-e164-without-plus>
WHATSAPP_ACCOUNT_ID=default

# Optional — L1 source-candidate discovery
WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED=1
WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_ENABLED=1
WORMBASE_SOURCE_CANDIDATE_CHANNEL_MENTION_WINDOW=604800
```

### 11c — Handle the `depends_on: postgres` declarations

Three services (`worm-core`, `channel-adapter`, `voice-agent`) have
`depends_on: postgres: condition: service_healthy` in the compose. Since you've
suspended `postgres`, Coolify needs to skip this dependency. Most Coolify
versions handle this automatically for suspended services. If a deploy
fails with a dependency error, either:

- Edit the compose at deploy time in Coolify's UI to remove the postgres dependency lines, OR
- Push a follow-up commit that wraps the `depends_on` blocks in a profile.

### 11d — Deploy

Click **Deploy**. First build is 10-15 min (Python + Node images, dashboard
npm install). Watch logs in Coolify. When green, smoke-test from a Coolify
terminal (or `gcloud compute ssh wormbase-prod --tunnel-through-iap`):

```bash
docker ps
# Should list: wormbase-openclaw, wormbase-worm-core, wormbase-channel-adapter,
# wormbase-voice-agent, dashboard

docker exec wormbase-worm-core uv run wormbase-ledger-recent --tenant <slug> --limit 5
# Should connect to Cloud SQL and return empty initially.
```

---

## Operational notes

### Re-deploys

Coolify watches the branch and auto-deploys on push (if you enabled the
webhook). Otherwise click **Redeploy** in the dashboard.

### Where the secrets are

| Secret | Source of truth |
|---|---|
| Postgres root password | `gcloud secrets versions access latest --secret=wormbase-prod-db-root-password` |
| Postgres app-user password | `gcloud secrets versions access latest --secret=wormbase-prod-db-user-password` |
| Full DSN | `gcloud secrets versions access latest --secret=wormbase-prod-ledger-dsn` |
| All other tokens (Slack, Ollama, WhatsApp pairing, etc.) | Coolify's Environment Variables UI |

### Backups + survivability

- Cloud SQL: daily backups at 08:00 UTC + point-in-time recovery to any moment in the last 7 days. Configured in Step 3.
- VM disk: no automatic snapshots. If the VM dies, re-run Steps 7-9 and re-deploy via Coolify; the ledger data is safe in Cloud SQL.
- WhatsApp pairing: lives in the `openclaw-state` Docker volume on the VM. If the VM dies, you re-pair — which means scanning a QR code on your bot phone. Plan accordingly.

### Costs

| Resource | Monthly (no credits) |
|---|---|
| VM (e2-medium 24/7) | ~$24 |
| Cloud SQL (db-f1-micro + 10GB SSD + backups) | ~$11 |
| Static IP (in-use) | $0 |
| GCS bucket (low traffic) | <$1 |
| Secret Manager (few secrets) | <$1 |
| Network egress (modest) | ~$3-5 |
| **Total** | **~$40/mo** |

With standard GCP $300 trial credit: ~7 months free.

### When to scale up

- **>10 tenants on this VM** — split. Move worm-core to its own machine; bump Cloud SQL tier; consider regional read replicas.
- **WhatsApp scaling** — OpenClaw 2026.5.x is single-account-WhatsApp per process. Each WhatsApp tenant needs its own OpenClaw container, which means either multiple compose stacks on the VM or multiple VMs.
- **Heavy transcript ingestion** (hundreds/day) — embedding-backfill becomes the hot path; bump VM to e2-standard-2.

---

## Tear-down (if you need it)

```bash
# In reverse order of creation:
gcloud compute instances delete wormbase-prod --zone="$GCP_ZONE" --quiet
gcloud sql instances delete wormbase-prod-db --quiet
gcloud compute firewall-rules delete wormbase-iap-ssh wormbase-public-ssh --quiet
gcloud compute addresses delete wormbase-prod-ip --region="$GCP_REGION" --quiet
gcloud compute addresses delete wormbase-sql-private-range --global --quiet
gcloud storage buckets delete gs://wormbase-prod-objects --quiet
gcloud artifacts repositories delete wormbase --location="$GCP_REGION" --quiet
gcloud secrets delete wormbase-prod-db-root-password --quiet
gcloud secrets delete wormbase-prod-db-user-password --quiet
gcloud secrets delete wormbase-prod-ledger-dsn --quiet
gcloud secrets delete wormbase-prod-coolify-env --quiet  # if created earlier
gcloud services vpc-peerings delete --service=servicenetworking.googleapis.com --network=default --quiet
```

Then remove the server from Coolify and delete the project.

---

## Cross-references

- Kickoff runbook (per-customer): `docs/superpowers/runbooks/2026-05-25-altis-kickoff-runbook.md`
- Source-connector catalogue: `docs/superpowers/runbooks/source-connector-cheatsheet.md`
- Weekly-report template: `docs/superpowers/runbooks/weekly-report-template.md`
- Silent-mode spec: `docs/superpowers/specs/2026-05-18-silent-mode-design.md`
- Agent-driven lake extension (Sprint 2+): `docs/superpowers/specs/2026-05-23-agent-driven-lake-extension-design.md`
