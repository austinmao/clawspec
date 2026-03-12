from __future__ import annotations

import time
from typing import Any

import httpx

from .common import elapsed, outcome


def gateway_response(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    endpoint = assertion["endpoint"]
    expected_status = assertion["expected_status"]
    expected_body = assertion.get("expected_body")
    try:
        response = httpx.get(endpoint, timeout=5.0)
    except httpx.HTTPError as exc:
        return outcome("gateway_response", "FAIL", str(exc), elapsed=elapsed(start))

    if response.status_code != expected_status:
        return outcome(
            "gateway_response",
            "FAIL",
            f"Expected {expected_status}, got {response.status_code}",
            elapsed=elapsed(start),
        )
    if expected_body and expected_body not in response.text:
        return outcome(
            "gateway_response",
            "FAIL",
            f"Expected body fragment not found: {expected_body}",
            elapsed=elapsed(start),
        )
    return outcome("gateway_response", "PASS", None, elapsed=elapsed(start))


HANDLERS = {"gateway_response": gateway_response}
