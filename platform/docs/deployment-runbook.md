# Q-Tail Forge deployment runbook

## 1. Host baseline

Use a Linux host with Docker Engine and the Compose plugin, persistent SSD storage, and a domain. The provided Caddy edge overlay performs HTTPS termination and certificate renewal. Recommended minimum for the current asynchronous MVP is 4 vCPU, 16 GiB RAM, and 100 GiB SSD; resize after measuring real Q-Tail job duration, queue age, and package growth.

For a controlled single-Worker design-partner pilot on a constrained ECS, set
`QTAIL_HOST_PROFILE=ecs-small` and keep
`MAX_ACTIVE_GENERATIONS_PER_USER=1`. This profile bounds service memory and
reduces MySQL buffers; it is a deployment exception, not evidence of general
paid-traffic capacity. Upgrade to the standard host baseline before opening
unrestricted paid traffic or increasing generation concurrency.

For Caddy ingress, expose only ports 80/443. For Cloudflare Tunnel ingress,
close inbound application ports entirely after the connector is verified. Never
expose MySQL. Compose binds the database and upstream web port to `127.0.0.1`
by default; keep `MYSQL_BIND_HOST=127.0.0.1` and
`WEB_BIND_HOST=127.0.0.1` on a public host.

## 2. Production environment

Create `platform/.env` from `.env.example`. Required production values:

```dotenv
APP_ENV=production
APP_SECRET=<at-least-32-random-characters>
ADMIN_TOKEN=<at-least-32-random-characters>
SESSION_COOKIE_SECURE=1
PIP_INDEX_URL=https://pypi.org/simple
MYSQL_DATABASE=qtail
MYSQL_USER=qtail
MYSQL_PASSWORD=<strong-unique-password>
MYSQL_ROOT_PASSWORD=<strong-unique-root-password>
MYSQL_BIND_HOST=127.0.0.1
MYSQL_EXPOSED_PORT=3307
PRO_PRICE_CENTS=99900
PAYMENT_MODE=manual_qr_verification
PAYMENT_PUBLIC_URL=
QTAIL_PAYMENT_SECRETS_DIR=/opt/qtail/secrets/payment
PRO_DAILY_GENERATION_LIMIT=50
MAX_ACTIVE_GENERATIONS_PER_USER=5
QTAIL_FAKE_GENERATOR=0
QTAIL_WORKER_ENABLED=1
QTAIL_WORKER_MAX_ATTEMPTS=3
QTAIL_WORKER_POLL_SECONDS=1
QTAIL_WORKER_HEARTBEAT_SECONDS=15
QTAIL_WORKER_LEASE_SECONDS=120
QTAIL_WORKER_RETRY_BASE_SECONDS=5
QTAIL_RETENTION_SWEEP_SECONDS=60
WEB_PORT=8080
WEB_BIND_HOST=127.0.0.1
QTAIL_DOMAIN=qtail.example.com
EDGE_BIND_HOST=0.0.0.0
HTTP_PORT=80
HTTPS_PORT=443
QTAIL_INGRESS_MODE=caddy
QTAIL_HOST_PROFILE=standard
CLOUDFLARE_TUNNEL_TOKEN=
CLOUDFLARE_TUNNEL_TOKEN_FILE=./var/secrets/cloudflare_tunnel_token
QTAIL_TUNNEL_DNS_SUBNET=10.254.53.0/24
QTAIL_TUNNEL_DNS_IP=10.254.53.53
QTAIL_TUNNEL_CONNECTOR_IP=10.254.53.54
```

Keep the manual mode until the merchant contracts and HTTPS callback domain are ready. For Alipay/WeChat merchant identifiers, mounted key files, live-test order, refund and rollback steps, follow `docs/official-payment-runbook.md`.

Generate secrets using the host's secret manager or `openssl rand -hex 32`. Never commit `.env`, API keys, the admin token, database dumps, or generated customer packages.

