from __future__ import annotations

import time
from typing import Any

from .common import elapsed, outcome
from .gateway_logs import parse_tool_calls


def tool_was_called(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    entries = parse_tool_calls(assertion["log_path"], run_id=assertion["run_id"])
    found = any(entry["tool"] == assertion["tool"] for entry in entries)
    status = "PASS" if found else "FAIL"
    detail = None if found else f"Tool not called: {assertion['tool']}"
    return outcome("tool_was_called", status, detail, elapsed=elapsed(start))


def tool_not_called(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    entries = parse_tool_calls(assertion["log_path"], run_id=assertion["run_id"])
    found = any(entry["tool"] == assertion["tool"] for entry in entries)
    status = "FAIL" if found else "PASS"
    detail = f"Tool was called: {assertion['tool']}" if found else None
    return outcome("tool_not_called", status, detail, elapsed=elapsed(start))


HANDLERS = {
    "tool_was_called": tool_was_called,
    "tool_not_called": tool_not_called,
}
