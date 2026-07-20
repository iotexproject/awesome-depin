# Launch checklist

Current boundary (2026-07-20): local-only. The RC14–RC22 deployment entries
below are retained as historical evidence, not as a claim that Q-Tail is still
running on the former server. Port 6222 has been returned to the original legacy
application. No remote access or deployment is authorized without a new,
explicit user instruction.

## Product and conversion

- [x] Public homepage follows the approved visual direction
- [x] Investor/procurement evidence page follows the approved visual direction
- [x] Registration, login, logout, and protected routes
- [x] API application and operator approval
- [x] WeChat and Alipay QR order creation
- [x] Manual payment reference submission and operator verification
- [x] Verified payment activates 30-day Pro
- [x] Approved Pro user can create an API key
- [x] Browser and API generation flow produces a downloadable ZIP
- [x] Pro-only catalog API serves the fixed 64-trajectory MetaWorld/Sawyer sample only after byte/SHA-256 verification and records each download
- [x] Pro API creates request-specific 1–64 episode Sawyer/MetaWorld RLDS-compatible batches after Q-Tail allocation, exact source/archive verification, and complete TFRecord record copying
- [x] Request-specific batches include source/selection/robot/format manifests and remain `evidence_scope=simulation`, `buyer_gate_passed=false`
- [x] Every generation records a versioned source/derivative-rights attestation hash and blocks incomplete attestations
- [x] Buyer deletion request, guarded payload removal, immutable SHA-256 receipt, HTTP 410 tombstone, and account-export record
- [x] Buyer compliance profile records deployment, residency, retention, deletion, and current Terms/Privacy/DPA acceptance hashes
- [x] Operator compliance approval is required before any all-Gates-approved case becomes contract-ready
- [x] Pro buyer can create a procurement case from a completed generation job
- [x] Gate 1–3 automatic thresholds, sequential operator approvals, evidence hashes, and audit events
- [x] Simulation/public-benchmark Gate approvals are blocked from contract readiness
- [x] Only sequential buyer-external Gate 1–3 records with original/signoff hashes and operator review attestations create a versioned contract-ready snapshot
- [x] Contract signing requires an executed-document hash, both signatories, distinct provider/buyer signature-proof hashes, effective date, and execution-attestation hash
- [x] Contract owner can download a scope/Gate-hash/SOW negotiation draft that is explicitly not an executed agreement
- [x] Desktop/mobile responsive QA and zero browser console errors

## Data and infrastructure

