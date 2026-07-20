# Q-Tail Forge API

Base URL: `https://<your-domain>`

The web application uses an HttpOnly session cookie. Programmatic generation accepts an API key in `X-API-Key`. An API key can be created only after an operator approves the API application and a verified payment activates Pro.

## Health

```bash
curl https://<your-domain>/api/health
```

## List and download the fixed synthetic sample

The catalog is available only to an active Pro session or API key. The list
response reports availability only after the mounted archive passes exact byte
and SHA-256 checks:

```bash
curl --header 'X-API-Key: qtail_live_...' \
  'https://<your-domain>/api/catalogs'

curl --fail --location \
  --header 'X-API-Key: qtail_live_...' \
  --output qtail-gate1-metaworld-sawyer-v0.1.0.tar.gz \
  'https://<your-domain>/api/catalogs/metaworld-sawyer-v0.1.0/download'

sha256sum qtail-gate1-metaworld-sawyer-v0.1.0.tar.gz
# c58b39d83a1a9f9d72533ed2f33d8280bbf7fee98e28b3c082fca116894d2fb0
```

The response includes `X-Content-SHA256` and
`X-QTail-Evidence-Scope: simulation`. Every successful download creates an
audit event. This 64-trajectory, 3,285-frame MetaWorld/Sawyer package is a
fixed Q-Tail technical sample in LeRobotDataset v3 and RLDS-compatible
TFRecord—not buyer-selected production, real-robot evidence, or procurement
acceptance.

## Create a request-specific simulation trajectory batch

Use the same asynchronous endpoint with a locked delivery contract:

```json
{
  "delivery_product": "simulation_trajectory_batch",
  "trajectory_count": 16,
  "robot_model": "Sawyer / MetaWorld",
  "control_frequency_hz": 20,
  "sensors": "256x256 RGB + 39D state",
  "training_format": "RLDS",
  "production_backend": "MuJoCo / MetaWorld",
  "synthetic_budget": 100000,
  "csv_text": "task,count\nreach-v3,50\nbutton-press-v3,7\npick-place-v3,7\n",
  "data_rights": {
    "source_type": "customer_owned",
    "license_basis": "Customer-owned task selection",
    "contains_personal_data": false,
    "retention_days": 90,
    "source_rights_confirmed": true,
    "derivative_rights_confirmed": true,
    "restricted_data_excluded": true
  },
  "claim_acknowledged": true
}
```

`trajectory_count` must be 1–64 and no smaller than the requested task count.
The current source supports `reach-v3`, `button-press-v3`, and
`pick-place-v3`. The Worker runs Q-Tail allocation, verifies the exact source
archive and internal manifest SHA-256 values, and copies complete TFRecord
episodes into a request-specific ZIP. The ZIP includes the allocation plan,
selection index, robot contract, dataset metadata, source manifest and
per-file hashes. It always declares `evidence_scope=simulation` and
`buyer_gate_passed=false`; it is not buyer-selected production, independent
closed-loop evidence, real-robot evidence, or procurement acceptance.

## Create a generation

```bash
curl --request POST 'https://<your-domain>/api/generations' \
  --header 'Content-Type: application/json' \
  --header 'X-API-Key: qtail_live_...' \
  --data-binary '{
    "filename": "customer_tasks.csv",
    "robot_model": "Buyer Robot V1",
    "control_frequency_hz": 50,
    "sensors": "RGB-D, joint state, gripper",
    "training_format": "LeRobot v3",
    "production_backend": "Buyer trajectory production pipeline",
    "synthetic_budget": 100000,
    "data_rights": {
      "source_type": "customer_owned",
      "license_basis": "Customer-owned task statistics",
      "contains_personal_data": false,
      "retention_days": 90,
      "source_rights_confirmed": true,
      "derivative_rights_confirmed": true,
      "restricted_data_excluded": true
    },
    "claim_acknowledged": true,
    "csv_text": "task,count\npick red cube,120\nplace in bin,80\n"
  }'
```

Required input contract:

