from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .common import elapsed, load_structured, load_text, matching_paths, outcome, resolve_key_path


def _parse_updated_after(value: str | None) -> float | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _fresh_matches(path_pattern: str, *, updated_after: float | None = None) -> list[Path]:
    matches = matching_paths(path_pattern)
    if updated_after is None:
        return matches
    return [path for path in matches if path.stat().st_mtime >= updated_after]


def _poll_for_match(
    path_pattern: str, timeout: float, *, updated_after: float | None = None
) -> list[Path]:
    deadline = time.time() + timeout
    while True:
        matches = _fresh_matches(path_pattern, updated_after=updated_after)
        if matches:
            return matches
        if timeout <= 0 or time.time() >= deadline:
            return []
        time.sleep(0.1)


def artifact_exists(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    timeout = float(assertion.get("timeout", 0))
    updated_after = _parse_updated_after(assertion.get("updated_after"))
    matches = _poll_for_match(assertion["path"], timeout, updated_after=updated_after)
    if matches:
        return outcome("artifact_exists", "PASS", None, elapsed=elapsed(start))
    detail = f"Artifact not found before timeout: {assertion['path']}"
    return outcome("artifact_exists", "FAIL", detail, elapsed=elapsed(start))


def artifact_contains(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    timeout = float(assertion.get("timeout", 0))
    updated_after = _parse_updated_after(assertion.get("updated_after"))
    matches = _poll_for_match(assertion["path"], timeout, updated_after=updated_after)
    if not matches:
        return outcome(
            "artifact_contains",
            "FAIL",
            f"Artifact not found: {assertion['path']}",
            elapsed=elapsed(start),
        )
    path = max(matches, key=lambda candidate: (candidate.stat().st_mtime, str(candidate)))
    text = path.read_text(encoding="utf-8")

    missing_sections = []
    for section in assertion.get("sections", []):
        heading = f"# {section}".casefold()
        subheading = f"## {section}".casefold()
        colon_form = f"{section}:".casefold()
        lowered = text.casefold()
        if heading not in lowered and subheading not in lowered and colon_form not in lowered:
            missing_sections.append(section)

    missing_fields = []
    if assertion.get("fields"):
        _, payload = load_structured(assertion["path"])
        for field in assertion.get("fields", []):
            if payload is None or resolve_key_path(payload, field) is None:
                missing_fields.append(field)

    if missing_sections or missing_fields:
        parts = []
        if missing_sections:
            parts.append(f"missing sections: {', '.join(missing_sections)}")
        if missing_fields:
            parts.append(f"missing fields: {', '.join(missing_fields)}")
        return outcome("artifact_contains", "FAIL", "; ".join(parts), elapsed=elapsed(start))
    return outcome("artifact_contains", "PASS", None, elapsed=elapsed(start))


def artifact_absent_words(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    timeout = float(assertion.get("timeout", 0))
    updated_after = _parse_updated_after(assertion.get("updated_after"))
    matches = _poll_for_match(assertion["path"], timeout, updated_after=updated_after)
    if not matches:
        return outcome(
            "artifact_absent_words",
            "FAIL",
            f"Artifact not found: {assertion['path']}",
            elapsed=elapsed(start),
        )
    path = max(matches, key=lambda candidate: (candidate.stat().st_mtime, str(candidate)))
    text = path.read_text(encoding="utf-8")

    words = assertion.get("words")
    if words is None:
        source_path = assertion["source"]
        _, payload = load_structured(source_path)
        words = resolve_key_path(payload or {}, assertion["key"]) or []

    lowered = text.casefold()
    found = [word for word in words if str(word).casefold() in lowered]
    if found:
        return outcome(
            "artifact_absent_words",
            "FAIL",
            f"Found prohibited words: {', '.join(map(str, found))}",
            elapsed=elapsed(start),
        )
    return outcome("artifact_absent_words", "PASS", None, elapsed=elapsed(start))


def _lcs_length(left: list[str], right: list[str]) -> int:
    rows = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
    for i, left_token in enumerate(left, start=1):
        for j, right_token in enumerate(right, start=1):
            if left_token == right_token:
                rows[i][j] = rows[i - 1][j - 1] + 1
            else:
                rows[i][j] = max(rows[i - 1][j], rows[i][j - 1])
    return rows[-1][-1]


def artifact_matches_golden(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    timeout = float(assertion.get("timeout", 0))
    updated_after = _parse_updated_after(assertion.get("updated_after"))
    matches = _poll_for_match(assertion["path"], timeout, updated_after=updated_after)
    actual = None
    if matches:
        path = max(matches, key=lambda candidate: (candidate.stat().st_mtime, str(candidate)))
        actual = path.read_text(encoding="utf-8")
    _, golden = load_text(assertion["golden"])
    if actual is None:
        return outcome(
            "artifact_matches_golden",
            "FAIL",
            f"Artifact not found: {assertion['path']}",
            elapsed=elapsed(start),
        )
    if golden is None:
        return outcome(
            "artifact_matches_golden",
            "FAIL",
            f"Golden file not found: {assertion['golden']}",
            elapsed=elapsed(start),
        )

    actual_tokens = actual.split()
    golden_tokens = golden.split()
    lcs = _lcs_length(actual_tokens, golden_tokens)
    precision = lcs / len(actual_tokens) if actual_tokens else 0.0
    recall = lcs / len(golden_tokens) if golden_tokens else 0.0
    score = 0.0 if precision + recall == 0 else (2 * precision * recall) / (precision + recall)
    threshold = float(assertion.get("rouge_threshold", 0.5))
    status = "PASS" if score >= threshold else "WARN"
    detail = None if status == "PASS" else f"ROUGE-L {score:.3f} below threshold {threshold:.3f}"
    return outcome(
        "artifact_matches_golden",
        status,
        detail,
        elapsed=elapsed(start),
        score=round(score, 4),
        threshold=threshold,
    )


def state_file(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    state_path = assertion.get("state_path") or assertion.get("path")
    timeout = float(assertion.get("timeout", 0))
    updated_after = _parse_updated_after(assertion.get("updated_after"))
    matches = _poll_for_match(state_path, timeout, updated_after=updated_after)
    if not matches:
        return outcome(
            "state_file", "FAIL", f"State file not found: {state_path}", elapsed=elapsed(start)
        )
    path = max(matches, key=lambda candidate: (candidate.stat().st_mtime, str(candidate)))
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        import json as _json

        payload = _json.loads(text)
    else:
        payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        return outcome(
            "state_file", "FAIL", f"State file not found: {state_path}", elapsed=elapsed(start)
        )

    expected_status = assertion.get("expected_status")
    if expected_status is not None and payload.get("status") != expected_status:
        return outcome(
            "state_file",
            "FAIL",
            f"Expected status {expected_status}, got {payload.get('status')}",
            elapsed=elapsed(start),
        )

    for key, expected in (assertion.get("expected_fields") or {}).items():
        actual = resolve_key_path(payload, key)
        if actual != expected:
            return outcome(
                "state_file",
                "FAIL",
                f"Expected {key}={expected}, got {actual}",
                elapsed=elapsed(start),
            )

    return outcome("state_file", "PASS", None, elapsed=elapsed(start))


HANDLERS = {
    "artifact_exists": artifact_exists,
    "artifact_contains": artifact_contains,
    "artifact_absent_words": artifact_absent_words,
    "artifact_matches_golden": artifact_matches_golden,
    "state_file": state_file,
}
