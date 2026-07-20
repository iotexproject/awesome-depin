# Q-Tail MVP-to-procurement acceptance status

> Historical record. Superseded by
> [acceptance-status-2026-07-20-local-only.md](acceptance-status-2026-07-20-local-only.md).
> The RC22 Q-Tail pilot on port 6222 was retired on 2026-07-20 and the original
> legacy HTTP application was restored. The endpoint statements below describe
> the July 17 acceptance run and are not current availability claims.

Status date: 2026-07-17 (Asia/Shanghai; acceptance cycle started 2026-07-15)

## Decision

The repository is ready for a controlled MVP/design-partner pilot. The RC22
application and operations bundle is deployed on the controlled ECS host at
`https://8.153.83.178:6222`; its
MySQL-backed production stack, systemd lifecycle, monitoring, encrypted backup,
restart persistence, Pro catalog entitlement, protected catalog download, and
commercial acceptance flow have passed. The local Docker acceptance stack,
Q-Tail generation adapter, Gate workflow, contract draft, and isolated restore
drill have also passed.

This status proves a publicly reachable controlled-pilot HTTPS endpoint. It
does **not** claim canonical TCP/443/domain launch, payment merchant settlement,
buyer-owned robot trials, legal approval, or an executed procurement agreement.

## Latest persistent ECS acceptance

- Release: `qtail-forge-20260717-rc22` (RC21 buyer pilot kit plus an executable,
  fail-closed Gate 1 buyer-production-backend validator)
- Current release link: `/opt/qtail/current` →
  `/opt/qtail/releases/qtail-forge-20260717-rc22`
- Local release verification: `qtail-forge-20260717-rc22.verification.json`
  (`passed`), including 31 backend tests, the real Q-Tail generator commercial
  flow, request-contract/TFRecord unit coverage, backup/restore verification,
  monitoring, restart persistence, 16-route smoke, buyer-kit integrity and
  alternate-HTTPS Compose verification. Release archive SHA-256:
  `982456043e45d39aeafeda5313d3fcb2dbf2435530e9ba61bdcec3c065135b94`.
- Buyer pilot kit: `/buyer-kit/qtail-buyer-pilot-kit-v1.1.0.zip`, 11 blank
  Gate/SOW/signoff/contract templates plus the executable Gate 1 validator,
  SHA-256 `c86ffd52d795db08ea44dade69cf52c4afa9971d991ad7a037a932eb8b35e362`.
  The manifest sets `contract_eligibility=false`; downloading or completing a
  template is not buyer acceptance without the required external evidence and
  authorized signatures.
- Public production full E2E:
  `var/acceptance/rc20-production-public-6222-full-e2e.json` (`passed`, run
  `20260717T055829Z-37ca82a9`). Through the externally reachable trusted HTTPS
  endpoint with Secure cookies it completed registration, compliance, simulated
  manual payment/invoice/refund, Pro/API key, exact catalog download, a
  Q-Tail-weighted 8-episode/418-frame request-specific RLDS-compatible batch,
  three ordinary real-generator deliveries, deletion/tombstone, simulation
  evidence contract rejection, external-fixture contract hash flow, stateless
  service restart and byte-for-byte persistence.
- Request-specific trajectory delivery SHA-256:
  `64917694ab97d163bf19c082f4d625d04880665889454ef319fea3e01b783896`.
  Its source is the immutable catalog SHA-256
  `c58b39d83a1a9f9d72533ed2f33d8280bbf7fee98e28b3c082fca116894d2fb0`;
  the package declares `evidence_scope=simulation` and
  `buyer_gate_passed=false`.
- RC22 post-deployment encrypted backup:
  `/opt/qtail/backups/qtail-20260717T064559Z.tar.gz.enc`, SHA-256
  `c44f5a7adcf14b2c9c84bc6469c498f363c1c957d2270fbd66e3a64c83735edf`.
  The backup timer remained active and protected monitoring passed afterward.