- `robot_model`
- `control_frequency_hz` between 1 and 1000
- `sensors`
- `training_format` containing `RLDS` or `LeRobot`
- `production_backend`
- `csv_text` with at least one data row, one task-like column, and one count-like column
- `synthetic_budget` between 100 and 10,000,000
- `data_rights` with source/license basis, 7–3650-day retention, no personal
  data, and explicit source, derivative, and restricted-data attestations
- confirmation of the current claim boundary

The request is asynchronous. A successful response is `202 Accepted` and
includes `job_id`, `status=queued`, `status_url`, and `gate_evaluation`. Gate 0
and the Gate 1 input contract must pass before the request is committed to the
MySQL queue. The independent Worker uses a renewable lease and bounded retries;
an API restart does not discard an accepted task.

Poll one task until it reaches a terminal state:

```bash
curl 'https://<your-domain>/api/generations/<job-id>' \
  --header 'X-API-Key: qtail_live_...'
```

`queued` and `running` are non-terminal. `completed` supplies `download_url`;
`failed` supplies a sanitized `error_message` after the retry budget is
exhausted. Gate 2 and Gate 3 remain `not_validated` until buyer-owned
closed-loop and real-robot evidence is attached.

The canonical data-rights attestation is versioned, SHA-256 hashed, stored in
MySQL, returned with the job, and included in a later contract acceptance
snapshot. The shared service rejects data declared to contain personal
information; such processing first requires an approved DPA and private/VPC or
on-premises boundary.

## List runs

```bash
curl 'https://<your-domain>/api/generations' \
  --header 'X-API-Key: qtail_live_...'
```

## Download a delivery package

```bash
curl --fail --location \
  --header 'X-API-Key: qtail_live_...' \
  --output qtail-delivery.zip \
  'https://<your-domain>/downloads/<job-id>'
```

## Payload retention and verified deletion

The authenticated buyer—not an API key—can request deletion after a job reaches
`completed` or `failed`:

```bash
curl --request POST 'https://<your-domain>/api/generations/<job-id>/deletion-request' \
  --cookie qtail_session=... \
  --header 'Content-Type: application/json' \
  --data-binary '{"reason":"Pilot ended; remove input and delivery payloads."}'
```

The request receives a deadline from the approved compliance profile's deletion
SLA, or 30 days before a profile exists. Operators can complete or reject a
request with `POST /api/admin/data-deletion-requests/<id>/complete|reject`.
The Worker automatically completes requests at their deadline and creates the
same workflow when a job's per-request `retention_days` expires. Backup pause
also pauses deletion so database and file snapshots cannot race.

Completion removes the guarded job directory, nulls stored input/output paths,
and returns HTTP `410 payload_deleted` for later downloads. Q-Tail retains only
the generation/input hash, rights attestation, deletion manifest SHA-256, audit
events, Gate evidence hashes, and contract snapshot required for provenance and
legal/accounting defense. The deletion receipt records every removed relative
path, pre-deletion file SHA-256, byte count, and a canonical receipt SHA-256.

## Procurement Gate workflow

Procurement endpoints use the authenticated buyer session cookie because they belong to the logged-in Pro workspace. They do not accept `X-API-Key`. A case can be created only from one of that buyer's completed generation jobs that passed Gate 0.

### Download the buyer pilot kit

The evidence room and authenticated Gate workspace expose a versioned blank
package at `/buyer-kit/qtail-buyer-pilot-kit-v1.2.0.zip`. Its adjacent
`.zip.sha256` file fixes the archive bytes and `/buyer-kit/manifest.json`
contains per-file byte counts and hashes. The package includes the SOW,
Gate-specific API payloads, closed-loop ledger, real-robot trial ledger,
invoice/cost ledger, buyer-signoff template and executed-contract checklist.
Version 1.2 includes `tools/validate_gate1_delivery.py`, a standard-library
validator for the buyer-produced dataset package, production log, robot
contract, trajectory/frame counts and declared hashes. A passing validation
report remains `contract_eligible=false` and `buyer_signoff_required=true`.
The contract checklist separately records provider and buyer signature-proof
SHA-256 values; the two values must both be valid and must not be identical.

Every Gate JSON uses the exact field names accepted by the endpoints below but
defaults to non-passing booleans, null metrics and visibly invalid hash
placeholders. Downloading or hashing the blank kit never creates procurement
evidence. The buyer must populate it from the frozen external protocol, sign
outside Q-Tail, and submit the resulting original/signoff hashes.

