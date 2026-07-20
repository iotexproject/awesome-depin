# Q-Tail Forge changelog

## 20260720-local-contract-integrity

- Added separate provider and buyer signature-proof SHA-256 fields to the
  procurement-contract schema, operator API, audit event, account export,
  contract draft and execution attestation.
- Contract completion now fails closed when either proof is missing, malformed,
  or identical to the other party's proof. Historical signed records without
  both independent hashes are shown as unverified instead of full contracts.
- Upgraded the buyer pilot kit to v1.2.0 with a two-party signature-proof
  archival checklist. This is a local software control and does not create or
  verify any real signature.

## 20260717-rc22

- Upgraded the robot-vendor pilot kit to v1.1.0 with a standalone,
  standard-library Gate 1 production-backend validator. Buyers can validate a
  frozen dataset package and production log against robot, sensor, frequency,
  task, format, trajectory/frame, Q-Tail source and SHA-256 declarations.
- The validator rejects the blank template, placeholders, malformed or
  timezone-free observations, non-RLDS/LeRobot formats, missing schema/playback
  checks, URL/hash mismatches and post-manifest package tampering.
- A passing technical report deliberately remains `contract_eligible=false`
  and `buyer_signoff_required=true`; independent kit verification exercises a
  completed fixture and a tampered fixture before release packaging.

## 20260717-rc21

- Added a public, versioned robot-vendor procurement pilot kit with 11 blank
  working templates: SOW, robot/dataset contract, Gate 1–3 evidence payloads,
  closed-loop ledger, real-robot trial ledger, invoice/cost ledger, buyer
  signoff, and executed-contract archival checklist.
- The kit is deterministically built into a ZIP with a per-file manifest and
  archive SHA-256 sidecar. Independent verification rejects missing, changed,
  duplicate or path-traversing members and requires every evidence template to
  default to a non-passing state.
- Added public evidence-room and authenticated Gate-workspace downloads. Smoke,
  release verification and production preflight now verify the kit. Blank
  templates remain `contract_eligibility=false` and cannot substitute for
  buyer data, real-robot trials, invoices, signatures or an executed contract.

## 20260717-rc20

- Added an optional, validated alternate HTTPS listener for production Caddy
  deployments. It exposes the same certificate, HSTS policy, frontend, API,
  MySQL-backed sessions, and Secure-cookie behavior as the canonical 443
  listener without publishing the private Web or database ports.
- Production preflight and the ingress-aware lifecycle wrapper reject invalid,
  privileged, duplicate, or Cloudflare-mode alternate ports. Release packaging
  and independent Compose verification now require the new overlay.
- This listener is a compatibility path for an already-open cloud firewall
  port; standard TCP/443 and an owned provider-approved domain remain required
  for canonical paid launch and official merchant callbacks.

## 20260717-rc19

- Added a Pro-only `simulation_trajectory_batch` generation product for the
  verified Sawyer/MetaWorld source. Requests may select 1–64 episodes across
  `reach-v3`, `button-press-v3`, and `pick-place-v3` under the locked 20 Hz,
  RGB-plus-state, MuJoCo/MetaWorld, RLDS-compatible contract.
- The Worker now runs the normal Q-Tail allocation, verifies the exact
  56,447,787-byte source archive and its internal manifest by SHA-256, then
  copies complete TFRecord records into a request-specific ZIP. The delivery
  includes the allocation plan, selection index, robot contract, source
  manifest, dataset metadata, per-file hashes, and an immutable source hash.
- Added MySQL delivery-product/trajectory-count fields, API validation,
  dashboard/studio/run-ledger/docs UI, Worker catalog read-only mount, audit
  metadata, and restart-persistent downloads.
- The request-specific package is always marked `evidence_scope=simulation`
  and `buyer_gate_passed=false`. It cannot satisfy buyer Gate 1–3 or contract
  eligibility without separately verified buyer-external evidence.
- Local verification passed the frontend build, 31 backend tests, browser QA
  with zero console errors, real-generator Docker commercial E2E, an 8-episode
  418-frame on-demand delivery, simulation-to-contract rejection, and
  byte-for-byte restart persistence.

## 20260717-rc18.1

- Production preflight now rejects a synthetic-catalog bind source that root
  can hash but the non-root API container cannot traverse or read. This closes
  the permission gap found during RC18 production acceptance.
- Docker commercial acceptance can preserve normal TLS hostname/certificate
  verification while routing an HTTPS origin to a loopback address with
  `--resolve`. Secure session cookies are therefore exercised on the persistent
  host without public-IP hairpin NAT.
- Acceptance jobs can run in batches of 1–3 so the ECS-small profile keeps its
  per-user active-queue protection. The queue check accepts the valid race where
  a Worker leases a submitted job before the 202 response is serialized.
- A full production HTTPS run passed registration, compliance, simulated manual
  payment and invoice/refund states, Pro/API key, protected catalog SHA-256,
  three real-generator Worker jobs, deletion/tombstone, Gate claim boundary,
  contract hash workflow, and post-restart persistence. It remains explicitly
  simulation-only evidence.