- Production catalog acceptance:
  `var/acceptance/rc18-production-catalog-https.json` (`ok=true`). The
  trusted-loopback HTTPS run registered a production test user, activated Pro
  through an explicitly simulated manual-QR review, downloaded 56,447,787
  bytes, and matched SHA-256
  `c58b39d83a1a9f9d72533ed2f33d8280bbf7fee98e28b3c082fca116894d2fb0`.
- Full production HTTPS commercial acceptance:
  `var/acceptance/rc18.1-production-full-e2e.json` (`status=passed`) traversed
  Caddy/API/MySQL with Secure cookies, a simulated manual-QR order, Pro/API key,
  the protected catalog, three real-generator Worker jobs under the ECS-small
  one-job inflight limit, verified deletion/tombstone, sequential Gate review,
  simulation-to-contract rejection, fixture execution hashes, and restart
  persistence. Its claim boundary remains `simulation_only=true`.
- Evidence boundary: `evidence_scope=simulation`;
  `buyer_gate_passed=false`; `real_generator_fixture=false`.
- Production payment mode: `manual_qr_verification`; official merchant mode is
  fail-closed until real credentials and valid HTTPS callbacks are installed.
- Docker backend tests: 31/31 passed, including generated-key Alipay RSA2 and
  WeChat Pay API v3 callback/refund/idempotency coverage.
- Database/restore reconciliation: 16 critical tables, including immutable
  provider-event audit records.
- Delivery ZIP SHA-256:
  `966d38e4db7ce5e2249da3954699f679937c3b4d6596dd90bae55f107efe072f`
- Deletion receipt SHA-256:
  `1bc0076c718bccf1c636d55638b97c7fc49fa752d7416b6c20095fc8017eebc9`
- Contract negotiation draft SHA-256:
  `5a36bbe2c8e97172f31d79ebefff2ba583167d9def67d38a89abff65b64d8228`
- Execution-attestation SHA-256:
  `1603694603f1af4c41092ff8e35b14ee9a60d242bdeacf2b068b6cb18d6db17a`
- RC22 deployment persistence re-verification passed on 2026-07-17: the MySQL
  session, Pro entitlement, catalog metadata, protected download, exact byte
  count, generated jobs, deletion tombstone, Gate case, invoice/refund records,
  contract draft and execution-attestation fixture all remained byte- and
  hash-identical. MySQL remained online throughout the frontend/edge release.
- Host checks on 2026-07-17: db/API/Worker/web/edge healthy; protected monitor
  clear; `qtail.service`, backup, monitor, and certificate-renewal timers active.
  The post-deployment encrypted backup
  `qtail-20260717T060515Z.tar.gz.enc` completed successfully with SHA-256
  `b48a5355f26ac3738930b0920dc362737ee67eaee3d75e56426bf98239f71d19`;
  production HTTPS port 6222 remains available after edge/API/Worker/Web restart.
- The first RC18 HTTPS catalog probe exposed a host-permission defect: the
  read-only bind mount existed, but the non-root API user could not traverse the
  root-owned `0750` directory. Production permissions were corrected to a
  non-writable `0755` directory and `0644` catalog files; container readability,
  host immutability, metadata integrity, download headers, MySQL audit event,
  and post-restart download were then verified. RC18.1 preflight now rejects
  this permission state before activation.
- ECS isolated restore run `20260716T142145Z-host-restore` passed using a fresh
  encrypted production backup. All 16 production/restored table counts matched
  (`4/3/3/3/3/2/0/7/7/2/3/9/2/12/2/95`), all 55 delivery files matched, the
  temporary API health check passed, and the drill removed its containers,
  network, and volumes without modifying production volumes. Backup SHA-256:
  `fcf994dfdfe86d88bb811a86e987bca043b764ac29f320e89db9658c251eba89`.
  An encrypted copy was transferred off the ECS host and independently matched
  the same hash. Automated object-storage replication remains required.
- A macOS launchd job now pulls the latest encrypted ECS archive every six
  hours through the dedicated forced-command `qtailbackup` account. Its first
  restricted automatic run exited 0 after pinning the ECS ED25519
  fingerprint `SHA256:bipBCsgd/TnpQdyjx/2ffN2kv/4fS3NUbozSA843zs8` and matching
  remote/local SHA-256
  `312d8dc878b7f12e1a0954bf0b8fd16f04f5ee248bb93a2f18f67841751aaf9f`.
  The workstation has no backup decryption password. This is genuine off-host
  redundancy while that workstation is online, not multi-region object storage.
