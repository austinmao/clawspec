from __future__ import annotations

import statistics
import time
from typing import Any

import httpx

from .common import elapsed, load_text, outcome


def agent_identity_consistent(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    _, output_text = load_text(assertion["output_path"])
    _, soul_text = load_text(assertion["soul_path"])
    if output_text is None or soul_text is None:
        return outcome(
            "agent_identity_consistent",
            "FAIL",
            "Missing output or SOUL file",
            elapsed=elapsed(start),
        )

    threshold = float(assertion.get("pass_threshold", 3))
    try:
        response = httpx.post(
            assertion.get("endpoint", "http://localhost:18789/qa/judge"),
            json={
                "rubric": assertion.get("rubric", "Score 1-5 for identity fidelity."),
                "output": output_text,
                "identity": soul_text,
            },
            timeout=30.0,
        )
        payload = response.json()
        score = float(payload["score"])
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        return outcome("agent_identity_consistent", "SKIP", str(exc), elapsed=elapsed(start))

    status = "PASS" if score >= threshold else "WARN"
    detail = (
        None if status == "PASS" else f"Identity score {score:.2f} below threshold {threshold:.2f}"
    )
    return outcome(
        "agent_identity_consistent",
        status,
        detail,
        elapsed=elapsed(start),
        score=statistics.fmean([score]),
        threshold=threshold,
    )


HANDLERS = {"agent_identity_consistent": agent_identity_consistent}