- [x] MySQL schema for users, sessions, applications, keys, orders, jobs, data rights, deletion requests, compliance/legal acceptances, procurement cases/evidence/contracts, and audit events
- [x] Real Q-Tail adapter connected with `QTAIL_FAKE_GENERATOR=0`
- [x] MySQL-backed asynchronous queue, separate Worker, renewable lease, bounded retry, and per-job status endpoint
- [x] Worker crash injection: expired lease requeued once and completed on attempt 2 without losing the job
- [x] Backup/restore Worker quiescing prevents database/package snapshot races
- [x] Retention-expiry deletion Worker respects backup pause and deletion-SLA monitoring
- [x] Dockerfiles, Compose stack, Nginx routing, persistent volumes, and health checks
- [x] Frontend production build and 31 backend integration/threshold/lifecycle tests
- [x] 2026-07-20 isolated local Docker rebuild, 16-route smoke, catalog-required commercial E2E, 8-trajectory/418-frame on-demand RLDS delivery, and post-restart persistence
- [x] Container image build/run and smoke test on the local Docker host
- [x] Temporary external HTTPS acceptance preview and Secure-cookie registration check
- [x] Encrypted database/package backup generation and checksum verification tooling
- [x] Restore verification, local/public stack checks, public smoke suite, and Nginx API rate limits
- [x] Protected operations-health metrics and alert-capable monitor script
- [x] Required-service health enforcement, including a container-only Caddy liveness endpoint
- [x] 1,200-request / 64-concurrency idempotent read-path load test (0 errors; p95 27.55 ms on the latest acceptance-host run)
- [x] Encrypted backup plus isolated destructive restore drill with 16-table and full delivery-file reconciliation
- [x] Production Compose resource/logging/security overlay and systemd service/timer package
- [x] Caddy automatic-HTTPS edge overlay; local HTTP/2, redirect, HSTS, internal certificate, and Secure-cookie acceptance passed
- [x] Outbound-only Cloudflare Tunnel overlay, private DoH/SRV resolver, connection-aware health check, HSTS, and fail-closed token preflight
- [x] Cloudflare Quick Tunnel public end-to-end flow: registration, Pro/payment simulation, API key, three real-model jobs, verified payload deletion, Gate 1–3, contract draft, and restart persistence
- [x] Fail-closed server preflight for secrets, bindings, DNS/IP, capacity, runtime assets, Compose, and Caddy
- [x] Allow-listed release archive with outer/per-file SHA-256 manifests and secret/runtime-data exclusions
- [x] RC6 archive extracted independently; outer/inner checksums, Caddy/Cloudflare Compose renders, 13-route smoke, 17 tests, commercial E2E, deletion receipt, monitoring, and restart persistence passed
- [x] RC7 archive extracted independently; outer/inner checksums, both production ingress renders, 13-route smoke, 19 tests, simulation-to-contract guard, execution/deletion attestations, real-generator commercial E2E, monitoring, and restart persistence passed
- [x] RC13 archive independent verification and ECS deployment: checksums, local Docker rebuild, 27 tests, commercial E2E, 16-table restore drill, server migration, monitoring, and restart persistence passed
- [x] RC14 operations bundle independently verified and atomically deployed: 13-route smoke, 27 tests, commercial E2E/restart persistence, host restore script packaging, server preflight, systemd reload, and protected monitoring passed
- [x] RC16 independently verified and atomically deployed: automatic replication receipt, restricted exporter metadata/stream/hash tests, arbitrary-command/path-traversal rejection, 13-route smoke, 27 tests, commercial E2E and persistence passed
- [x] RC17.3 independently verified and deployed: trusted Let’s Encrypt IP certificate, SNI-less IP-literal handshake, proxied health, HTTP-01 webroot staging renewal, 12-hour renewal timer, edge-only forced recreation, 13-route smoke, 27 tests, commercial E2E and persistence passed
- [x] RC18 independently verified and atomically deployed: protected Pro catalog, exact byte/SHA-256 validation, read-only mount, simulation/procurement claim boundary, 27 tests, real-generator commercial E2E, production HTTPS catalog download, audit event, stateless-service restart persistence, monitoring, and encrypted post-deployment backup passed
- [x] RC18.1 independently verified and atomically deployed: preflight rejects non-root-unreadable catalog mounts; Python HTTPS loopback preserves TLS/Secure-cookie validation; ECS-small batch acceptance passed registration through contract-hash workflow, three real-generator jobs, protected catalog, restart persistence, health monitoring, and encrypted pre-switch backup
- [x] RC19 local acceptance: 31 backend tests, browser QA with zero console errors, real-generator commercial E2E, protected catalog, Q-Tail-weighted 8-episode/418-frame on-demand TFRecord batch, simulation-to-contract rejection, and restart persistence
- [x] RC19 independently verified and atomically deployed: exact release checksums, amd64 images, production preflight, additive MySQL migration, five healthy services, trusted HTTPS/Secure-cookie commercial E2E, on-demand trajectory delivery, stateless-service restart persistence, protected monitoring, and pre-switch encrypted backup
- [x] RC20 independently verified and atomically deployed: alternate HTTPS overlay/preflight/release verification passed; the legacy 6222 PM2 process was stopped and removed from saved startup state; public trusted HTTPS, 13 routes, browser rendering, full commercial E2E, 8-episode/418-frame request delivery, four-service restart persistence, protected monitoring and post-deployment encrypted backup passed
- [x] RC21 independently verified and atomically deployed: release/per-file hashes, 31 tests, 16 public smoke checks, commercial simulation E2E/restart persistence, 11-template buyer pilot kit and SHA sidecar, fail-closed non-evidence defaults, public download hash, protected monitoring, preflight and encrypted post-deployment backup passed
- [x] RC22 independently verified and atomically deployed: Gate 1 buyer-backend validator passed completed-fixture validation and rejected blank/tampered packages; 31 tests, 16 public smoke checks, public ZIP/tool execution, restart persistence, protected monitoring, preflight and encrypted post-deployment backup passed
- [x] Durable production host deployment with persistent MySQL/delivery volumes and systemd lifecycle
- [x] Trusted IP-origin TLS, certificate-expiry monitoring, and automatic renewal software
- [ ] Fresh, explicitly authorized public Q-Tail endpoint (the historical 6222 pilot has been retired)
- [ ] Alibaba ECS security-group TCP/443 inbound rule; external nodes currently time out while TCP/80 succeeds
- [ ] Owned production domain, DNS, ICP/access filing, and payment-provider callback-domain approval
- [ ] Authenticated Cloudflare account/named Tunnel and controlled hostname, if Cloudflare ingress is selected
- [ ] Production secret manager and secret rotation record
- [x] Activate and observe automated encrypted backups on the production host
- [x] ECS isolated restore drill using resource-bounded temporary MySQL/API volumes: all 16 critical table counts and 55 delivery files reconciled; production volumes untouched
- [x] Copy the tested encrypted backup off the ECS host and verify its SHA-256 against the restore report
- [x] Automatic file/S3/OSS encrypted-backup replication software, checksum sidecar, default download re-verification, operations configuration, and fail-closed production preflight
- [x] Automated second-host encrypted backup pull every six hours through a forced-command, no-forwarding `qtailbackup` account with pinned ECS ED25519 fingerprint, remote/local SHA-256 match, 90-day retention and machine receipt; first restricted launchd run exited 0
- [x] HTTPS alert test utility, monitor success heartbeat, and overlap lock
- [x] ECS read-path load acceptance: 600 requests at concurrency 16, zero errors, 608.72 requests/second, p95 67.06 ms; post-load protected monitoring passed
- [ ] Configure external alert delivery and automated multi-region object-storage backup replication

