#!/usr/bin/env python3
"""Watch the Strong Open X downloader and recover only when it is stale."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "results" / "openx_strong_download" / "download.log"
OUT_PATH = ROOT / "results" / "openx_strong_download" / "download_watchdog_status.json"
HISTORY_PATH = ROOT / "results" / "openx_strong_download" / "download_watchdog_history.json"
DATA_DIR = ROOT / "data" / "openx_demo"
LABEL = "qtail-openx-strong-addon"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)


def load_previous_status() -> dict:
    if not OUT_PATH.exists():
        return {}
    try:
        return json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        return None


def du_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def log_age_seconds() -> float | None:
    if not LOG_PATH.exists():
        return None
    return max(0.0, datetime.now(timezone.utc).timestamp() - LOG_PATH.stat().st_mtime)


def launchd_label_present(label: str) -> bool:
    proc = run(["launchctl", "list"])
    return any(line.endswith(label) for line in proc.stdout.splitlines())


def active_gsutil_processes() -> list[dict]:
    proc = run(["ps", "aux"])
    rows = []
    for line in proc.stdout.splitlines():
        if (
            "gsutil" in line
            and "gdm-robotics-open-x-embodiment" in line
            and "data/openx_demo" in line
        ):
            parts = line.split(None, 10)
            rows.append({
                "pid": parts[1] if len(parts) > 1 else None,
                "cpu_pct": parts[2] if len(parts) > 2 else None,
                "mem_pct": parts[3] if len(parts) > 3 else None,
                "started": parts[8] if len(parts) > 8 else None,
                "command": parts[10] if len(parts) > 10 else line,
            })
    return rows


def restart_downloader() -> dict:
    uid = run(["id", "-u"]).stdout.strip()
    target = f"gui/{uid}/{LABEL}"
    proc = run(["launchctl", "kickstart", "-k", target])
    return {
        "command": ["launchctl", "kickstart", "-k", target],
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def append_history(payload: dict, limit: int = 192) -> None:
    history = {"rows": []}
    if HISTORY_PATH.exists():
        try:
            history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            history = {"rows": []}
    if not isinstance(history.get("rows"), list):
        history["rows"] = []
    row = {
        "generated_at": payload.get("generated_at"),
        "action": payload.get("action"),
        "log_fresh": payload.get("log_fresh"),
        "log_age_seconds": payload.get("log_age_seconds"),
        "data_bytes": payload.get("data_bytes"),
        "data_growth_bytes_since_last_check": payload.get("data_growth_bytes_since_last_check"),
        "data_unchanged_since": payload.get("data_unchanged_since"),
        "no_data_growth_seconds": payload.get("no_data_growth_seconds"),
        "active_gsutil_process_count": payload.get("active_gsutil_process_count"),
        "reasons": payload.get("reasons") or [],
        "restart_returncode": (payload.get("restart_result") or {}).get("returncode"),
    }
    history["rows"].append(row)
    history["rows"] = history["rows"][-limit:]
    history["generated_at"] = payload.get("generated_at")
    history["row_count"] = len(history["rows"])
    HISTORY_PATH.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def check(*, stale_after_seconds: int, dry_run: bool) -> dict:
    generated_dt = datetime.now(timezone.utc)
    generated_at = generated_dt.isoformat()
    previous = load_previous_status()
    age = log_age_seconds()
    processes = active_gsutil_processes()
    label_present = launchd_label_present(LABEL)
    data_bytes = du_bytes(DATA_DIR)
    previous_data_bytes = previous.get("data_bytes")
    previous_generated_at = parse_time(previous.get("generated_at"))
    previous_unchanged_since = parse_time(previous.get("data_unchanged_since"))
    data_unchanged_since = None
    if previous_data_bytes == data_bytes:
        data_unchanged_since = previous_unchanged_since or previous_generated_at or datetime.now(timezone.utc)
    no_data_growth_seconds = 0.0
    if data_unchanged_since:
        no_data_growth_seconds = max(0.0, datetime.now(timezone.utc).timestamp() - data_unchanged_since.timestamp())
    reasons = []
    if age is None:
        reasons.append("download_log_missing")
    elif age > stale_after_seconds:
        reasons.append("download_log_stale")
    if not processes:
        reasons.append("no_active_gsutil_process")
    if not label_present:
        reasons.append("launchd_label_absent")
    if previous_data_bytes == data_bytes and no_data_growth_seconds >= stale_after_seconds:
        reasons.append("no_data_growth")

    should_restart = bool(
        "download_log_missing" in reasons
        or "download_log_stale" in reasons
        or "no_active_gsutil_process" in reasons
        or "no_data_growth" in reasons
    )
    action = "watching"
    restart_result = None
    pre_restart_no_data_growth_seconds = None
    if should_restart:
        action = "would_restart" if dry_run else "restart_requested"
        if not dry_run:
            restart_result = restart_downloader()
            if restart_result.get("returncode") == 0:
                pre_restart_no_data_growth_seconds = no_data_growth_seconds
                data_unchanged_since = generated_dt
                no_data_growth_seconds = 0.0

    payload = {
        "generated_at": generated_at,
        "label": LABEL,
        "stale_after_seconds": stale_after_seconds,
        "dry_run": dry_run,
        "log_path": str(LOG_PATH),
        "log_age_seconds": age,
        "log_fresh": age is not None and age <= stale_after_seconds,
        "data_dir": str(DATA_DIR),
        "data_bytes": data_bytes,
        "previous_data_bytes": previous_data_bytes,
        "data_growth_bytes_since_last_check": None
        if previous_data_bytes is None
        else data_bytes - int(previous_data_bytes),
        "data_unchanged_since": data_unchanged_since.isoformat() if data_unchanged_since else None,
        "no_data_growth_seconds": no_data_growth_seconds,
        "pre_restart_no_data_growth_seconds": pre_restart_no_data_growth_seconds,
        "launchd_label_present": label_present,
        "active_gsutil_process_count": len(processes),
        "active_gsutil_processes": processes[:8],
        "reasons": reasons,
        "action": action,
        "restart_result": restart_result,
        "policy": "Restart the Strong downloader only when the log is stale, missing, no gsutil process is alive, or downloaded bytes stop growing for the stale window.",
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    append_history(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Recover the Strong Open X downloader when stale.")
    parser.add_argument("--stale-after-seconds", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(check(stale_after_seconds=args.stale_after_seconds, dry_run=args.dry_run), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
