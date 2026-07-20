# Q-Tail local-only acceptance status

Status date: 2026-07-20 (Asia/Shanghai)

## Decision

Q-Tail Forge is authorized for local development and local Docker acceptance
only. The former RC22 Q-Tail pilot on server port 6222 has been retired and the
original legacy HTTP application has been restored on that port. No current
Q-Tail public endpoint is claimed.

No remote server may be connected to, inspected, deployed to, restarted, or
reconfigured unless the user gives explicit permission for that specific action
in the current conversation.

## Current verified local scope

- Fundraising homepage, authenticated Pro console, and investor/procurement
  evidence room.
- MySQL-backed registration, login, sessions, API applications, API keys, Pro
  entitlements, payment orders, generation jobs, data rights, deletion records,
  procurement evidence, contracts, and audit events.
- Manual WeChat/Alipay QR review flow and software-complete official Alipay RSA2
  / WeChat Pay API v3 checkout, callback, idempotency, refund, and entitlement
  state machines using generated test keys.
- Real Q-Tail allocation/scenario generation plus a fixed, verified
  Sawyer/MetaWorld simulation catalog and request-specific RLDS-compatible
  batches.
- Simulation evidence remains `buyer_gate_passed=false` and cannot unlock a
  procurement contract.
- Buyer pilot kit v1.2.0, fail-closed Gate 1 validator, and separate provider /
  buyer signature-proof SHA-256 archival fields.

## Verification at status update

- Frontend production build: passed.
- Backend unit/integration/threshold/lifecycle suite: 31/31 passed.
- Full local Docker rebuild and end-to-end acceptance: passed at
  `http://127.0.0.1:28080` in isolated project `qtail-local-20260720`.
- Public-route smoke: 16/16 passed, including both supplied payment QR images
  and the buyer pilot kit plus checksum.
- Commercial workflow report:
  `var/acceptance/20260720-local-contract-integrity-e2e.json`
  (`status=passed`, run `20260720T025134Z-ae3cde38`).
- The run completed registration/session, compliance approval, simulated manual
  QR payment, Pro activation, invoice/refund review state, API approval and
  one-time key creation, three real Q-Tail generation jobs, verified deletion,
  sequential Gate review, simulation-to-contract rejection, external-fixture
  contract hashes, and contract draft download.
- The fixed catalog download matched 56,447,787 bytes and SHA-256
  `c58b39d83a1a9f9d72533ed2f33d8280bbf7fee98e28b3c082fca116894d2fb0`.
- The Q-Tail-weighted on-demand batch contained 8 trajectories / 418 frames,
  preserved TFRecord framing, and remained `evidence_scope=simulation` with
  `buyer_gate_passed=false`. Delivery SHA-256:
  `1b9ca79629549a74563eb26cf5d1eaf6de72e9beda951880a92f94bbef885c48`.
- The contract-integrity fixture stored distinct provider and buyer signature
  proof hashes (`fd9101…90c62` / `96c625…61175`) and bound both to execution
  attestation SHA-256
  `008d60772df1ef2724b88b6b6456fb24329c21099b339253ba0c5d0e4adb040f`.
  Identical proof hashes are rejected before the case can become contracted.
- Buyer pilot kit v1.2.0 independently verified with archive SHA-256
  `db4b6432ee91dbb8cb7851dc8f4094e9b2d1329023c4fa935426c7647afd78ff`.
- After restarting the local API, Worker and Web containers, persistence
  verification passed for MySQL identity/Pro state, jobs, byte-identical
  retained deliveries, the deletion tombstone, invoice/refund states,
  procurement case, contract draft, both independent signature-proof hashes,
  and execution-attestation hash.

## Still external and incomplete

- Real merchant credentials, approved HTTPS callbacks, low-value live payment,
  settlement reconciliation, invoice and original-channel refund evidence.
- Buyer-selected production backend execution and signed Gate 1 acceptance.
- Independent buyer Gate 2 reproduction and signed acceptance.
- Real-robot Gate 3 trials, safety/procurement owners, actual invoice-backed
  costs, and signed acceptance.
- A procurement contract signed by both authorized parties with real archived
  executed-document, separate provider/buyer signature-proof, and final
  attestation hashes.
- Any newly authorized public deployment, owned domain, DNS/TLS and applicable
  filing/access approvals.

Historical RC18–RC22 evidence remains useful for reproducibility and release
engineering, but it must not be presented as proof of current public
availability or buyer acceptance.
