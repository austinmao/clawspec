from __future__ import annotations

import time
from typing import Any

from .common import elapsed, outcome
from .gateway_logs import parse_sessions, parse_tool_calls


def delegation_occurred(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    entries = parse_tool_calls(assertion["log_path"], run_id=assertion["run_id"])
    matching = [
        entry
        for entry in entries
        if entry["tool"] == "sessions_spawn" and entry.get("target_agent") == assertion["to_agent"]
    ]
    if not matching:
        return outcome(
            "delegation_occurred",
            "FAIL",
            "No matching sessions_spawn call found",
            elapsed=elapsed(start),
        )

    child_run_id = matching[0].get("child_run_id")
    if not child_run_id:
        return outcome(
            "delegation_occurred",
            "FAIL",
            "Delegation log entry missing child run id",
            elapsed=elapsed(start),
        )

    sessions = parse_sessions(assertion["log_path"], run_id=child_run_id)
    if not any(entry["agent"] == assertion["to_agent"] for entry in sessions):
        return outcome(
            "delegation_occurred",
            "FAIL",
            "Child session for delegated agent not found",
            elapsed=elapsed(start),
        )

    return outcome("delegation_occurred", "PASS", None, elapsed=elapsed(start))


HANDLERS = {"delegation_occurred": delegation_occurred}