`PIP_INDEX_URL` is a build-time dependency source only. On a mainland-China ECS,
an audited HTTPS mirror such as `https://mirrors.aliyun.com/pypi/simple` may be
used when direct PyPI throughput is inadequate; runtime containers do not
receive this value.

Set the production `.env` mode to `0600`, then run the fail-closed host
preflight before building:

```bash
chmod 0600 .env
# Caddy mode only:
EXPECTED_PUBLIC_IP=<server-public-ip> ./scripts/server_preflight.sh
# Cloudflare mode (do not set EXPECTED_PUBLIC_IP):
./scripts/server_preflight.sh
```

The preflight rejects placeholder/short secrets, insecure cookies, the fixture
generator, public MySQL/upstream bindings, an unresolved or mismatched domain,
insufficient disk/Docker memory, missing payment/model assets, invalid Compose,
an invalid Caddy configuration, or a missing/short Cloudflare named-tunnel
token. Its default capacity floors are 40 GiB free
disk and 12 GiB assigned to Docker; override them only after recording an
explicit capacity decision. A no-public-DNS local rehearsal is available with
`PREFLIGHT_MODE=local`.

The documented `ecs-small` design-partner exception may use
`MIN_FREE_DISK_GIB=10 MIN_HOST_MEMORY_GIB=1` after confirming swap, keeping one
active generation per user, and monitoring memory, disk, queue age, and Worker
heartbeats. These preflight overrides do not certify production capacity.

## 3. Reproducible release bundle

Build the deployment archive from the repository root layout:

```bash
RELEASE_ID=<version-or-utc-id> ./scripts/build_release_bundle.sh
(cd var/releases && shasum -a 256 -c qtail-forge-<version-or-utc-id>.tar.gz.sha256)
./scripts/verify_release_bundle.sh var/releases/qtail-forge-<version-or-utc-id>.tar.gz
```

The allow-listed archive contains the platform source, four required model
runtime modules, one model prior, and two training calibration snapshots. It
excludes `.env` files, customer jobs, database state, downloaded training
corpora, development dependencies, build output, and bytecode caches. The
archive contains `RELEASE-METADATA.txt` and per-file `SHA256SUMS`; verify both
the outer checksum and the inner manifest after transfer to the host. The
independent verifier also renders both production ingress variants and runs the
packaged Docker stack through smoke, 19 backend tests, real-generator commercial
E2E, verified payload deletion, monitoring, and restart persistence. Its JSON
report is written next to the archive.

## 4. Build and start

From `platform/`, use the ingress-aware wrapper. It always includes the
production resource, log-rotation, API/Worker read-only-root-filesystem overlay,
then exactly one selected ingress overlay:

```bash
ENV_FILE=.env ./scripts/production_stack.sh config
ENV_FILE=.env ./scripts/production_stack.sh up
ENV_FILE=.env ./scripts/production_stack.sh ps
curl --fail http://127.0.0.1:8080/api/health
```

Expected health response includes `"ok":true`, `"database":"mysql"`, and `"service":"qtail-platform-api"`.

## 5. DNS and TLS

### Direct Caddy ingress

Point `QTAIL_DOMAIN` to the host, allow inbound TCP 80/443, and keep the upstream
web/MySQL bindings on `127.0.0.1`. `docker-compose.edge.yml` maps public 80/443
to Caddy's unprivileged container ports, requests and renews the certificate,
redirects HTTP to HTTPS, adds HSTS, and forwards to `web:80`. The edge container
has a read-only root filesystem, no Linux capabilities, and
`no-new-privileges`. Keep `SESSION_COOKIE_SECURE=1`.

If a cloud security group already exposes a non-standard TLS port while 443 is
being approved, set `QTAIL_ALT_HTTPS_PORT` (1024-65535). The production wrapper
adds `docker-compose.alt-https.yml`, mapping that host port to the same Caddy
TLS listener, certificate, HSTS policy, and RC19 application as 443. Use an
explicit `https://host:port` URL. This is a compatibility entrance, not a
replacement for opening standard TCP 443; remove it after the security-group
rule and canonical domain are live.

