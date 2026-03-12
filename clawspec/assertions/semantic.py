from __future__ import annotations

import statistics
import time
from typing import Any

import httpx

from .common import elapsed, load_text, outcome


def _extract_score(response: httpx.Response | Any) -> float:
    payload = response.json()
    if "score" in payload:
        return float(payload["score"])
    if "result" in payload and isinstance(payload["result"], dict) and "score" in payload["result"]:
        return float(payload["result"]["score"])
    raise ValueError("Judge response missing score")


def llm_judge(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    _, text = load_text(assertion["path"])
    if text is None:
        return outcome(
            "llm_judge", "FAIL", f"Artifact not found: {assertion['path']}", elapsed=elapsed(start)
        )

    consistency = assertion.get("consistency") or {}
    runs = int(consistency.get("runs", 1))
    min_passes = int(consistency.get("min_passes", 1))
    threshold = float(assertion.get("pass_threshold", 3))
    scores: list[float] = []
    try:
        for _ in range(runs):
            response = httpx.post(
                assertion.get("endpoint", "http://localhost:18789/qa/judge"),
                json={
                    "rubric": assertion["rubric"],
                    "text": text,
                    "section": assertion.get("section"),
                },
                timeout=30.0,
            )
            scores.append(_extract_score(response))
    except (httpx.HTTPError, ValueError) as exc:
        return outcome("llm_judge", "SKIP", str(exc), elapsed=elapsed(start))

    if not scores:
        return outcome(
            "llm_judge",
            "SKIP",
            "consistency.runs is 0; no scores collected",
            elapsed=elapsed(start),
        )

    passes = sum(score >= threshold for score in scores)
    status = "PASS" if passes >= min_passes else "WARN"
    score = statistics.fmean(scores)
    detail = (
        None if status == "PASS" else f"Judge score {score:.2f} below threshold {threshold:.2f}"
    )
    return outcome(
        "llm_judge",
        status,
        detail,
        elapsed=elapsed(start),
        score=round(score, 4),
        threshold=threshold,
    )


HANDLERS = {"llm_judge": llm_judge}