### List cases and eligible jobs

```bash
curl --cookie qtail_session=... \
  'https://<your-domain>/api/procurement-cases'
```

The response contains `cases`, `eligible_jobs`, and the authoritative `gate_definitions`. Each case includes Gate 0–3 status, the latest evidence record for each Gate, and its contract record when one exists.

### Create a case

```bash
curl --request POST 'https://<your-domain>/api/procurement-cases' \
  --cookie qtail_session=... \
  --header 'Content-Type: application/json' \
  --data-binary '{
    "generation_job_id": "<completed-job-id>",
    "title": "Rare Pick Buyer Pilot",
    "buyer_owner": "Buyer acceptance owner",
    "pilot_scope": "3–5 tail tasks"
  }'
```

### Submit Gate evidence

Use `POST /api/procurement-cases/<case-id>/gates/<1|2|3>/evidence`. Gates unlock sequentially and each accepted payload is canonicalized and assigned an `evidence_sha256` before operator review.

Every submission must declare `evidence_scope`:

- `simulation` records a public benchmark, local simulation, or technical baseline. It can pass the numerical threshold and unlock the next technical Gate, but it is never contract eligible.
- `buyer_external` is reserved for evidence produced or accepted outside Q-Tail by the buyer or an independent verifier. It additionally requires `evidence_issuer`, `evidence_artifact_sha256`, `buyer_signoff_sha256`, and ISO-8601 `evidence_observed_at`. External Gates unlock sequentially against the preceding approved external Gate.

Gate 1 requires:

- `trajectory_count` greater than 0
- `schema_validation_passed` and `sample_playback_passed`
- a 64-character hexadecimal `dataset_manifest_sha256`
- an absolute `production_log_url`

Gate 2 requires:

- `same_policy` and `same_budget`
- `baseline_name` and positive `evaluation_episodes`
- `tail_sr_gain_pp >= 5`
- `ci95_lower_pp > 0`
- `overall_gain_pp >= -1`
- `head_gain_pp >= -2`
- an absolute `evaluation_report_url`

Gate 3 requires:

- `tail_task_count` between 3 and 5
- `simulation_episodes_per_condition >= 100`
- `real_robot_trials_per_task >= 30`
- `unit_cost_reduction_pct >= 20`
- `safety_review_passed`
- `buyer_acceptance_owner`
- an absolute `validation_report_url`

An automatic pass creates a `received` record; it does not approve buyer acceptance by itself. The response exposes `contract_eligible=false` until an operator performs the external-artifact review.

## Compliance and data-rights profile

Authenticated buyers use `GET /api/compliance` and `PUT /api/compliance` to
submit the organization legal name, security contact, deployment boundary,
data residency, retention/deletion terms, source and derivative rights, and
acceptance of the current terms, privacy notice, and DPA versions. Each profile
version receives a canonical SHA-256 and enters operator review.

`POST /api/admin/compliance-profiles/<user-id>/approve` or `/reject` requires
the operator token. Gate 1–3 approval alone no longer makes a case contract
ready: the current compliance profile and all required legal document versions
must also be approved/accepted. The profile hash, document acceptance hashes,
and per-job data-rights hash enter the immutable contract snapshot.

## Operator procurement endpoints

Operator requests require `X-Admin-Token` and are intended for the protected operator console:

| Method and path | Transition |
|---|---|
| `POST /api/admin/procurement-evidence/<id>/approve` | `received` → `approved`; external evidence requires `verification_reference`, `reviewer_name`, and a specific `review_note`, then receives a review-attestation SHA-256 |
| `POST /api/admin/procurement-evidence/<id>/reject` | `received` → `rejected` with a review note; buyer can resubmit |
| `POST /api/admin/procurement-cases/<id>/issue-contract` | Requires approved buyer-external Gate 1–3 evidence plus approved compliance; otherwise returns `external_evidence_required`; creates/reuses a versioned immutable acceptance snapshot |
| `POST /api/admin/procurement-contracts/<id>/mark-signed` | Requires `contract_reference`, executed-document SHA-256, both signatory names, distinct `provider_signature_sha256` and `buyer_signature_sha256`, and effective date; records an execution-attestation SHA-256 before the case becomes `contracted` |
| `POST /api/admin/data-deletion-requests/<id>/complete` | Deletes guarded input/delivery files and records the immutable deletion receipt |
| `POST /api/admin/data-deletion-requests/<id>/reject` | Returns a premature/ambiguous request with an auditable reason; retention expiry can reactivate it |