Before paid traffic, verify `docker compose logs edge`, the certificate chain,
renewal storage volumes, and that the domain returns the expected HSTS and
Secure/HttpOnly/SameSite cookie attributes. The local TLS acceptance path can be
tested with `QTAIL_DOMAIN=localhost`, non-public host ports, and
`CURL_INSECURE=1 ./scripts/smoke.sh https://localhost:<port>`; never use the
insecure flag for the production domain.

### Outbound-only Cloudflare ingress

Use this mode only with an authenticated Cloudflare account and a domain in
that account:

1. Run `npx wrangler whoami` and confirm the intended account.
2. Create a remotely managed named Tunnel in Cloudflare Zero Trust.
3. Add a public hostname for `QTAIL_DOMAIN` whose origin service is
   `http://web:80`. Cloudflare creates/uses the proxied DNS route.
4. Put the copied connector token in the host secret manager and expose it as
   `CLOUDFLARE_TUNNEL_TOKEN` only while the wrapper starts, or provision the
   mode-0600 path named by `CLOUDFLARE_TUNNEL_TOKEN_FILE`. Set
   `QTAIL_INGRESS_MODE=cloudflare` and keep `WEB_BIND_HOST=127.0.0.1`.
5. Run `PREFLIGHT_MODE=production ./scripts/server_preflight.sh`, then
   `./scripts/production_stack.sh up` and `./scripts/production_stack.sh monitor`.

The wrapper atomically materializes a command-scoped token as a mode-0600 host
file, and the Compose overlay mounts that file read-only through `/run/secrets`
rather than placing its value in the container command/environment. Keep the
file outside backups and release archives and rotate it with the named Tunnel.
`cloudflared` and the private DoH
resolver have read-only filesystems and `no-new-privileges`; the resolver is
limited to `NET_BIND_SERVICE` and an internal network. Change the default
`10.254.53.0/24` subnet only if it conflicts with the host/VPC. For Tunnel mode,
do not set `EXPECTED_PUBLIC_IP`: public DNS resolves to Cloudflare anycast, not
the origin. After the named Tunnel is healthy, close all inbound application
ports at the origin firewall.

After TLS is live, verify:

- `/`, `/evidence`, `/register`, `/login`, `/terms`, `/privacy`, `/dpa`, `/payment-policy`
- authenticated `/app` workflow
- `/api/health`
- generation ZIP download
- both QR assets under `/pay/`
- no browser console errors at desktop and mobile widths

## 6. Operator workflow

1. Open `/operator` over HTTPS.
2. Enter the production `ADMIN_TOKEN`; it is kept only in that browser tab's session storage.
3. Review API applications and approve or reject with a note.
4. Review buyer compliance profiles against the actual data license, derivative
   rights, DPA, security boundary, residency, retention, and deletion terms.
5. For submitted QR orders, verify the amount and reference in the actual WeChat/Alipay account.
6. Confirm only after funds are visible. Confirmation grants 30 Pro days in one database transaction.

Personal QR codes do not provide signed server callbacks. A user-submitted reference never auto-activates Pro. For automatic fulfillment, replace this flow with official WeChat Pay and Alipay merchant APIs, server-side signature verification, idempotent webhooks, refunds, reconciliation, and invoices.

Paid orders can create a digital-invoice request and one full-refund request.
Operators may record an invoice only after verifying the external tax-system
number; an HTTPS document link is optional. Refund approval does not revoke Pro
or mark money returned. Completion requires a real original-channel refund
reference. If an invoice was issued, the system blocks refund completion until
an operator records the real red-letter/cancellation reference. A completed
refund changes the order to `refunded`, subtracts the corresponding 30-day
entitlement, and revokes API keys if no Pro term remains.

The run ledger also accepts per-job payload deletion requests. Operators can
execute them immediately after checking scope, while the Worker enforces the
approved deletion deadline and each job's versioned retention period. A
completed deletion removes input and generated packages, disables the download
with HTTP 410, and retains only hashes, audit/Gate/contract metadata, and an
immutable file-level deletion receipt. The protected monitor fails if a
deletion SLA or retention deadline is overdue. Deletion pauses whenever backup
quiescing pauses the Worker.

