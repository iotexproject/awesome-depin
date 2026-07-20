# Q-Tail Forge

Q-Tail Forge is the commercial web layer for the Q-Tail long-tail data engine. It combines a fundraising-ready public site, a buyer evidence room, a Pro workspace, MySQL-backed identity and entitlements, API access review, manual-QR and official-merchant payment modes, and auditable generation jobs.

Current operating mode: **local-only acceptance**. The former RC22 public pilot
on port 6222 was retired on 2026-07-20 and the original legacy HTTP application
was restored there. Q-Tail must not connect to or change that server without
new, explicit permission. Historical RC deployment evidence is retained for
audit purposes, but it does not prove a currently available Q-Tail public
endpoint. See
[acceptance-status-2026-07-20-local-only.md](docs/acceptance-status-2026-07-20-local-only.md).

The customer-facing engine produces long-tail allocation plans and scenario specifications. Pro users can also list and download a fixed, SHA-256-verified 64-episode MetaWorld Sawyer synthetic sample in LeRobot v3 and RLDS-compatible TFRecord through `/api/catalogs`, or request a 1–64 episode RLDS-compatible subset through `/api/generations` with `delivery_product=simulation_trajectory_batch`. The Worker runs the Q-Tail allocation first, verifies the immutable source archive and internal manifest, then copies complete TFRecord episodes into a request-specific ZIP with selection records and per-file hashes. These simulator artifacts remain `evidence_scope=simulation` and `buyer_gate_passed=false`; they do **not** substitute for buyer-owned backend, independent reproduction, real-robot approval, cost acceptance, or an executed procurement contract.

## Product surfaces

- `/` — public product and fundraising homepage
- `/evidence` — investor and procurement evidence room
- `/evidence#pilot-kit` — robot-vendor design-partner kit and verified download
- `/buyer-kit/qtail-buyer-pilot-kit-v1.2.0.zip` — SOW, Gate 1–3, real-robot, cost, independent two-party signature-proof, contract-archive templates, and an executable Gate 1 buyer-backend validator
- `/register`, `/login` — buyer identity
- `/app` — authenticated buyer dashboard
- `/app/studio` — contract-checked generation workspace
- `/app/compliance` — versioned data-rights, deployment, residency, retention, deletion, and legal-document review
- `/app/gates` — four-Gate buyer evidence, review, and contract-status workflow
- `/app/api` — API application and key management
- `/app/billing` — WeChat/Alipay QR orders, paid-order invoice, red-letter-aware refund, and entitlement status
- `/app/runs` — generation history, delivery downloads, retention state, and verified deletion requests
- `/app/account` — account export and verified closure/revocation
- `/operator` — API review, manual payment verification, official refund operations, buyer compliance review, procurement evidence review, and contract archival
- `/terms`, `/privacy`, `/dpa`, `/payment-policy` — public pre-launch legal/data-processing/payment review drafts

## Production-shaped local stack

1. Copy `.env.example` to `.env` and replace every secret.
2. Set `APP_ENV=production` and `SESSION_COOKIE_SECURE=1` for an HTTPS deployment.
3. Start the stack:

   ```bash
   docker compose up -d --build
   ```

4. Open `http://localhost:8080` or the port configured by `WEB_PORT`.

The stack contains MySQL 8.4, the Flask API, a separate lease-based Q-Tail
generation Worker, and an Nginx-served React build. Accepted generation tasks
and their retry state live in MySQL; inputs and generated packages share a
persistent named volume between API and Worker. `docker-compose.edge.yml` adds
a hardened Caddy automatic-HTTPS edge for a real domain.

Official merchant mode implements Alipay RSA2 and WeChat Pay API v3 signed
checkout/refund requests, response and callback verification, WeChat AES-GCM
decryption, merchant/order/amount validation and idempotent entitlement updates.
It is disabled by default. Follow `docs/official-payment-runbook.md`; generated
test keys prove software behavior, not real settlement.

Production ingress is selected with `QTAIL_INGRESS_MODE`:

- `caddy` — direct host ingress on ports 80/443 with automatic certificates.
- `cloudflare` — outbound-only named Cloudflare Tunnel using
  `docker-compose.cloudflare.yml`; the token is mounted from a mode-0600,
  file-backed Compose secret and is not placed in the container command or
  environment. The wrapper can atomically populate that file from a
  command-scoped `CLOUDFLARE_TUNNEL_TOKEN` supplied by a host secret manager.

Use `scripts/production_stack.sh` for either mode. It selects the correct
overlay and derives the required health checks so monitoring cannot silently
omit the active ingress service:

```bash
ENV_FILE=.env ./scripts/production_stack.sh config
ENV_FILE=.env ./scripts/production_stack.sh up
ENV_FILE=.env ./scripts/production_stack.sh monitor
```

For a short-lived external acceptance preview, use the separate production-configured environment and tunnel overlay:

```bash
docker compose -p qtail-preview \
  --env-file .env.preview \
  -f docker-compose.yml \
  -f docker-compose.production.yml \
  -f docker-compose.preview.yml \
  --profile temporary-preview \
  up -d --build
```

The free Pinggy URL is printed by `docker compose ... logs pinggy` and expires after 60 minutes. It is a QA preview, not a durable production deployment.

An account-free Cloudflare HTTPS rehearsal is also available. It includes a
private DNS-over-HTTPS resolver because some container/host networks block the
SRV lookups required for Tunnel edge discovery:

```bash
docker compose -p qtail-cloudflare-preview \
  --env-file .env.preview \
  -f docker-compose.yml \
  -f docker-compose.production.yml \
  -f docker-compose.cloudflare-preview.yml \
  --profile cloudflare-preview up -d --build --wait
docker compose -p qtail-cloudflare-preview \
  --env-file .env.preview \
  -f docker-compose.yml \
  -f docker-compose.production.yml \
  -f docker-compose.cloudflare-preview.yml \
  --profile cloudflare-preview logs cloudflared
```

Quick Tunnel hostnames are temporary and are never a substitute for an
authenticated named tunnel, controlled server, domain, backups, and alerts.
The Cloudflare preview overlay binds its local MySQL and Web ports to
`127.0.0.1:13318` and `127.0.0.1:18084` by default, so it can coexist with the
regular preview stack; override them with `CF_PREVIEW_MYSQL_EXPOSED_PORT` and
`CF_PREVIEW_WEB_PORT` if needed.

## Developer mode

The frontend expects `/api` and `/downloads` to be available through the Vite proxy. The backend can use an existing MySQL instance or the Compose database.

```bash
npm install
npm run dev
```

```bash
python -m pip install -r backend/requirements.txt
python backend/app.py
```

Use `QTAIL_FAKE_GENERATOR=1` only for isolated fixture tests. Production and acceptance testing must use `QTAIL_FAKE_GENERATOR=0`.

## Verification

```bash
npm run build
python -m unittest discover -s backend/tests -v
docker compose config --quiet
./scripts/smoke.sh http://127.0.0.1:8080
ENV_FILE=.env ./scripts/check_stack.sh
set -a; source .env.acceptance; set +a; python scripts/docker_acceptance.py
```

`docker_acceptance.py` traverses Nginx, the API, MySQL, Pro/payment enforcement,
versioned buyer compliance and source/derivative-rights checks, three
asynchronously queued real Q-Tail package generations, API-key catalog download,
an on-demand request-specific TFRecord trajectory delivery, a
buyer deletion request with an immutable receipt and HTTP 410 tombstone, and
the sequential Gate workflow. Its payment, legal, Gate, and contract records are
labelled Docker simulations and are
not substitutes for real-robot or buyer evidence. After restarting the Compose
stack, rerun it with `--verify-persistence` to verify the database and delivery
volume byte-for-byte. On a production host with Secure cookies, use
`--base-url https://<host> --resolve <host>:443:127.0.0.1` to keep normal TLS
certificate/SNI validation while testing through the local edge. Set
`--max-inflight-jobs 1` on the ECS-small profile so the acceptance flow respects
the production per-user queue limit instead of weakening it.

