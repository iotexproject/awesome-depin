#!/usr/bin/env python3
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import zipfile


PLATFORM_DIR = Path(__file__).resolve().parents[1]
KIT_DIR = PLATFORM_DIR / "public" / "buyer-kit"
TEMPLATE_DIR = KIT_DIR / "templates"
VERSION = "1.2.0"
ARCHIVE_NAME = f"qtail-buyer-pilot-kit-v{VERSION}.zip"
ARCHIVE_ROOT = f"qtail-buyer-pilot-kit-v{VERSION}"
MANIFEST_PATH = KIT_DIR / "manifest.json"
ARCHIVE_PATH = KIT_DIR / ARCHIVE_NAME
SIDECAR_PATH = KIT_DIR / f"{ARCHIVE_NAME}.sha256"
FIXED_ZIP_TIME = (2026, 7, 20, 0, 0, 0)

REQUIRED_TEMPLATES = {
    "README.md",
    "pilot-sow-template.md",
    "gate1-dataset-manifest.json",
    "gate1-evidence.json",
    "gate2-evidence.json",
    "gate2-evaluation-ledger.csv",
    "gate3-evidence.json",
    "gate3-real-robot-trials.csv",
    "gate3-commercial-cost-ledger.csv",
    "buyer-signoff-template.md",
    "contract-execution-checklist.md",
}
REQUIRED_TOOLS = {"validate_gate1_delivery.py"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def zip_entry(name: str, data: bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info, data


def main() -> None:
    templates = {path.name: path for path in TEMPLATE_DIR.iterdir() if path.is_file()}
    missing = sorted(REQUIRED_TEMPLATES - templates.keys())
    unexpected = sorted(templates.keys() - REQUIRED_TEMPLATES)
    if missing or unexpected:
        raise SystemExit(f"buyer kit template mismatch: missing={missing}, unexpected={unexpected}")
    tool_dir = KIT_DIR / "tools"
    tools = {path.name: path for path in tool_dir.iterdir() if path.is_file()}
    missing_tools = sorted(REQUIRED_TOOLS - tools.keys())
    unexpected_tools = sorted(tools.keys() - REQUIRED_TOOLS)
    if missing_tools or unexpected_tools:
        raise SystemExit(f"buyer kit tool mismatch: missing={missing_tools}, unexpected={unexpected_tools}")

    file_records = []
    payloads: dict[str, bytes] = {}
    for name in sorted(REQUIRED_TEMPLATES):
        relative = f"templates/{name}"
        data = templates[name].read_bytes()
        payloads[relative] = data
        file_records.append({"path": relative, "bytes": len(data), "sha256": sha256(data)})
    for name in sorted(REQUIRED_TOOLS):
        relative = f"tools/{name}"
        data = tools[name].read_bytes()
        payloads[relative] = data
        file_records.append({"path": relative, "bytes": len(data), "sha256": sha256(data)})

    manifest = {
        "package": "qtail_buyer_procurement_pilot_kit",
        "version": VERSION,
        "generated_at": datetime(2026, 7, 20, tzinfo=UTC).isoformat(),
        "template_count": len(REQUIRED_TEMPLATES),
        "tool_count": len(REQUIRED_TOOLS),
        "gate_thresholds": {
            "gate1": "trajectory_count > 0; schema and playback pass; manifest hash and production log present",
            "gate2": "same policy and budget; Tail SR >= +5 pp; CI95 lower > 0; overall >= -1 pp; head >= -2 pp",
            "gate3": "3-5 tasks; simulation >= 100/condition; real robot >= 30/task; unit cost reduction >= 20%; safety and buyer owners",
        },
        "files": file_records,
        "contract_eligibility": False,
        "claim_boundary": "Blank buyer working papers only; no buyer data, external acceptance, real-robot result, invoice, legal approval, signature, or executed contract.",
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    MANIFEST_PATH.write_bytes(manifest_bytes)

    with zipfile.ZipFile(ARCHIVE_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, data in sorted({"manifest.json": manifest_bytes, **payloads}.items()):
            info, payload = zip_entry(f"{ARCHIVE_ROOT}/{relative}", data)
            archive.writestr(info, payload, compresslevel=9)

    archive_sha = sha256(ARCHIVE_PATH.read_bytes())
    SIDECAR_PATH.write_text(f"{archive_sha}  {ARCHIVE_NAME}\n", encoding="utf-8")
    print(json.dumps({
        "status": "built",
        "archive": str(ARCHIVE_PATH),
        "bytes": ARCHIVE_PATH.stat().st_size,
        "sha256": archive_sha,
        "files": len(payloads) + 1,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