## 7. Backups and recovery

Create an encrypted MySQL and delivery-package backup before upgrades and at least daily:

```bash
export BACKUP_ENCRYPTION_PASSWORD='<read from secret manager>'
ENV_FILE=.env BACKUP_DIR=/srv/qtail/backups ./scripts/backup.sh
```

The backup contains the transactional database dump, the generated delivery packages, metadata, and SHA-256 checksums. Production mode refuses to create an unencrypted archive. Verify every backup and test restore quarterly:

```bash
BACKUP_ENCRYPTION_PASSWORD='<read from secret manager>' \
  ENV_FILE=.env \
  RESTORE_MODE=verify \
  ./scripts/restore.sh /srv/qtail/backups/qtail-YYYYMMDDTHHMMSSZ.tar.gz.enc
```

An actual restore is intentionally destructive and additionally requires `RESTORE_MODE=restore RESTORE_CONFIRM=restore-qtail`. Run it only inside a maintenance window after preserving the current state. Schedule `backup.sh` with the host scheduler and ship encrypted archives to separate object storage.

Automatic off-host replication is fail-closed once `OFFSITE_BACKUP_URI` is set.
It supports an absolute `file:///` mount, `s3://` through an authenticated AWS
CLI, and `oss://` through an authenticated `ossutil`. The encrypted archive and
its SHA-256 sidecar are uploaded; by default the archive is downloaded again
and hashed before the backup service succeeds:

```bash
OFFSITE_BACKUP_URI=oss://company-qtail-backups/production \
OFFSITE_VERIFY_DOWNLOAD=1 \
ENV_FILE=.env BACKUP_DIR=/srv/qtail/backups \
./scripts/backup.sh
```

Keep `REQUIRE_OFFSITE_BACKUP=0` until credentials and the destination are
installed, then set it to `1` in the root-only operations environment. A local
copy on the same ECS disk is not an off-host backup.

If object-storage credentials are not yet available, a separate macOS
operations workstation can pull the encrypted archives on a schedule. The
puller refuses plaintext files, pins the server ED25519 fingerprint, compares
the server and workstation SHA-256, writes an atomic receipt, and retains no
database decryption password:

```bash
QTAIL_BACKUP_HOST=203.0.113.10 \
QTAIL_BACKUP_HOST_FINGERPRINT='SHA256:verified-fingerprint' \
QTAIL_OFFSITE_DIR=/secure/qtail-offsite \
./scripts/pull_remote_backup.sh
```

Do not give the scheduled puller an unrestricted server login. Create a
dedicated `qtailbackup` system account/group, install
`deploy/server/qtail-backup-export.sh` as a root-owned executable, and prefix
the workstation public key in that account's `authorized_keys` with:

```text
restrict,command="/usr/local/sbin/qtail-backup-export"
```

Set `BACKUP_READ_GROUP=qtailbackup` in `/etc/qtail/operations.env`; new archives
will be group-readable while plaintext working files remain root-only. The
forced command accepts only `qtail-backup-metadata` and a validated
`qtail-backup-stream qtail-*.tar.gz.enc` request. It rejects arbitrary shell,
paths, symlinks, port forwarding and PTY access.

Install `deploy/launchd/com.qtail.offsite-backup.plist.example` under the
operator's `~/Library/LaunchAgents` after replacing every example path. This is
a real second-host copy when the workstation is online; it is not a substitute
for multi-region immutable object storage.

Before production, run the automated destructive drill against a disposable,
random-port Compose project. It creates an encrypted source backup, restores it
into independent MySQL/job volumes, reconciles row and delivery-file counts,
runs the smoke suite, and destroys only the guarded drill project:

```bash
ENV_FILE=.env COMPOSE_PROJECT_NAME=qtail-production \
  BACKUP_ENCRYPTION_PASSWORD='<read from secret manager>' \
  ./scripts/restore_drill.sh
```

## 8. Monitoring and smoke checks