## 20260717-rc18

- Added a reproducible MetaWorld Sawyer/MuJoCo synthetic trajectory producer
  that exports the same 64-episode Q-Tail allocation as LeRobotDataset v3 and
  RLDS-compatible TFRecord. Both formats passed loader/schema checks across
  3,285 frames with zero missing, non-finite, or corrupt frames; package
  manifest SHA-256 is
  `003d5d62c92237412f86d72e796c4a5570e3a9760b1d40fee8c0f7f826f3c13a`.
- Changed the controlled Gate 2 study to train directly from that immutable
  Gate 1 package. State/action hashes match deterministic simulator
  recollection, and the same-policy/same-budget run retained Tail SR +16.33 pp
  with a +12.00 pp paired 95% CI lower bound.
- Updated public evidence summaries and copy while preserving the boundary:
  Pro users can now list and download the fixed synthetic trajectory sample
  through an authenticated API with byte/SHA-256 verification and an audit
  event. Arbitrary customer jobs still return allocation/scenario packages,
  and no local simulator artifact counts as buyer production-backend,
  real-robot, invoice, or contract acceptance.

## 20260716-rc17.3

- Changed edge reloads to a forced edge-only recreation so release-directory
  symlink switches cannot retain a bind mount resolved from the previous
  Caddyfile. Web, API, Worker and MySQL remain untouched.

## 20260716-rc17.2

- Added Caddy `default_sni` for IP-literal HTTPS clients, which normally omit
  SNI and otherwise received a TLS internal-error alert before HTTP routing.
- Extended independent release verification from static Caddy validation to a
  trusted SNI-less TLS handshake and proxied `/api/health` response.
- Made on-host IP-TLS monitoring preserve certificate/hostname verification
  while routing to loopback, avoiding public-IP hairpin-NAT dependency.

## 20260716-rc17.1

- Made IP-TLS production preflight compare `QTAIL_PUBLIC_IP` with the operator's
  independently supplied `EXPECTED_PUBLIC_IP` before switching the edge.

## 20260716-rc17

- Added trusted IP-origin TLS using a short-lived Let’s Encrypt IP certificate,
  an explicit Caddy certificate/webroot overlay, HTTP challenge routing, and
  strict HTTP→HTTPS redirect for all non-challenge requests.
- Added 12-hour Certbot renewal service/timer, IP SAN/key/validity preflight,
  public HTTPS health monitoring, edge-only reload after certificate changes,
  and a two-day certificate-expiry safety floor.
- Official merchant mode remains fail-closed under IP TLS because real payment
  activation still requires an owned provider-approved callback domain.

## 20260716-rc16

- Added a macOS off-host puller and launchd template for encrypted ECS backups.
  It pins the ED25519 server fingerprint, refuses plaintext, checks remote and
  local SHA-256 values, records an atomic receipt, and applies scoped retention.
- Added a forced-command encrypted-backup exporter, optional group-read mode
  for final encrypted archives, and path/symlink/command rejection so the
  scheduled workstation does not need an unrestricted root login.
- Installed the workstation job at a six-hour interval and verified its first
  automatic run exited successfully with a matching encrypted archive hash.

RC16 provides a working second-host backup path without copying the decryption
password. Multi-region object storage and external alert reception still need
real provider endpoints.

## 20260716-rc15

- Added automatic encrypted-backup replication to absolute mounted storage,
  S3, or Alibaba OSS, including a SHA-256 sidecar and default download-and-hash
  verification before the scheduled backup succeeds.
- Added fail-closed production preflight flags for offsite backup and HTTPS
  alert endpoints, a real alert delivery acceptance command, a success/dead-man
  monitor heartbeat, and an overlap lock for timer/manual monitor invocations.

RC15 makes external disaster-recovery and alert delivery configurable and
testable. Those controls remain externally unaccepted until real cloud
credentials/endpoints are installed and receiver-side evidence is retained.

## 20260716-rc14

- Added a resource-bounded ECS restore drill that reuses the deployed API image,
  restores into isolated MySQL/job volumes, reconciles all 16 critical tables
  and delivery-file counts, emits a machine-readable report, and removes the
  temporary project without changing production volumes.
- Completed an ECS restore rehearsal with 16/16 table-count and 55/55 delivery-
  file reconciliation, copied the encrypted backup off-host, and matched its
  SHA-256 independently.
- Completed an ECS idempotent read-path load probe with 600 requests at
  concurrency 16, zero errors and p95 67.06 ms; protected monitoring passed
  after the run.

RC14 adds repeatable operational evidence. It does not alter the RC13 payment,
Gate, or contract claim boundary and is not buyer/merchant evidence.

## 20260716-rc13

- Added a fail-closed official merchant payment mode with Alipay RSA2 and
  WeChat Pay API v3 outbound signing, signed-response verification, callback
  signature verification, AES-256-GCM resource decryption, merchant/app/order/
  currency/amount checks, and replay-resistant provider-event storage.
