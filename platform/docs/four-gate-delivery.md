# Four-gate delivery standard

The website makes procurement readiness observable instead of turning an MVP demo into an unsupported purchasing claim.

The public evidence room provides a versioned buyer pilot kit containing the
SOW, robot/data contract, exact Gate 1–3 submission payloads, per-run evaluation
and real-robot ledgers, invoice/cost ledger, buyer-signoff template, contract
execution checklist, and a standalone Gate 1 production-backend validator. Its
deterministic ZIP, archive sidecar and per-file manifest can be verified
independently. All templates are blank and default to failure; the package
itself is never buyer evidence.

| Gate | Commercial question | Acceptance evidence | Current platform state |
|---|---|---|---|
| Gate 0 — redefine the product | Is the buyer purchasing an allocation/scenario intelligence layer rather than falsely labeled trajectory data? | Claim boundary acknowledged; input and output hashes; model card and delivery manifest | **Implemented and testable** |
| Gate 1 — produce trainable trajectories | Can the allocation plan be executed by a configured production backend into the buyer's RLDS/LeRobot contract? | Positive trajectory count; schema validation and sample playback; immutable manifest SHA-256; production log URL | **Submission, automatic checks, review, and audit chain implemented; real buyer trajectory evidence still required** |
| Gate 2 — closed-loop comparison | Does the Q-Tail route improve tail performance without unacceptable overall/head regression? | Same-policy/same-budget baseline vs Q-Tail; tail gain at least +5 pp; 95% CI lower bound above 0; overall at least -1 pp; head at least -2 pp; report URL | **Submission, threshold checks, review, and audit chain implemented; real controlled study still required** |
| Gate 3 — real robot and commercial proof | Is the result repeatable, safe, cheaper, and contractable in the buyer's production setting? | 3–5 tail tasks; at least 100 simulation episodes per condition; at least 30 real-robot trials per task; at least 20% unit-cost reduction; safety review; named buyer owner and report URL; approved compliance/data-rights profile | **Submission, threshold checks, compliance block, review, and contract transition implemented; real buyer trials and acceptance still required** |

## Delivery package at each stage

### Gate 0 package

- Input checksum and immutable job identifier
- Long-tail allocation plan and scenario specifications
- Model card, README, effect summary, and package manifest
- Explicit statement that no trainable trajectory or policy uplift is being claimed

### Gate 1 package

- Buyer task-frequency CSV and schema validation
- Robot model, control frequency, sensor contract, and RLDS/LeRobot format
- Named production backend and execution logs
- Generated dataset sample, playback/decoder check, and acceptance report
- Executable validation of the dataset/log hashes, robot contract, task/format,
  trajectory/frame counts, and Q-Tail source job

The application separates `simulation` from `buyer_external` evidence. Both can be threshold-checked and audited, but only external evidence containing the original-artifact hash, buyer-signoff hash, issuer, and observation time can be independently reviewed for contract eligibility. The configured production backend must still execute in the buyer environment; a test payload is not production evidence. The Gate 1 validator's technical pass remains `contract_eligible=false` until the buyer signs and the operator verifies the frozen originals.

### Gate 2 package

- Frozen baseline and Q-Tail experiment protocol
- Seed list, environment versions, stratified head/tail task set
- Success-rate table with confidence intervals and regression guardrails
- Reproducible analysis and signed buyer review

### Gate 3 package

- Simulation and real-robot trial logs
- Safety/incident record and failed-case review
- Cost-per-accepted-trajectory and total cost comparison
- Procurement acceptance, data rights, SLA, security terms, and commercial order form
- Versioned Terms, Privacy, and DPA acceptance hashes plus approved deployment,
  residency, retention, and deletion controls

## Contract rule

Only evidence already produced can be marked passed. Technical and buyer-external tracks unlock sequentially: automatic threshold pass → operator approval → next Gate at the same evidence level. Simulation/public-benchmark approval never sets `contract_ready`. Contract readiness requires reviewed buyer-external Gate 1–3 records, each with an immutable evidence hash, buyer-signoff hash, verification reference, named reviewer, and review-attestation SHA-256. The buyer must also submit the current legal-document versions, data-rights confirmations, and security/deployment controls, and an operator must approve that compliance profile.

An operator can then issue a versioned contract record containing the immutable external-evidence snapshot, compliance-profile hash, legal-acceptance hashes, and source/derivative-rights attestation hash. The buyer can download a Markdown procurement/SOW negotiation draft containing the scope, evidence hashes, acceptance-snapshot hash, and required commercial blanks. The draft is not an executed agreement. The project becomes `contracted` only after an operator records the external contract/archive reference, executed-contract SHA-256, both signatories, effective date, and the derived execution-attestation SHA-256. Legacy records that lack these proofs remain visibly labeled as unverified.

The platform does not manufacture a legal signature or treat example URLs as buyer proof. Automated Docker cases are explicitly marked simulation-only even when they exercise the positive external-evidence code path. Production procurement claims require buyer-owned reports, logs, trials, safety review, and an actual executed agreement.