- ECS read-path load run on 2026-07-16 passed 600 requests at concurrency 16
  with zero errors, 608.72 requests/second, p95 67.06 ms and p99 293.87 ms.
  The protected monitor passed after the run. This evidence covers idempotent
  web/read paths and one API/MySQL health preflight only; it is not sustained
  model-generation throughput or merchant-settlement evidence.
- Public-origin status: Caddy has a valid Let's Encrypt certificate whose SAN
  is IP address `8.153.83.178`. `https://8.153.83.178:6222` passed an external
  trusted TLS handshake, HTTP/2/HSTS headers, 16-route smoke, browser rendering,
  full commercial E2E and post-restart persistence. Public TCP/443 still fails
  at the Alibaba security-group/network layer. Standard 443, an owned domain,
  DNS, filing/access path, and payment callback approval remain required for
  canonical paid launch.

## Earlier temporary public Docker acceptance

- Run ID: `20260715T153204Z-446b53c9`
- Public path: temporary Cloudflare HTTPS preview
- Database: MySQL
- Generator fixture: `false`
- Delivery package type: `qtail_data_engine_evaluation_package`
- Delivery package internal validation: `true`
- Delivery ZIP SHA-256:
  `11e0837d50642777822863f3cbf0f8f1cc31201990da882a99ebf08f51927933`
- Contract/SOW negotiation draft SHA-256:
  `96b75576886362f2b1d8d2052b4679b8e2da1a1b2eb6e0a2f8cf7f642c2a0131`
- Three real-model tasks were accepted as `202 queued`, executed by the
  independent Worker, downloaded, and assigned distinct SHA-256 values. The
  buyer then requested deletion of job
  `bd34f997-9be0-406f-85c7-986994081cc8`; operator completion produced receipt
  SHA-256 `334b299eaaea43bf02fd0d2e14a4d6ba73e90dee49fb766882b6d94c9e91543d`
  and the former download returned HTTP 410.
- Cold restart persistence: passed for the user, Pro entitlement, all three
  generation-job records, the two retained ZIPs, the deleted-job tombstone and
  receipt, procurement case, and byte-identical contract draft.

The automated flow covered Cloudflare → Nginx → API → MySQL,
registration/session, versioned Terms/Privacy/DPA acceptances, buyer compliance
submission/operator approval, per-generation source and derivative-rights
attestations, Pro enforcement, manual QR order review, invoice issuance/refund
review states, API application/approval, one-time API key, MySQL queue
submission, independent Worker execution, real Q-Tail package generation,
three ZIP downloads, a buyer deletion request and immutable deletion receipt,
sequential Gate 1–3 review, versioned acceptance and
compliance snapshots, contract reference archival, and owner-only contract
draft download. Its payment, invoice, refund, compliance, Gate, and contract
records are explicitly labelled Docker simulations.

## Gate evidence

| Gate | Reproducible evidence completed locally | External acceptance still required |
|---|---|---|
| Gate 0 | Product boundary is allocation/scenario intelligence; model/customer claims are separated and audited. | Buyer and counsel must accept the final SOW wording. |
| Gate 1 | 64 new Sawyer/MetaWorld/MuJoCo synthetic episodes, 3,285 frames, LeRobot v3 official loader/DataLoader and RLDS-compatible TFRecord validation passed; missing fields, non-finite values, and corrupt frames all zero. Manifest SHA-256 `003d5d62c92237412f86d72e796c4a5570e3a9760b1d40fee8c0f7f826f3c13a`. The prior 64-episode public Open X adapter baseline remains separately archived. | Run the agreed buyer tasks through the buyer-selected production backend, verify physical/sensor validity, and obtain signed buyer acceptance. |
| Gate 2 | The Q-Tail policy was retrained directly from the immutable Gate 1 package; feature/action hashes matched deterministic recollection. 900 MetaWorld closed-loop evaluations at the same 64-trajectory budget and same policy produced tail success +16.33 pp, paired 95% CI +12.00 to +20.67 pp, overall +10.44 pp, head -1.33 pp. Manifest SHA-256 `07a4d7bfc638031dc936e5e34390d69161b18812c590035ee356823ca0217c53`. | Independent buyer reproduction/acceptance on the frozen buyer protocol. |
| Gate 3 | Three local simulation tasks, nominal and perturbed conditions, 600 episodes; zero post-clip bounds/non-finite/exception failures; modeled unit-success cost reduction 24.02%. Manifest SHA-256 `bdf0c0fb51278a57dbe286f11e0121a3c539cea672556e911e747de45977dce6`. | 3–5 buyer tasks, real-robot trials, actual invoice-backed costs, safety owner, procurement owner, and signed acceptance. |