Production operations are packaged in `scripts/backup.sh`,
`scripts/replicate_backup.sh`, `scripts/restore.sh`, `scripts/smoke.sh`, and
`scripts/check_stack.sh`. Production backups require
`BACKUP_ENCRYPTION_PASSWORD`; they pause new Worker claims and wait for running
tasks before taking the database/filesystem snapshot. When
`OFFSITE_BACKUP_URI` is configured, every successful encrypted backup is copied
to an absolute file mount, S3, or Alibaba OSS together with a checksum sidecar
and is downloaded again for SHA-256 verification by default. Restore defaults
to verification-only and requires an explicit confirmation phrase before
changing MySQL or delivery files.

Additional production controls include `scripts/monitor.sh`, the dependency-free
`scripts/load_test.py`, the full local `scripts/restore_drill.sh`, and the
resource-bounded `scripts/host_restore_drill.sh`. External alert delivery can be
accepted with `scripts/test_alert_delivery.sh`. A macOS operations workstation
can use `scripts/pull_remote_backup.sh` with the supplied launchd template to
pull only encrypted ECS archives, pin the ED25519 host fingerprint, verify the
remote/local SHA-256 and keep a machine receipt. The host drill reuses the
deployed API image, restores into isolated MySQL/job volumes, reconciles all 16
critical tables and delivery-file counts, writes a JSON report, and always
removes the temporary project. Production Compose configuration lives in
`docker-compose.production.yml`; installable systemd units are under
`deploy/systemd/`.

When an owned domain is not yet available, the Caddy IP-TLS overlay can serve a
real short-lived Let’s Encrypt IP certificate. `scripts/renew_ip_certificate.sh`
uses a shared HTTP-01 webroot, validates the IP SAN and two-day safety window,
and reloads only the edge when the certificate changes. The edge supplies the
IP certificate as the default SNI because standards-compliant IP-literal clients
normally omit SNI. Release verification requires that SNI-less handshake and a
proxied health response, not only static Caddy parsing. This provides a trusted
HTTPS IP origin, but official merchant payment and final launch still require
an owned/approved domain.

Before moving the stack to a server, create a minimal, checksummed archive and
run the fail-closed host preflight:

```bash
RELEASE_ID=<release-id> ./scripts/build_release_bundle.sh
./scripts/verify_release_bundle.sh var/releases/qtail-forge-<release-id>.tar.gz
chmod 0600 .env
# Caddy ingress only; omit EXPECTED_PUBLIC_IP for Cloudflare Tunnel:
EXPECTED_PUBLIC_IP=<server-public-ip> ./scripts/server_preflight.sh
```

The release archive intentionally omits local environments, customer jobs,
database state, downloaded corpora, dependencies, build output, and bytecode.
The preflight verifies production secrets and bindings, domain/DNS, host
capacity, runtime assets, non-root container readability of the read-only
catalog mount, ingress-aware Compose rendering, and either the Caddy
configuration or fail-closed named-Tunnel token. The independent verifier
extracts the archive into a temporary directory, checks outer and per-file
hashes, renders both production ingress variants, and runs Docker smoke, the
27-test backend suite, real-generator commercial E2E, deletion/tombstone,
monitoring, and restart-persistence checks.

See [deployment runbook](docs/deployment-runbook.md), [API reference](docs/api.md), [four-gate delivery standard](docs/four-gate-delivery.md), and [launch checklist](docs/launch-checklist.md).

The current evidence-backed status is recorded in
[acceptance-status-2026-07-20-local-only.md](docs/acceptance-status-2026-07-20-local-only.md).
The earlier
[acceptance-status-2026-07-15.md](docs/acceptance-status-2026-07-15.md) is a
historical deployment record only.

The public evidence room exposes immutable summaries for the latest local Gate
1–3 evidence. Full reproducible artifacts live under the parent project's
`results/qtail_gate*` directories and are generated by
`../scripts/run_procurement_gates.sh`.
