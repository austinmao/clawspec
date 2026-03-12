from __future__ import annotations

import re
import time
from typing import Any

from .common import elapsed, load_structured, load_text, outcome


def log_entry(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    path, text = load_text(assertion["path"])
    if path is None or text is None:
        return outcome(
            "log_entry", "FAIL", f"Log file not found: {assertion['path']}", elapsed=elapsed(start)
        )

    found = re.search(assertion["pattern"], text) is not None
    wants_absent = bool(assertion.get("absent"))
    if wants_absent and not found:
        return outcome("log_entry", "PASS", None, elapsed=elapsed(start))
    if not wants_absent and found:
        return outcome("log_entry", "PASS", None, elapsed=elapsed(start))
    detail = "Pattern was present" if wants_absent else "Pattern not found"
    return outcome("log_entry", "FAIL", detail, elapsed=elapsed(start))


def decision_routed_to(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    _, payload = load_structured(assertion["state_path"])
    if payload is None:
        return outcome(
            "decision_routed_to",
            "FAIL",
            f"State file not found: {assertion['state_path']}",
            elapsed=elapsed(start),
        )

    actual = payload.get("selected_agent") or payload.get("agent")
    expected = assertion["expected_agent"]
    status = "PASS" if actual == expected else "FAIL"
    detail = None if status == "PASS" else f"Expected {expected}, got {actual}"
    return outcome("decision_routed_to", status, detail, elapsed=elapsed(start))


HANDLERS = {
    "log_entry": log_entry,
    "decision_routed_to": decision_routed_to,
}