Gate 3 intentionally discloses 29,034 raw controller saturation events before
clipping. Local simulation is not presented as a real-robot safety pass.

## Operational evidence

- Backend integration/threshold/commercial/data-lifecycle suite: 27/27 passed in
  RC13, including generated-key official-provider signature, replay,
  amount/currency, exact-once entitlement, refund, and event-audit tests. The
  earlier lifecycle coverage included
  invoice issuance, red-letter gating, full-refund completion, Pro adjustment,
  API-key revocation, concurrent queue-cap enforcement, terminal retry failure,
  expired-lease recovery, backup pause behavior, idempotent buyer deletion,
  immutable deletion receipts, HTTP 410 tombstones, retention-expiry purge,
  buyer-external evidence provenance, and simulation-to-contract rejection.
- Public/local smoke suite: 13/13 health/routes/assets passed, including the DPA,
  protected compliance application shell, and both payment QR files.
- Idempotent public/read load probe: 1,200 requests, concurrency 64, 0 errors,
  3,385.05 requests/second, p95 27.55 ms, p99 34.61 ms on the acceptance host.
- The rebuilt five-service preview (`db`, `api`, `worker`, `web`, `edge`) passed
  protected monitoring plus the then-current smoke checks through both local HTTPS and a
  short-lived external HTTPS tunnel; queue depth, oldest queue age, Worker pause,
  and failed-job thresholds were all clear at verification time.
- A separate outbound-only Cloudflare Quick Tunnel rehearsal passed over real
  public HTTPS. Run `20260715T153204Z-446b53c9` completed registration/session,
  versioned compliance and data-rights approval, Pro enforcement, QR
  payment/invoice/refund workflow simulation, API approval and key creation,
  three asynchronously queued real-generator packages, verified deletion of
  one payload, Gate 1–3 review,
  compliance-blocked contract transition, contract-draft download, HSTS, and
  post-restart persistence. The
  `cloudflared` `/ready` health check confirmed a registered QUIC connection;
  the private DoH resolver handled SRV discovery on the restricted local network.
  This is transport/software evidence only, not a durable named deployment.
- The Quick Tunnel normal-traffic probe passed 120 requests at concurrency 4
  with zero errors and p95 2.28 s. A deliberately heavier 600-request,
  concurrency-32 probe failed with 25.67% QR-image timeouts on the anonymous
  single-connection tunnel. The local application baseline remained 1,200/64
  with zero errors; the failed public probe is retained as evidence that Quick
  Tunnel capacity must never be presented as production capacity.
- Every required production service now has a container health probe; monitoring
  rejects `starting`, `unhealthy`, and missing-health states for db, API, web,
  Worker, the non-public Caddy `/healthz` listener, Cloudflare connector, and
  private Tunnel DNS resolver according to the selected ingress mode.
- Worker fault injection: the reproducible crash drill killed the Worker during
  a leased job; after lease expiry a fresh Worker emitted exactly one
  `generation.requeued` audit event and completed job
  `c6e92fa1-f2c1-4898-acd7-8ac919aaf706` on attempt 2. The report is explicitly
  local simulation evidence, not an uptime SLA.