## Legal and payments

- [x] Personal QR payment is labeled manual verification; no fake callback or auto-activation
- [x] Official Alipay RSA2 / WeChat API v3 code, mounted secrets, signed callbacks, replay guard, exact-once Pro activation, and original-channel refund state machine pass generated-key Docker tests
- [x] Public service, privacy, DPA/data-processing, and payment/refund/invoice review drafts
- [x] Self-service account export and verified account closure/revocation workflow
- [x] Paid-order invoice request, tax-system issuance reference, red-letter/cancellation gate, full-refund review, original-channel completion, and entitlement/API-key revocation workflow
- [ ] Real official merchant accounts, production credentials, public HTTPS callbacks, and reconciled low-value payment/refund fulfillment
- [ ] Legal/tax approval of terms, privacy/data-processing, refund, and invoice drafts; publish verified entity contact details
- [ ] China hosting registration/filing review for the selected infrastructure

## Procurement evidence

- [x] Gate 0 claim boundary and audit evidence
- [x] Gate 1 buyer input contract validation
- [x] Gate 1–3 evidence submission/review and contract-state workflow (QA data)
- [x] Public deterministic buyer pilot kit with SOW, Gate 1–3 JSON/CSV ledgers, signoff, contract checklist, manifest and SHA-256 sidecar; every blank template defaults to non-passing evidence
- [x] Technical-vs-buyer-external evidence separation, legacy-record warning, and simulation-to-contract rejection
- [x] Contract-ready transition and contract draft are blocked until the current compliance/data-rights profile is approved
- [x] Gate 1 public Open X→LeRobot v3 adapter baseline: 64 trajectories / 1,915 frames / loader and playback passed
- [x] Gate 1 local Sawyer/MuJoCo synthetic production baseline: 64 trajectories / 3,285 frames / LeRobot v3 official loader and RLDS-compatible TFRecord validation passed / missing and corrupt frames 0
- [x] Gate 2 retrained directly from the immutable Gate 1 synthetic package; feature/action hashes match deterministic simulator recollection
- [ ] Gate 1 buyer-specific production-backend execution and operator acceptance
- [x] Gate 2 controlled MetaWorld comparison meets thresholds: Tail SR +16.33 pp; paired 95% CI +12.00 to +20.67 pp
- [ ] Gate 2 independent buyer reproduction/acceptance
- [x] Gate 3 local simulation/safety/economics: 3 tasks / 600 episodes / modeled unit-cost reduction 24.02%
- [ ] Gate 3 real-robot, actual invoice-cost, safety-owner, and procurement acceptance evidence

## Launch decision

The product is ready for local controlled MVP/design-partner acceptance. RC22
deployment, monitoring, backup, TLS and restart records are historical evidence;
they are not active-runtime claims. A future public launch requires new explicit
authorization, a fresh deployment to a non-conflicting origin, an owned/approved
domain, filing and verified entity/legal/tax details, live official-merchant
reconciliation or accountable manual payment operations, and buyer-owned Gate
evidence. Do not present unchecked items as complete.
