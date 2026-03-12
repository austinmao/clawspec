from __future__ import annotations

import time
from typing import Any

from .common import elapsed, outcome
from .gateway_logs import parse_token_usage


def token_budget(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    usage = parse_token_usage(assertion["log_path"], run_id=assertion["run_id"])
    if usage is None:
        return outcome(
            "token_budget", "SKIP", "Token usage unavailable in gateway log", elapsed=elapsed(start)
        )

    limits = {
        "input": assertion.get("max_input_tokens"),
        "output": assertion.get("max_output_tokens"),
        "total": assertion.get("max_total_tokens"),
    }
    for key, limit in limits.items():
        if limit is not None and usage[key] > int(limit):
            return outcome(
                "token_budget",
                "FAIL",
                f"{key} tokens {usage[key]} exceeded budget {limit}",
                elapsed=elapsed(start),
            )

    return outcome("token_budget", "PASS", None, elapsed=elapsed(start))


HANDLERS = {"token_budget": token_budget}
