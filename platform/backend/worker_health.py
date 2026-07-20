from __future__ import annotations

import os
import sys
import time
from pathlib import Path


path = Path(os.environ.get("QTAIL_WORKER_HEALTH_FILE", "/tmp/qtail-worker-heartbeat"))
max_age = max(15, int(os.environ.get("QTAIL_WORKER_HEALTH_MAX_AGE_SECONDS", "90")))
if not path.is_file():
    raise SystemExit("worker heartbeat file is missing")
age = time.time() - path.stat().st_mtime
if age > max_age:
    raise SystemExit(f"worker heartbeat is stale: {age:.1f}s")
sys.stdout.write("ok\n")