- Encrypted restore drill: the backup first paused new Worker claims and waited
  for running jobs to drain; database dump and delivery package checksums then
  verified. On 2026-07-16 an isolated destructive restore and the 13-route smoke
  suite passed; the latest RC13-preparation run reconciled 16 critical tables,
  including provider-event audit state, across identity,
  commercial, job/data-rights/deletion, compliance/legal, procurement, and
  audit state; 556 delivery files reconciled; temporary containers/volumes
  were removed.
- API and Worker containers: read-only root filesystems, all Linux capabilities dropped,
  `no-new-privileges`, resource limits, and log rotation enabled by the
  production Compose overlay.
- Caddy edge container: automatic HTTPS configuration validated; local HTTP/2,
  HTTP→HTTPS redirect, HSTS, internal certificate, Secure/HttpOnly/SameSite
  session cookie, read-only root filesystem, no capabilities, and
  `no-new-privileges` passed. HTTP/3 is intentionally disabled because public
  443 maps to the unprivileged container 8443 port.
- Server preflight: local production-config rehearsal passed its secret,
  Secure-cookie, real-generator, private-bind, asset, capacity, Compose, and
  Caddy and Cloudflare-mode checks. Production mode additionally requires a real
  resolving domain; direct Caddy ingress can pin it to the intended host with
  `EXPECTED_PUBLIC_IP`, while Tunnel mode deliberately rejects that origin-IP
  assertion and requires the connector token.
- Deployment archive: `qtail-forge-20260717-rc18.1.tar.gz`, outer SHA-256
  `a8afc11d0778b5d32fca48177cdbd1801f02ce9dbf8d02c621250fdaab8862cd`.
  The archive excludes
  secrets/runtime state and carries a verified per-file SHA-256 manifest. It was
  extracted into independent directories, the API/Worker/Web/Caddy and
  Cloudflare/DoH application images were built from those extractions, and
  HTTPS redirect, HSTS, API→MySQL health, public routes, both QR assets,
  ingress health checks, read-only filesystems, capability restrictions, and
  `no-new-privileges` passed. The RC18.1 verifier additionally runs 13-route smoke,
  all 27 backend tests, generated-key official-payment cryptography tests, the
  real-generator commercial workflow, Pro catalog byte/SHA verification, the
  simulation-to-contract guard, executed-contract attestation, a verified
  payload deletion and HTTP 410 tombstone, cold restart persistence, backup
  replication, and protected operations monitoring. Its machine-readable
  evidence is stored in the adjacent `.verification.json` sidecar.
- Named-Tunnel secret regression: Docker Compose 5.0.2 did not materialize the
  original environment-sourced secret despite accepting the configuration.
  RC4 replaced it with a mode-0600 file-backed Compose secret; RC7 retains that
  fix while adding compliance/data-rights contract controls, verified payload
  deletion, and a repeatable independent release verifier. An actual
  container-create/start audit confirmed the value is readable through
  `/run/secrets`, mounted read-only, and absent from the container command,
  environment, and `docker inspect` metadata.

## External launch conditions

The following cannot be manufactured by Docker or public datasets and remain
required before accepting general paid production traffic or claiming a buyer
procurement pass:

1. Attach a controlled production domain to the persistent ECS deployment;
   complete DNS, trusted TLS, the selected mainland filing/access path, firewall,
   secret rotation, off-host backup, alert delivery, and host restore/load drills.
2. Complete legal/tax review, verified company address/contact publication, and
   the hosting/filing path selected for the production jurisdiction.
3. Continue manual QR verification with an accountable operator, or complete
   official WeChat Pay/Alipay merchant onboarding, signed callbacks, refunds,
   reconciliation, and invoices. A customer-entered reference is never proof of
   settlement.
4. Collect and approve buyer-owned Gate 1, Gate 2, and Gate 3 evidence using the
   supplied templates and validator.
5. Have authorized representatives execute the negotiated procurement/SOW
   document. Only then record the external contract/archive reference as signed.

The ECS deployment is persistent, but it must not receive confidential buyer
data or real automated payments until the trusted domain/TLS and merchant
callback acceptance items above pass. Any temporary tunnel remains QA-only.
