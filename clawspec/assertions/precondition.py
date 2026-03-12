from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import httpx

from .common import elapsed, outcome


def file_present(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    path = Path(assertion["path"])
    status = "PASS" if path.exists() else "FAIL"
    detail = None if path.exists() else f"File not found: {path}"
    return outcome("file_present", status, detail, elapsed=elapsed(start))


def file_absent(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    path = Path(assertion["path"])
    status = "PASS" if not path.exists() else "FAIL"
    detail = None if not path.exists() else f"File exists: {path}"
    return outcome("file_absent", status, detail, elapsed=elapsed(start))


def gateway_healthy(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    endpoint = assertion.get("endpoint", "http://localhost:18789/health")
    try:
        response = httpx.get(endpoint, timeout=5.0)
    except httpx.HTTPError as exc:
        return outcome("gateway_healthy", "FAIL", str(exc), elapsed=elapsed(start))
    status = "PASS" if response.status_code == 200 else "FAIL"
    detail = None if status == "PASS" else f"Gateway returned {response.status_code}"
    return outcome("gateway_healthy", status, detail, elapsed=elapsed(start))


def env_present(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    required = assertion.get("vars", [])
    missing = [name for name in required if name not in os.environ]
    status = "PASS" if not missing else "FAIL"
    detail = None if not missing else f"Missing env vars: {', '.join(missing)}"
    return outcome("env_present", status, detail, elapsed=elapsed(start))


HANDLERS = {
    "file_present": file_present,
    "file_absent": file_absent,
    "gateway_healthy": gateway_healthy,
    "env_present": env_present,
}