- Official payment callbacks now grant Pro atomically exactly once. Manual QR
  references and operator confirmation cannot settle official merchant orders.
- Added original-channel refund initiation for both providers. WeChat refunds
  remain processing until a signed success callback; Alipay completes only from
  a verified synchronous response. Manual completion is forbidden for official
  refunds, and retries preserve the merchant refund number.
- Added mounted-file secret handling, production preflight checks, a dynamic
  official checkout QR in the Pro console, operator refund states, account
  exports, and 27 containerized backend tests covering valid signatures,
  tampering, stale callbacks, replay, amount mismatch and entitlement reversal.

RC13 proves the payment software and mock-key cryptographic flows. It is not a
real merchant settlement or refund record; production remains in manual mode
until merchant credentials, a valid HTTPS domain and a reconciled low-value
live payment/refund are supplied.

## 20260716-rc12

- Added non-building `start` and ingress-aware encrypted `backup` production
  actions so boot recovery never depends on a package registry and backups
  always use the selected host/ingress overlays.
- Updated the systemd package for atomic `/opt/qtail/current` releases,
  `/etc/qtail/qtail.env`, `/opt/qtail/backups`, and the explicit root-equivalent
  Docker-socket trust boundary.

RC12 is the persistent-host release candidate used for the ECS service/timer
installation; product and evidence behavior are unchanged from RC11.

## 20260716-rc11

- Made independent release verification port allocation Docker Desktop-aware;
  it now excludes ports already published inside the Docker VM even when they
  are invisible to the macOS host socket table.

RC11 supersedes RC10 after verification discovered a local acceptance stack on
the kernel-selected MySQL port; no production application behavior changed.

## 20260716-rc10

- Added an explicit build-time `PIP_INDEX_URL` argument for both Python images,
  allowing a constrained mainland-China ECS to use an audited regional mirror
  without putting the mirror setting into runtime containers.
- Suppressed extended attributes with the tar implementation's
  `--no-xattrs` option after validating that `COPYFILE_DISABLE` alone did not
  remove libarchive metadata on this macOS host.

RC10 preserves the RC9 application and TLS behavior while making the release
build reproducible on the selected ECS network path.

## 20260716-rc9

- Pinned the TLS edge and preflight validator to Caddy 2.10.2 so registry
  mirrors cannot silently supply an obsolete `2` tag that rejects the hardened
  HTTP/1.1 + HTTP/2 server configuration.
- Disabled macOS extended-attribute records in release archives to keep Linux
  extraction quiet and the immutable payload portable.

RC9 supersedes RC8 for ECS deployment; application behavior and the
simulation-versus-procurement evidence boundary are unchanged.

## 20260716-rc8

- Added an optional `ecs-small` host profile for a single-Worker design-partner
  deployment on a constrained ECS, including bounded service memory/CPU and
  reduced MySQL memory settings.
- Wired the profile into production startup, fail-closed preflight, release
  packaging, and independent Compose rendering without weakening the standard
  production defaults.

The small-host profile is a controlled pilot configuration, not evidence of
general paid-traffic capacity.

## 20260716-rc7

- Separated public-benchmark/local-simulation evidence from buyer-external
  procurement evidence. Technical threshold passes remain auditable but can no
  longer make a project contract-ready.
- Added original-artifact, buyer-signoff, issuer, observation-time, external
  verification-reference, named-reviewer, and review-attestation controls for
  Gate 1–3.
- Required executed-contract SHA-256, both signatories, effective date, and an
  execution-attestation SHA-256 before a contract can be marked signed.
- Added compatible MySQL migrations and legacy-record warnings so historical
  simulation/reference-only records are not silently promoted.
- Extended container tests and commercial E2E to prove the simulation contract
  guard, positive external-evidence fixture path, restart persistence, and
  encrypted 15-table restore with the new fields.

RC7 proves deployable software behavior and fail-closed procurement state. It
does not turn Docker fixtures into buyer evidence or an executed agreement.

## 20260716-rc6

- Added buyer-requested and retention-expiry payload deletion with guarded file
  removal, HTTP 410 tombstones, immutable file-level SHA-256 receipts, operator
  review, account-export records, and deletion-SLA monitoring.
- Added the `data_deletion_requests` MySQL table and brought encrypted recovery
  reconciliation to 15 commercial, compliance, generation, procurement, and
  audit tables.
- Extended the Docker commercial acceptance flow to prove request, deletion,
  receipt, persistence, and non-downloadability after restart.
- Added independent release-archive verification covering outer and inner
  checksums, forbidden-path checks, both production Compose ingress renders,
  13-route smoke, 17 backend tests, real-generator commercial E2E, restart
  persistence, and protected operations health.

RC6 remains a deployable software release. It is not evidence of merchant
settlement, buyer-owned robot acceptance, or an executed procurement contract.
