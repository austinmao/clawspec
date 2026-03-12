from __future__ import annotations

import time
from typing import Any

from .common import elapsed, outcome
from .gateway_logs import parse_tool_calls


def tool_not_permitted(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    allowed_tools = set(assertion.get("allowed_tools", []))
    entries = parse_tool_calls(assertion["log_path"], run_id=assertion["run_id"])
    disallowed = sorted({entry["tool"] for entry in entries if entry["tool"] not in allowed_tools})
    if disallowed:
        return outcome(
            "tool_not_permitted",
            "FAIL",
            f"Disallowed tools used: {', '.join(disallowed)}",
            elapsed=elapsed(start),
        )
    return outcome("tool_not_permitted", "PASS", None, elapsed=elapsed(start))


HANDLERS = {"tool_not_permitted": tool_not_permitted}
