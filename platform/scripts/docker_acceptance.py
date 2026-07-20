#!/usr/bin/env python3
"""End-to-end Docker acceptance test for the Q-Tail commercial workflow.

The generated procurement record is explicitly labelled as a Docker simulation.
It proves the software workflow and persistence, not real-robot or buyer evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import http.cookiejar
import io
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "var" / "acceptance" / "latest.json"
ACCEPTANCE_PASSWORD = "Docker-Acceptance-2026!"
CATALOG_SLUG = "metaworld-sawyer-v0.1.0"
CATALOG_SHA256 = "c58b39d83a1a9f9d72533ed2f33d8280bbf7fee98e28b3c082fca116894d2fb0"
CATALOG_BYTES = 56_447_787


class ResolvedHTTPSConnection(http.client.HTTPSConnection):
    """Keep TLS SNI/certificate validation while connecting to a fixed address."""

    def __init__(self, host: str, resolve_address: str, resolve_port: int, **kwargs):
        self.resolve_address = resolve_address
        self.resolve_port = resolve_port
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        original_host, original_port = self.host, self.port
        self.host, self.port = self.resolve_address, self.resolve_port
        try:
            http.client.HTTPConnection.connect(self)
        finally:
            self.host, self.port = original_host, original_port
        server_hostname = self._tunnel_host or original_host
        self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)


class ResolvedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, resolve_address: str, resolve_port: int):
        super().__init__()
        self.resolve_address = resolve_address
        self.resolve_port = resolve_port

    def https_open(self, request):
        def connection(host, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, **kwargs):
            return ResolvedHTTPSConnection(
                host,
                self.resolve_address,
                self.resolve_port,
                timeout=timeout,
                **kwargs,
            )

        return self.do_open(connection, request, context=self._context)


def parse_https_resolution(base_url: str, resolve_spec: str | None) -> tuple[str, int] | None:
    if not resolve_spec:
        return None
    parts = resolve_spec.rsplit(":", 2)
    if len(parts) != 3 or not parts[0] or not parts[1] or not parts[2]:
        raise ValueError("--resolve must use HOST:PORT:ADDRESS")
    resolve_host, port_text, resolve_address = parts
    parsed = urllib.parse.urlsplit(base_url)
    expected_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if parsed.scheme != "https":
        raise ValueError("--resolve is supported only with an HTTPS base URL")
    if resolve_host != parsed.hostname or not port_text.isdigit() or int(port_text) != expected_port:
        raise ValueError("--resolve host and port must exactly match the HTTPS base URL")
    return resolve_address, int(port_text)


class Client:
    def __init__(
        self,
        base_url: str,
        default_headers: dict[str, str] | None = None,
        resolve_spec: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.default_headers = default_headers or {}
        self.cookies = http.cookiejar.CookieJar()
        handlers: list = [urllib.request.HTTPCookieProcessor(self.cookies)]
        resolution = parse_https_resolution(self.base_url, resolve_spec)
        if resolution:
            handlers.append(ResolvedHTTPSHandler(*resolution))
        self.opener = urllib.request.build_opener(*handlers)

    def request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        headers = {"Accept": "application/json", **self.default_headers}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=300) as response:
                body = response.read()
                return response.status, json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read()
            try:
                parsed = json.loads(body.decode("utf-8"))
            except Exception:
                parsed = {"raw": body.decode("utf-8", errors="replace")}
            return error.code, parsed

    def download(self, path: str) -> tuple[int, bytes, str]:
        request = urllib.request.Request(
            self.base_url + path,
            headers={"Accept": "application/zip", **self.default_headers},
            method="GET",
        )
        try:
            with self.opener.open(request, timeout=300) as response:
                return response.status, response.read(), response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers.get("Content-Type", "")


def expect(status: int, expected: int, body: dict, label: str) -> dict:
    if status != expected:
        raise RuntimeError(f"{label}: expected HTTP {expected}, got {status}: {body}")
    return body


def post(client: Client, path: str, payload: dict, expected: int = 200, label: str | None = None) -> dict:
    status, body = client.request("POST", path, payload)
    return expect(status, expected, body, label or path)


def get(client: Client, path: str, expected: int = 200, label: str | None = None) -> dict:
    status, body = client.request("GET", path)
    return expect(status, expected, body, label or path)


def wait_for_generation(client: Client, job_id: str, timeout_seconds: float = 300.0) -> dict:
    deadline = time.monotonic() + timeout_seconds
    observed = []
    while time.monotonic() < deadline:
        job = get(client, f"/api/generations/{job_id}", label="generation status")
        observed.append(job.get("status"))
        if job.get("status") == "completed":
            job["observed_statuses"] = list(dict.fromkeys(observed))
            return job
        if job.get("status") == "failed":
            raise RuntimeError(f"generation failed after retries: {job}")
        time.sleep(0.5)
    raise RuntimeError(f"generation timed out; observed statuses: {observed[-20:]}")


def gate_payload(gate_number: int, run_id: str, evidence_scope: str = "simulation") -> dict:
    evidence_url = f"https://docker-simulation.invalid/{run_id}/gate-{gate_number}"
    common = {
        "evidence_scope": evidence_scope,
        "evidence_notes": "Docker workflow fixture only; not real buyer, real-robot or procurement evidence.",
    }
    if evidence_scope == "buyer_external":
        common.update({
            "evidence_issuer": "Docker Buyer-External Contract Fixture",
            "evidence_artifact_sha256": hashlib.sha256(f"{run_id}:artifact:{gate_number}".encode()).hexdigest(),
            "buyer_signoff_sha256": hashlib.sha256(f"{run_id}:buyer-signoff:{gate_number}".encode()).hexdigest(),
            "evidence_observed_at": datetime.now(UTC).isoformat(),
        })
    if gate_number == 1:
        return {
            **common,
            "trajectory_count": 480,
            "schema_validation_passed": True,
            "sample_playback_passed": True,
            "dataset_manifest_sha256": hashlib.sha256(f"{run_id}:gate1".encode()).hexdigest(),
            "production_log_url": evidence_url,
        }
    if gate_number == 2:
        return {
            **common,
            "same_policy": True,
            "same_budget": True,
            "baseline_name": "docker-simulation-baseline",
            "tail_sr_gain_pp": 6.2,
            "ci95_lower_pp": 1.1,
            "overall_gain_pp": 0.2,
            "head_gain_pp": -0.4,
            "evaluation_episodes": 800,
            "evaluation_report_url": evidence_url,
        }
    if gate_number == 3:
        return {
            **common,
            "tail_task_count": 3,
            "simulation_episodes_per_condition": 120,
            "real_robot_trials_per_task": 30,
            "unit_cost_reduction_pct": 20,
            "safety_review_passed": True,
            "buyer_acceptance_owner": "Docker Simulation QA",
            "validation_report_url": evidence_url,
        }
    raise ValueError(f"Unsupported gate: {gate_number}")


def run_acceptance(
    base_url: str,
    admin_token: str,
    report_path: Path,
    resolve_spec: str | None = None,
    max_inflight_jobs: int = 3,
) -> dict:
    if not 1 <= max_inflight_jobs <= 3:
        raise ValueError("max_inflight_jobs must be between 1 and 3")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    email = f"docker-acceptance-{run_id.lower()}@qtail.invalid"
    user = Client(base_url, resolve_spec=resolve_spec)
    admin = Client(base_url, {"X-Admin-Token": admin_token}, resolve_spec=resolve_spec)

    health = get(user, "/api/health", label="health")
    if health.get("database") != "mysql" or health.get("ok") is not True:
        raise RuntimeError(f"health did not confirm MySQL: {health}")

    registered = post(user, "/api/auth/register", {
        "name": "Docker Acceptance Buyer",
        "company": "Q-Tail Docker Simulation",
        "email": email,
        "password": ACCEPTANCE_PASSWORD,
    }, expected=201, label="register")
    user_id = registered["user"]["id"]

    compliance_status, compliance_body = user.request("PUT", "/api/compliance", {
        "organization_legal_name": "Q-Tail Docker Simulation",
        "security_contact_email": email,
        "deployment_boundary": "customer_vpc",
        "data_residency": "Docker local simulation",
        "retention_days": 30,
        "deletion_sla_days": 7,
        "source_rights_confirmed": True,
        "derivative_rights_confirmed": True,
        "restricted_data_excluded": True,
        "subprocessor_reviewed": True,
        "terms_accepted": True,
        "privacy_acknowledged": True,
        "dpa_accepted": True,
    })
    expect(compliance_status, 200, compliance_body, "compliance submission")
    post(
        admin,
        f"/api/admin/compliance-profiles/{user_id}/approve",
        {"review_note": "Approved as Docker simulation only; not legal review or buyer DPA."},
        label="compliance approval",
    )

    generation_payload = {
        "robot_model": "Franka Panda (Docker simulation)",
        "control_frequency_hz": 20,
        "sensors": "RGB-D + joint state",
        "training_format": "RLDS + LeRobot v3",
        "production_backend": "Docker real Q-Tail allocation engine",
        "synthetic_budget": 100000,
        "filename": "docker_acceptance_tasks.csv",
        "csv_text": "task,count,success_rate,difficulty,group\nrare_pick,12,0.32,0.91,tail\nstandard_pick,540,0.86,0.22,head\n",
        "claim_acknowledged": True,
        "data_rights": {
            "source_type": "customer_owned",
            "license_basis": "Docker acceptance fixture owned by test buyer",
            "contains_personal_data": False,
            "retention_days": 30,
            "source_rights_confirmed": True,
            "derivative_rights_confirmed": True,
            "restricted_data_excluded": True,
        },
    }

    blocked_status, blocked_body = user.request("POST", "/api/generations", generation_payload)
    expect(blocked_status, 402, blocked_body, "Pro entitlement enforcement")

    application = post(user, "/api/api-access", {
        "role": "Docker acceptance operator",
        "use_case": "Verify the complete commercial workflow through Docker networking.",
        "data_format": "RLDS + LeRobot v3",
        "monthly_volume": "100,000 units",
        "pilot_goal": "Verify registration, payment, API, generation, Gates, and persistence.",
    }, expected=201, label="API application")["application"]
    post(admin, f"/api/admin/api-access/{application['id']}/approve", {
        "review_note": "Approved for Docker acceptance simulation.",
    }, label="API approval")

    early_key_status, early_key_body = user.request("POST", "/api/api-keys", {"label": "too early"})
    expect(early_key_status, 402, early_key_body, "API key Pro enforcement")

    order = post(user, "/api/payment-orders", {"channel": "wechat"}, expected=201, label="payment order")["order"]
    post(user, f"/api/payment-orders/{order['id']}/submit", {
        "payment_reference": f"DOCKER-SIM-{run_id}",
    }, label="payment submission")
    paid = post(admin, f"/api/admin/payment-orders/{order['id']}/confirm", {
        "review_note": "Simulated manual QR receipt confirmation for Docker acceptance.",
    }, label="payment confirmation")["order"]
    if paid["status"] != "paid":
        raise RuntimeError(f"payment was not activated: {paid}")

    invoice = post(user, f"/api/payment-orders/{order['id']}/invoice-requests", {
        "invoice_title": "Q-Tail Docker Simulation Buyer",
        "taxpayer_id": "91110108MA01234567",
        "invoice_email": email,
    }, expected=201, label="invoice request")["invoice_request"]
    issued_invoice = post(admin, f"/api/admin/invoice-requests/{invoice['id']}/issue", {
        "invoice_number": f"DOCKER-INVOICE-{run_id}",
        "review_note": "Docker simulation only; no tax invoice was actually issued.",
    }, label="simulated invoice issuance")["invoice_request"]
    if issued_invoice["status"] != "issued":
        raise RuntimeError(f"invoice request did not reach issued workflow state: {issued_invoice}")

    me = get(user, "/api/auth/me", label="Pro session")["user"]
    if not me.get("is_pro"):
        raise RuntimeError(f"Pro entitlement was not activated: {me}")

    key_response = post(user, "/api/api-keys", {"label": "Docker acceptance key"}, expected=201, label="API key")
    api_key = key_response["api_key"]
    api_client = Client(base_url, {"X-API-Key": api_key}, resolve_spec=resolve_spec)
    catalog_result = None
    trajectory_delivery_result = None
    if os.environ.get("QTAIL_CATALOG_EXPECT_AVAILABLE", "0") == "1":
        catalogs = get(api_client, "/api/catalogs", label="Pro synthetic catalog")["catalogs"]
        catalog = next((item for item in catalogs if item.get("slug") == CATALOG_SLUG), None)
        if not catalog or not catalog.get("available") or catalog.get("integrity_status") != "verified":
            raise RuntimeError(f"required synthetic catalog is unavailable: {catalog}")
        if catalog.get("buyer_gate_passed") is not False or catalog.get("evidence_scope") != "simulation":
            raise RuntimeError(f"synthetic catalog claim boundary is invalid: {catalog}")
        catalog_status, catalog_bytes, catalog_type = api_client.download(catalog["download_url"])
        catalog_sha256 = hashlib.sha256(catalog_bytes).hexdigest()
        if catalog_status != 200 or len(catalog_bytes) != CATALOG_BYTES or catalog_sha256 != CATALOG_SHA256:
            raise RuntimeError(
                f"synthetic catalog download failed integrity: HTTP {catalog_status}, type={catalog_type}, "
                f"bytes={len(catalog_bytes)}, sha256={catalog_sha256}"
            )
        catalog_result = {
            "slug": CATALOG_SLUG,
            "bytes": len(catalog_bytes),
            "sha256": catalog_sha256,
            "evidence_scope": catalog["evidence_scope"],
            "buyer_gate_passed": catalog["buyer_gate_passed"],
        }
        trajectory_payload = {
            **generation_payload,
            "delivery_product": "simulation_trajectory_batch",
            "trajectory_count": 8,
            "robot_model": "Sawyer / MetaWorld",
            "control_frequency_hz": 20,
            "sensors": "256x256 RGB + 39D state",
            "training_format": "RLDS",
            "production_backend": "MuJoCo / MetaWorld",
            "filename": "docker_metaworld_tasks.csv",
            "csv_text": "task,count\nreach-v3,50\nbutton-press-v3,7\npick-place-v3,7\n",
        }
        trajectory_queued = post(
            api_client,
            "/api/generations",
            trajectory_payload,
            expected=202,
            label="on-demand simulation trajectory queue",
        )
        trajectory_completed = wait_for_generation(api_client, trajectory_queued["job_id"])
        trajectory_status, trajectory_archive, trajectory_type = api_client.download(trajectory_completed["download_url"])
        if trajectory_status != 200 or not trajectory_archive.startswith(b"PK"):
            raise RuntimeError(f"trajectory delivery download failed: HTTP {trajectory_status}, type={trajectory_type}")
        with zipfile.ZipFile(io.BytesIO(trajectory_archive)) as archive:
            names = set(archive.namelist())
            required = {
                "package_manifest.json",
                "trajectory_selection.json",
                "qtail_allocation_plan.csv",
                "rlds/0.1.0/dataset_info.json",
                "rlds/0.1.0/features.json",
            }
            missing = sorted(required - names)
            tfrecord_names = sorted(name for name in names if "tfrecord" in name)
            if missing or len(tfrecord_names) != 1:
                raise RuntimeError(f"trajectory delivery files invalid: missing={missing}, tfrecords={tfrecord_names}")
            trajectory_manifest = json.loads(archive.read("package_manifest.json"))
            selected_rows = json.loads(archive.read("trajectory_selection.json"))
            if not archive.read(tfrecord_names[0]):
                raise RuntimeError("trajectory delivery TFRecord is empty")
        if (
            trajectory_manifest.get("package_type") != "qtail_simulation_trajectory_batch"
            or trajectory_manifest.get("trajectory_count") != 8
            or len(selected_rows) != 8
            or trajectory_manifest.get("source_catalog_sha256") != CATALOG_SHA256
            or trajectory_manifest.get("evidence_scope") != "simulation"
            or trajectory_manifest.get("buyer_gate_passed") is not False
            or trajectory_manifest.get("validation", {}).get("record_framing_preserved") is not True
        ):
            raise RuntimeError(f"trajectory delivery manifest boundary or integrity invalid: {trajectory_manifest}")
        trajectory_delivery_result = {
            "job_id": trajectory_completed["job_id"],
            "delivery_sha256": hashlib.sha256(trajectory_archive).hexdigest(),
            "trajectory_count": trajectory_manifest["trajectory_count"],
            "frame_count": trajectory_manifest["frame_count"],
            "source_catalog_sha256": trajectory_manifest["source_catalog_sha256"],
            "evidence_scope": trajectory_manifest["evidence_scope"],
            "buyer_gate_passed": trajectory_manifest["buyer_gate_passed"],
        }
    queued_jobs = []
    pending_jobs = []
    completed_jobs = []
    for index in range(3):
        queued_payload = dict(generation_payload)
        queued_payload["filename"] = f"docker_acceptance_tasks_{index + 1}.csv"
        queued_payload["csv_text"] = generation_payload["csv_text"].replace("rare_pick", f"rare_pick_{index + 1}")
        queued = post(api_client, "/api/generations", queued_payload, expected=202, label=f"durable async generator queue {index + 1}")
        if queued.get("status") not in {"queued", "running"}:
            raise RuntimeError(f"generation was not accepted by the durable queue: {queued}")
        queued_jobs.append(queued)
        pending_jobs.append(queued)
        if len(pending_jobs) >= max_inflight_jobs:
            completed_jobs.extend(wait_for_generation(api_client, item["job_id"]) for item in pending_jobs)
            pending_jobs = []
    completed_jobs.extend(wait_for_generation(api_client, item["job_id"]) for item in pending_jobs)
    generated = completed_jobs[0]
    job_id = generated["job_id"]

    download_status, archive_bytes, content_type = api_client.download(f"/downloads/{job_id}")
    if download_status != 200 or not archive_bytes.startswith(b"PK"):
        raise RuntimeError(f"delivery download failed: HTTP {download_status}, type={content_type}")
    async_delivery_hashes = {job_id: hashlib.sha256(archive_bytes).hexdigest()}
    if trajectory_delivery_result:
        async_delivery_hashes[trajectory_delivery_result["job_id"]] = trajectory_delivery_result["delivery_sha256"]
    for completed_job in completed_jobs[1:]:
        extra_status, extra_archive, extra_type = api_client.download(f"/downloads/{completed_job['job_id']}")
        if extra_status != 200 or not extra_archive.startswith(b"PK"):
            raise RuntimeError(f"queued delivery download failed: HTTP {extra_status}, type={extra_type}")
        async_delivery_hashes[completed_job["job_id"]] = hashlib.sha256(extra_archive).hexdigest()
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = set(archive.namelist())
        required_delivery_files = {
            "package_manifest.json",
            "qtail_data_engine_report.json",
            "qtail_service_model_card.json",
            "qtail_synthetic_data.csv",
            "qtail_service_synthetic_plan.csv",
            "README_QTAIL_DELIVERY.md",
        }
        missing_delivery_files = sorted(required_delivery_files - names)
        if missing_delivery_files:
            raise RuntimeError(f"delivery files missing from archive: {missing_delivery_files}")
        manifest = json.loads(archive.read("package_manifest.json"))
    if manifest.get("test_fixture") is True:
        raise RuntimeError("real-generator acceptance unexpectedly returned a test fixture")
    if manifest.get("package_type") != "qtail_data_engine_evaluation_package":
        raise RuntimeError(f"unexpected delivery package type: {manifest.get('package_type')!r}")
    if manifest.get("validation", {}).get("valid") is not True:
        raise RuntimeError(f"delivery package validation failed: {manifest.get('validation')}")

    deleted_job_id = completed_jobs[-1]["job_id"]
    deletion_request = post(
        user,
        f"/api/generations/{deleted_job_id}/deletion-request",
        {"reason": "Docker acceptance verifies payload deletion without removing audit metadata."},
        expected=201,
        label="buyer payload deletion request",
    )["deletion_request"]
    deletion_receipt = post(
        admin,
        f"/api/admin/data-deletion-requests/{deletion_request['id']}/complete",
        {"review_note": "Executed as Docker deletion simulation; file removal is real inside the test volume."},
        label="operator payload deletion completion",
    )["deletion_request"]
    if deletion_receipt.get("status") != "completed" or len(deletion_receipt.get("deletion_sha256") or "") != 64:
        raise RuntimeError(f"payload deletion did not produce an immutable receipt: {deletion_receipt}")
    deleted_status, _deleted_body, _deleted_type = api_client.download(f"/downloads/{deleted_job_id}")
    if deleted_status != 410:
        raise RuntimeError(f"deleted delivery remained downloadable: HTTP {deleted_status}")

    case = post(user, "/api/procurement-cases", {
        "generation_job_id": job_id,
        "title": f"Docker Gate simulation {run_id}",
        "buyer_owner": "Docker Simulation QA",
        "pilot_scope": "Software workflow validation only; no external buyer or real-robot claim.",
    }, expected=201, label="procurement case")["case"]
    case_id = case["id"]

    simulation_evidence_ids: dict[str, str] = {}
    for gate_number in (1, 2, 3):
        evidence = post(
            user,
            f"/api/procurement-cases/{case_id}/gates/{gate_number}/evidence",
            gate_payload(gate_number, run_id),
            expected=201,
            label=f"Gate {gate_number} evidence",
        )["evidence"]
        simulation_evidence_ids[str(gate_number)] = evidence["id"]
        post(
            admin,
            f"/api/admin/procurement-evidence/{evidence['id']}/approve",
            {"review_note": f"Approved as Docker simulation for Gate {gate_number}; not production evidence."},
            label=f"Gate {gate_number} approval",
        )

    blocked_status, blocked_body = admin.request("POST", f"/api/admin/procurement-cases/{case_id}/issue-contract", {})
    expect(blocked_status, 409, blocked_body, "simulation contract guard")
    if blocked_body.get("error", {}).get("code") != "external_evidence_required":
        raise RuntimeError(f"simulation evidence was not blocked from contract readiness: {blocked_body}")

    evidence_ids: dict[str, str] = {}
    for gate_number in (1, 2, 3):
        evidence = post(
            user,
            f"/api/procurement-cases/{case_id}/gates/{gate_number}/evidence",
            gate_payload(gate_number, run_id, "buyer_external"),
            expected=201,
            label=f"Gate {gate_number} buyer-external fixture evidence",
        )["evidence"]
        evidence_ids[str(gate_number)] = evidence["id"]
        approved = post(
            admin,
            f"/api/admin/procurement-evidence/{evidence['id']}/approve",
            {
                "review_note": f"Docker-only positive-path review for Gate {gate_number}; not real external verification.",
                "verification_reference": f"BUYER-EVIDENCE-FIXTURE-{run_id}-G{gate_number}",
                "reviewer_name": "Docker Procurement Fixture Reviewer",
            },
            label=f"Gate {gate_number} buyer-external fixture approval",
        )["evidence"]
        if not approved.get("contract_eligible"):
            raise RuntimeError(f"external fixture did not become contract eligible: {approved}")

    contract = post(
        admin,
        f"/api/admin/procurement-cases/{case_id}/issue-contract",
        {},
        expected=201,
        label="contract snapshot",
    )["contract"]
    draft_status, contract_draft, draft_content_type = user.download(f"/api/procurement-contracts/{contract['id']}/draft")
    if draft_status != 200 or b"SHA-256" not in contract_draft or "text/markdown" not in draft_content_type:
        raise RuntimeError(f"contract draft download failed: HTTP {draft_status}, type={draft_content_type}")
    provider_signature_sha256 = hashlib.sha256(f"{run_id}:provider-signature-proof-fixture".encode()).hexdigest()
    buyer_signature_sha256 = hashlib.sha256(f"{run_id}:buyer-signature-proof-fixture".encode()).hexdigest()
    signed = post(
        admin,
        f"/api/admin/procurement-contracts/{contract['id']}/mark-signed",
        {
            "contract_reference": f"DOCKER-SIMULATION-{run_id}",
            "executed_document_sha256": hashlib.sha256(f"{run_id}:executed-contract-fixture".encode()).hexdigest(),
            "provider_signatory": "Docker Provider Fixture",
            "provider_signature_sha256": provider_signature_sha256,
            "buyer_signatory": "Docker Buyer Fixture",
            "buyer_signature_sha256": buyer_signature_sha256,
            "effective_date": datetime.now(UTC).date().isoformat(),
        },
        label="simulated contract archival",
    )["contract"]
    if signed["status"] != "signed":
        raise RuntimeError(f"simulated contract did not reach signed workflow state: {signed}")
    if (
        signed.get("provider_signature_sha256") != provider_signature_sha256
        or signed.get("buyer_signature_sha256") != buyer_signature_sha256
        or not signed.get("execution_verified")
    ):
        raise RuntimeError(f"independent signature proofs were not preserved: {signed}")
    signed_draft_status, signed_contract_draft, signed_draft_content_type = user.download(f"/api/procurement-contracts/{contract['id']}/draft")
    if signed_draft_status != 200 or signed["contract_reference"].encode() not in signed_contract_draft or "text/markdown" not in signed_draft_content_type:
        raise RuntimeError(f"signed-state contract draft download failed: HTTP {signed_draft_status}, type={signed_draft_content_type}")
    contract_draft_sha256 = hashlib.sha256(signed_contract_draft).hexdigest()

    cases = get(user, "/api/procurement-cases", label="final procurement state")["cases"]
    final_case = next(item for item in cases if item["id"] == case_id)
    if final_case["status"] != "contracted":
        raise RuntimeError(f"procurement workflow did not reach contracted: {final_case}")

    refund = post(user, f"/api/payment-orders/{order['id']}/refund-requests", {
        "reason": "Docker acceptance verifies the refund review path without moving real funds.",
    }, expected=201, label="refund request")["refund_request"]
    post(admin, f"/api/admin/refund-requests/{refund['id']}/reject", {
        "review_note": "Rejected as Docker simulation; no real refund was requested or settled.",
    }, label="simulated refund rejection")

    report = {
        "status": "passed",
        "simulation_only": True,
        "claim_boundary": "This record proves Docker software behavior only. It is not real-robot, buyer, payment-settlement, or executed-contract evidence.",
        "run_id": run_id,
        "completed_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "connection_resolution": resolve_spec,
        "max_inflight_jobs": max_inflight_jobs,
        "database": health["database"],
        "real_generator_fixture": manifest.get("test_fixture", False),
        "user_id": user_id,
        "email": email,
        "application_id": application["id"],
        "payment_order_id": order["id"],
        "invoice_request_id": invoice["id"],
        "refund_request_id": refund["id"],
        "api_key_id": key_response["key"]["id"],
        "synthetic_catalog": catalog_result,
        "on_demand_trajectory_delivery": trajectory_delivery_result,
        "job_id": job_id,
        "async_job_ids": [item["job_id"] for item in completed_jobs],
        "async_delivery_sha256": async_delivery_hashes,
        "deleted_job_id": deleted_job_id,
        "deletion_request_id": deletion_request["id"],
        "deletion_receipt_sha256": deletion_receipt["deletion_sha256"],
        "delivery_sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "delivery_manifest_package_type": manifest.get("package_type"),
        "delivery_manifest_validation": manifest.get("validation", {}).get("valid"),
        "procurement_case_id": case_id,
        "evidence_ids": evidence_ids,
        "simulation_evidence_ids": simulation_evidence_ids,
        "simulation_contract_blocked": True,
        "contract_id": contract["id"],
        "contract_draft_sha256": contract_draft_sha256,
        "contract_reference": signed["contract_reference"],
        "provider_signature_sha256": signed.get("provider_signature_sha256"),
        "buyer_signature_sha256": signed.get("buyer_signature_sha256"),
        "execution_attestation_sha256": signed.get("execution_attestation_sha256"),
        "checks": [
            "nginx_to_api_to_mysql",
            "registration_and_session",
            "pro_entitlement_enforcement",
            "manual_qr_order_workflow",
            "invoice_issue_and_refund_review_workflow",
            "api_application_and_approval",
            "one_time_api_key_and_api_auth",
            *( ["pro_catalog_download_and_sha256"] if catalog_result else [] ),
            *( ["qtail_weighted_on_demand_tfrecord_delivery"] if trajectory_delivery_result else [] ),
            "mysql_durable_async_queue_and_worker",
            "real_qtail_generation_and_zip_download",
            "versioned_data_rights_and_compliance_approval",
            "buyer_deletion_request_and_payload_tombstone",
            "sequential_gate_review",
            "simulation_evidence_contract_guard_and_external_attestation",
            "contract_snapshot_workflow",
            "buyer_contract_draft_download",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def verify_persistence(base_url: str, report_path: Path, resolve_spec: str | None = None) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    client = Client(base_url, resolve_spec=resolve_spec)
    logged_in = post(client, "/api/auth/login", {
        "email": report["email"],
        "password": ACCEPTANCE_PASSWORD,
    }, label="post-restart login")
    if logged_in["user"]["id"] != report["user_id"] or not logged_in["user"]["is_pro"]:
        raise RuntimeError(f"persisted user or Pro entitlement mismatch: {logged_in}")
    jobs = get(client, "/api/generations", label="post-restart jobs")["jobs"]
    persisted_job_ids = {job["id"] for job in jobs}
    expected_job_ids = set(report.get("async_job_ids") or [report["job_id"]])
    if report.get("on_demand_trajectory_delivery"):
        expected_job_ids.add(report["on_demand_trajectory_delivery"]["job_id"])
    if not expected_job_ids.issubset(persisted_job_ids):
        raise RuntimeError(f"generated jobs were not persisted across restart: {expected_job_ids - persisted_job_ids}")
    cases = get(client, "/api/procurement-cases", label="post-restart procurement cases")["cases"]
    persisted_case = next((item for item in cases if item["id"] == report["procurement_case_id"]), None)
    if not persisted_case or persisted_case["status"] != "contracted":
        raise RuntimeError(f"procurement state was not persisted: {persisted_case}")
    persisted_contract = persisted_case.get("contract", {})
    if (
        not persisted_contract.get("execution_verified")
        or persisted_contract.get("provider_signature_sha256") != report.get("provider_signature_sha256")
        or persisted_contract.get("buyer_signature_sha256") != report.get("buyer_signature_sha256")
        or persisted_contract.get("execution_attestation_sha256") != report.get("execution_attestation_sha256")
    ):
        raise RuntimeError(f"executed-contract attestation was not persisted: {persisted_case.get('contract')}")
    billing = get(client, "/api/billing", label="post-restart billing state")
    persisted_invoice = next((item for item in billing.get("invoice_requests", []) if item["id"] == report.get("invoice_request_id")), None)
    persisted_refund = next((item for item in billing.get("refund_requests", []) if item["id"] == report.get("refund_request_id")), None)
    if not persisted_invoice or persisted_invoice["status"] != "issued":
        raise RuntimeError(f"invoice workflow was not persisted: {persisted_invoice}")
    if not persisted_refund or persisted_refund["status"] != "rejected":
        raise RuntimeError(f"refund workflow was not persisted: {persisted_refund}")
    expected_delivery_hashes = report.get("async_delivery_sha256") or {report["job_id"]: report["delivery_sha256"]}
    deleted_job_id = report.get("deleted_job_id")
    for persisted_job_id, expected_sha256 in expected_delivery_hashes.items():
        status, archive_bytes, _ = client.download(f"/downloads/{persisted_job_id}")
        if persisted_job_id == deleted_job_id:
            if status != 410:
                raise RuntimeError(f"deleted package became available after restart: {persisted_job_id}, HTTP {status}")
            persisted_job = next(item for item in jobs if item["id"] == persisted_job_id)
            if not persisted_job.get("payload_deleted") or (persisted_job.get("deletion_request") or {}).get("deletion_sha256") != report.get("deletion_receipt_sha256"):
                raise RuntimeError(f"deletion tombstone did not persist: {persisted_job}")
            continue
        if status != 200 or hashlib.sha256(archive_bytes).hexdigest() != expected_sha256:
            raise RuntimeError(f"delivery package was not persisted byte-for-byte across restart: {persisted_job_id}")
    expected_catalog = report.get("synthetic_catalog")
    if expected_catalog:
        catalogs = get(client, "/api/catalogs", label="post-restart synthetic catalog")["catalogs"]
        catalog = next((item for item in catalogs if item.get("slug") == expected_catalog["slug"]), None)
        if not catalog or not catalog.get("available"):
            raise RuntimeError(f"synthetic catalog was unavailable after restart: {catalog}")
        catalog_status, catalog_bytes, _ = client.download(catalog["download_url"])
        if catalog_status != 200 or len(catalog_bytes) != expected_catalog["bytes"] or hashlib.sha256(catalog_bytes).hexdigest() != expected_catalog["sha256"]:
            raise RuntimeError("synthetic catalog did not persist byte-for-byte across restart")
    draft_status, contract_draft, _ = client.download(f"/api/procurement-contracts/{report['contract_id']}/draft")
    if draft_status != 200 or hashlib.sha256(contract_draft).hexdigest() != report.get("contract_draft_sha256"):
        raise RuntimeError("contract draft was not reproduced byte-for-byte across restart")
    result = {
        "status": "passed",
        "verified_at": datetime.now(UTC).isoformat(),
        "user_id": report["user_id"],
        "job_id": report["job_id"],
        "procurement_case_id": report["procurement_case_id"],
        "invoice_request_id": report["invoice_request_id"],
        "refund_request_id": report["refund_request_id"],
        "delivery_sha256": report["delivery_sha256"],
        "contract_draft_sha256": report["contract_draft_sha256"],
        "deletion_receipt_sha256": report.get("deletion_receipt_sha256"),
        "provider_signature_sha256": report.get("provider_signature_sha256"),
        "buyer_signature_sha256": report.get("buyer_signature_sha256"),
        "execution_attestation_sha256": report.get("execution_attestation_sha256"),
    }
    report["persistence"] = result
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Q-Tail Docker end-to-end acceptance workflow.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument(
        "--resolve",
        default=os.environ.get("QTAIL_ACCEPTANCE_RESOLVE"),
        help="Connect an HTTPS base URL through HOST:PORT:ADDRESS while preserving TLS validation and Secure cookies.",
    )
    parser.add_argument(
        "--max-inflight-jobs",
        type=int,
        default=int(os.environ.get("QTAIL_ACCEPTANCE_MAX_INFLIGHT_JOBS", "3")),
        help="Submit generation jobs in batches of this size (1-3) to respect production queue limits.",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--verify-persistence", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify_persistence:
            result = verify_persistence(args.base_url, args.report, args.resolve)
        else:
            admin_token = os.environ.get("ADMIN_TOKEN", "")
            if not admin_token:
                raise RuntimeError("ADMIN_TOKEN is required")
            result = run_acceptance(
                args.base_url,
                admin_token,
                args.report,
                args.resolve,
                args.max_inflight_jobs,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