An authenticated contract owner can download
`GET /api/procurement-contracts/<contract_id>/draft`. It returns a private,
non-cacheable Markdown procurement/SOW negotiation draft containing the project
scope, approved Gate evidence hashes, and the canonical acceptance-snapshot
SHA-256. The file is explicitly a negotiation draft; it cannot create or mimic
an external signature.

## Invoice and refund operations

| Endpoint | Behavior |
|---|---|
| `POST /api/payments/alipay/notify` | Public Alipay RSA2 notification endpoint; verifies signature, app/seller, order, CNY amount and settled status before exactly-once Pro activation |
| `POST /api/payments/wechat/notify` | Public WeChat API v3 payment/refund endpoint; verifies platform key id, replay window and signature, decrypts AES-GCM resource, then validates merchant/app/order/amount |
| `POST /api/payment-orders/<id>/invoice-requests` | Paid, non-refunded order owner submits title, 15–20-character taxpayer ID, and invoice email |
| `POST /api/payment-orders/<id>/refund-requests` | Paid order owner requests one full original-channel refund; no entitlement changes occur yet |
| `POST /api/admin/invoice-requests/<id>/issue` | Records a real external tax invoice number and optional HTTPS document link |
| `POST /api/admin/invoice-requests/<id>/cancel` | Records the real red-letter/cancellation reference for an issued invoice |
| `POST /api/admin/refund-requests/<id>/approve` | Manual orders enter approved review; official orders immediately attempt an idempotent original-channel refund unless invoice cancellation is required |
| `POST /api/admin/refund-requests/<id>/initiate` | Retries an approved/failed official refund using the same merchant refund number |
| `POST /api/admin/refund-requests/<id>/complete` | Manual orders only: requires a real original-channel reference and completed invoice cancellation, then updates entitlement; official refunds reject manual completion |

Official callbacks never accept a browser session or operator assertion as proof
of settlement. Authenticated provider events have a unique `(channel,event_id)`,
payload SHA-256 and signature-serial record; a second notification cannot extend
the entitlement twice. All actions create audit events. Docker acceptance
invoice/refund identifiers and generated-key callbacks are explicit simulations,
not tax documents or settlement evidence.

These endpoints record workflow state and evidence provenance. They do not generate a legal signature or substitute test/example evidence for real buyer acceptance.

## Response and error semantics

All JSON responses include `ok`. Errors include a stable `error.code` and human-readable `error.message`.

| HTTP | Common code | Meaning |
|---:|---|---|
| 401 | `authentication_required` | Missing or invalid session/API key |
| 402 | `pro_required` | Pro is not active |
| 403 | `api_access_not_approved` | API review has not been approved |
| 413 | `csv_too_large` / `payload_too_large` | Request exceeds the configured limit |
| 422 | `gate_validation_failed` / `trajectory_contract_invalid` / `gate_thresholds_not_met` / `data_rights_attestation_required` | Input, trajectory-source, evidence, or data-rights contract failed |
| 409 | `external_evidence_required` / `compliance_not_approved` | Contract issuance/signing is blocked pending buyer-external Gate evidence or approved rights/DPA/security evidence |
| 410 | `payload_deleted` | Input and delivery payloads were deleted; the response includes the deletion receipt hash |
| 429 | `daily_quota_exceeded` | Pro daily generation quota reached |
| 429 | `active_queue_limit_exceeded` | Buyer already has the maximum queued/running tasks |

Model execution failures are reported through the job resource rather than the
initial `202` response. The Worker records each start, retry, expired-lease
requeue, completion, and terminal failure in the audit log.

API keys are displayed once. Store them in a secret manager, never in frontend code or source control. Generated delivery packages contain allocation and scenario-planning artifacts; they are not represented as trainable trajectories or measured policy improvement.
