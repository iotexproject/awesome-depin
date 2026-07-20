#!/usr/bin/env python3
"""Destructive local fault injection for the durable generation Worker.

This script intentionally stops and kills the Worker. It refuses a project name
containing "production" and requires an explicit simulation flag.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


class Client:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.loads(error.read().decode())
            except Exception:
                return error.code, {"error": str(error)}


def wait_for(client: Client, job_id: str, expected: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        status, last = client.request("GET", f"/api/generations/{job_id}")
        if status != 200:
            raise RuntimeError(f"status read failed: HTTP {status}: {last}")
        if last.get("status") == expected:
            return last
        if last.get("status") == "failed":
            raise RuntimeError(f"job failed during crash drill: {last}")
        time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {expected}: {last}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Kill a local Q-Tail Worker mid-job and verify lease recovery.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--env-file", type=Path, default=Path(".env.acceptance"))
    parser.add_argument("--project", default="qtail-acceptance")
    parser.add_argument("--overlay", action="append", default=["docker-compose.production.yml"])
    parser.add_argument("--email", required=True)
    parser.add_argument("--report", type=Path, default=Path("var/acceptance/worker-crash-latest.json"))
    parser.add_argument("--allow-destructive-simulation", action="store_true")
    args = parser.parse_args()
    password = os.environ.get("CRASH_DRILL_PASSWORD", "")
    if not args.allow_destructive_simulation:
        raise SystemExit("--allow-destructive-simulation is required")
    if "production" in args.project.lower():
        raise SystemExit("refusing to fault-inject a production-named Compose project")
    if not password:
        raise SystemExit("CRASH_DRILL_PASSWORD is required")
    root = Path(__file__).resolve().parents[1]
    env_file = args.env_file.resolve()
    compose = ["docker", "compose", "-p", args.project, "--env-file", str(env_file), "-f", str(root / "docker-compose.yml")]
    for overlay in args.overlay:
        compose.extend(["-f", str((root / overlay).resolve())])

    def run_compose(*extra: str, env: dict | None = None, capture: bool = False) -> str:
        completed = subprocess.run(
            [*compose, *extra], check=True, text=True,
            stdout=subprocess.PIPE if capture else None,
            env=env,
        )
        return completed.stdout.strip() if capture else ""

    client = Client(args.base_url)
    status, login = client.request("POST", "/api/auth/login", {"email": args.email, "password": password})
    if status != 200 or not login.get("user", {}).get("is_pro"):
        raise SystemExit(f"crash-drill user login/Pro check failed: HTTP {status}")

    job_id = None
    try:
        run_compose("stop", "worker")
        status, queued = client.request("POST", "/api/generations", {
            "robot_model": "Franka Panda (worker crash drill)",
            "control_frequency_hz": 20,
            "sensors": "RGB-D + joint state",
            "training_format": "RLDS + LeRobot v3",
            "production_backend": "Docker lease-recovery drill",
            "synthetic_budget": 100000,
            "filename": "worker_crash_drill.csv",
            "csv_text": "task,count,success_rate,difficulty,group\ncrash_recovery_tail,9,0.25,0.95,tail\nstandard,400,0.85,0.2,head\n",
            "claim_acknowledged": True,
        })
        if status != 202 or queued.get("status") != "queued":
            raise RuntimeError(f"job was not queued: HTTP {status}: {queued}")
        job_id = queued["job_id"]

        delayed_env = os.environ.copy()
        delayed_env.update({
            "QTAIL_WORKER_TEST_DELAY_SECONDS": "20",
            "QTAIL_WORKER_HEARTBEAT_SECONDS": "1",
            "QTAIL_WORKER_LEASE_SECONDS": "5",
        })
        run_compose("up", "-d", "--force-recreate", "worker", env=delayed_env)
        running = wait_for(client, job_id, "running", 30)
        if int(running.get("attempt_count") or 0) != 1:
            raise RuntimeError(f"first lease did not use attempt 1: {running}")
        container_id = run_compose("ps", "-q", "worker", capture=True)
        if not container_id:
            raise RuntimeError("worker container id is unavailable")
        subprocess.run(["docker", "kill", container_id], check=True, stdout=subprocess.DEVNULL)
        time.sleep(7)
        run_compose("up", "-d", "--force-recreate", "worker")
        completed = wait_for(client, job_id, "completed", 120)
        if int(completed.get("attempt_count") or 0) != 2:
            raise RuntimeError(f"recovered job did not complete on attempt 2: {completed}")

        sql = f"SELECT COUNT(*) FROM audit_events WHERE object_id='{job_id}' AND event_type='generation.requeued';"
        audit_count = run_compose(
            "exec", "-T", "db", "sh", "-lc",
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -N -uroot "$MYSQL_DATABASE" -e "$1"',
            "sh", sql, capture=True,
        )
        if audit_count != "1":
            raise RuntimeError(f"expected one requeue audit event, got {audit_count!r}")
        report = {
            "status": "passed",
            "simulation_only": True,
            "completed_at": datetime.now(UTC).isoformat(),
            "compose_project": args.project,
            "job_id": job_id,
            "attempt_count": 2,
            "requeue_audit_events": 1,
            "download_url": completed.get("download_url"),
            "claim_boundary": "Local Docker Worker fault injection only; not production uptime or buyer evidence.",
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        try:
            run_compose("up", "-d", "--force-recreate", "worker")
        except Exception as error:
            print(f"WARNING: failed to restore default worker: {error}", file=os.sys.stderr)


if __name__ == "__main__":
    main()