### Trusted HTTPS before an owned domain is available

Let’s Encrypt IP certificates are short-lived. After obtaining the initial
certificate with Certbot 5.4 or newer, set the following production values:

```dotenv
QTAIL_INGRESS_MODE=caddy
QTAIL_TLS_MODE=ip_certificate
QTAIL_PUBLIC_IP=203.0.113.10
QTAIL_CERTBOT_CONFIG_DIR=/opt/qtail/certbot/config
QTAIL_ACME_WEBROOT=/opt/qtail/acme-webroot
```

The `docker-compose.ip-tls.yml` overlay mounts the complete Certbot config tree
read-only so its `live/` symlinks continue to resolve, serves HTTP-01 tokens
without redirecting them, redirects all other HTTP traffic, and loads the IP
certificate explicitly. Caddy's default SNI is set to that IP because clients
typically omit SNI for IP-literal URLs. Independent release verification must
complete a trusted SNI-less handshake and proxy `/api/health`; on-host checks
route the public IP name to loopback so they do not depend on provider hairpin
NAT. Install and enable `qtail-cert-renew.service` and
`qtail-cert-renew.timer`; the timer runs every 12 hours. Monitoring fails when
the certificate has less than two days remaining or the trusted public HTTPS
health endpoint fails.

IP HTTPS is an interim origin, not a substitute for an owned domain, ICP/access
filing, or payment-provider callback-domain approval. `server_preflight.sh`
intentionally rejects `PAYMENT_MODE=official_merchant` while IP-certificate
mode is active.

Run the local stack check from the host scheduler or monitoring agent:

```bash
ENV_FILE=.env \
  BACKUP_DIR=/srv/qtail/backups \
  PUBLIC_URL=https://qtail.example.com \
  ./scripts/check_stack.sh
```

It requires every configured service (`db,api,worker,web,edge` for Caddy or
`db,api,worker,web,tunnel-dns,cloudflared` for Cloudflare) to be
running and healthy, then verifies MySQL, local/public health, free disk, and
optional backup freshness. The edge health endpoint listens only inside its
container and is not a public application route. Run the public smoke suite
after every deployment:

```bash
./scripts/smoke.sh https://qtail.example.com
```

The smoke suite checks the public pages, API/MySQL health, documentation, and both supplied payment QR assets without mutating customer data. Nginx applies separate request limits to authentication, operator, and general API routes and returns HTTP 429 when a limit is exceeded.

`monitor.sh` additionally calls the protected operations-health endpoint and can
send a generic JSON alert to `ALERT_WEBHOOK_URL`. It never includes customer
payloads. `MONITOR_HEARTBEAT_URL` provides a success/dead-man heartbeat, and a
host lock prevents overlapping timer/manual monitor runs. Before relying on the
alert path, execute a real delivery test and retain the receiver-side event:

```bash
OPERATIONS_ENV_FILE=/etc/qtail/operations.env \
  ./scripts/test_alert_delivery.sh
```

Both external URLs must use HTTPS. Validate cacheable/read capacity without mutating the database:

```bash
python3 scripts/load_test.py https://qtail.example.com \
  --requests 1200 --concurrency 64 \
  --json-out /srv/qtail/reports/load-test.json
```

The load probe performs one API/MySQL health preflight and then exercises only
idempotent public pages/assets. The Docker acceptance suite separately queues
three real model jobs, and a fault-injection drill kills the Worker during a
leased task and verifies automatic requeue/completion. Host-specific sustained
generation capacity and payment settlement remain separate tests after expected
buyer payloads and a merchant sandbox are available.

## 9. systemd installation package

The repository provides `deploy/systemd/qtail.service`, daily encrypted backup,
five-minute monitor, and 12-hour short-lived-certificate renewal timers. The units expect an atomic release symlink at
`/opt/qtail/current`, a mode-0600 production environment at
`/etc/qtail/qtail.env`, and intentionally run as root because access to the host
Docker socket is already root-equivalent. On a Linux host:

1. Extract the verified release under `/opt/qtail/releases/` and atomically
   point `/opt/qtail/current` to it.
2. Copy `deploy/operations.env.example` to `/etc/qtail/operations.env`, replace
   the URLs, offsite destination and thresholds, and set owner `root:root` and mode `0600`. Leave
   `PUBLIC_URL` empty until the real domain has a valid public certificate.
3. Create the backup directory with
   `install -d -o root -g root -m 0700 /opt/qtail/backups`.
4. Copy the service/timer unit files to `/etc/systemd/system/`.
5. Run `systemctl daemon-reload` and enable `qtail.service`,
   `qtail-backup.timer`, `qtail-monitor.timer`, and, for IP TLS,
   `qtail-cert-renew.timer`.
6. Confirm `systemctl list-timers`, one successful off-host backup with download
   hash verification, one monitor run, a received intentional test alert, and a
   received success heartbeat before accepting paid traffic.

The service boot path uses `production_stack.sh start`, which never rebuilds or
pulls images. Build and verify an immutable release before switching the
`current` symlink; use `production_stack.sh up` only during that controlled
release operation.

## 10. Upgrade and rollback

```bash
docker compose pull
docker compose build --pull
docker compose up -d
docker compose ps
curl --fail http://127.0.0.1:8080/api/health
```

The schema initializer is additive for the current MVP. Before destructive migrations, create and test a dedicated migration and restore point. Roll back by redeploying the previous image tag and restoring only when the migration is not backward compatible.

## 11. Production hardening before paid traffic

- Put login, registration, generation, and admin endpoints behind edge rate limits.
- Store secrets in a managed secret store and rotate the admin token.
- Ship logs and audit events to retained monitoring; alert on 5xx, failed jobs, and backup failure.
- Scale the lease-based Worker horizontally only after measuring actual buyer
  job memory, duration, queue age, and delivery-storage growth.
- Move delivery packages to private object storage with expiring signed links.
- Have counsel/tax review `/terms`, `/privacy`, and `/payment-policy`; replace the
  draft warning with verified entity address/contact, retention schedule,
  subprocessors, refund owner, invoice workflow, and dispute terms.
- Complete ICP/public-security filings required for the chosen China deployment.
- Run security review and restore/load tests before public paid acquisition.

## 12. Temporary external acceptance preview

`docker-compose.preview.yml` adds an SSH-over-443 Pinggy connector to the production-shaped stack. It is useful when a reviewer needs to see the live application before a domain and host are provisioned:

```bash
docker compose -p qtail-preview \
  --env-file .env.preview \
  -f docker-compose.yml \
  -f docker-compose.production.yml \
  -f docker-compose.preview.yml \
  --profile temporary-preview \
  up -d --build

docker compose -p qtail-preview \
  --env-file .env.preview \
  -f docker-compose.yml \
  -f docker-compose.production.yml \
  -f docker-compose.preview.yml \
  --profile temporary-preview \
  logs pinggy
```

The anonymous URL expires after 60 minutes and has no uptime guarantee. Do not use it for paid customers, confidential buyer data, or investor diligence requiring a stable hostname. The durable path remains a controlled host, named domain, TLS, backups, monitoring, and production secrets.

For a second, independent HTTPS path, `docker-compose.cloudflare-preview.yml`
starts an account-free Quick Tunnel plus a private DoH resolver and a
connection-aware `/ready` health check:

```bash
docker compose -p qtail-cloudflare-preview --env-file .env.preview \
  -f docker-compose.yml -f docker-compose.production.yml \
  -f docker-compose.cloudflare-preview.yml \
  --profile cloudflare-preview up -d --build --wait
docker compose -p qtail-cloudflare-preview --env-file .env.preview \
  -f docker-compose.yml -f docker-compose.production.yml \
  -f docker-compose.cloudflare-preview.yml \
  --profile cloudflare-preview logs cloudflared
```

The `trycloudflare.com` hostname is ephemeral, has no SLA, and must not receive
real payments or confidential buyer data. Production must use the authenticated
named-tunnel procedure above.
