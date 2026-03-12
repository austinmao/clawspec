from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from clawspec.assertions import integration as integration_module
from clawspec.assertions import precondition as precondition_module
from clawspec.assertions import semantic as semantic_module
from clawspec.assertions.artifact import (
    artifact_absent_words,
    artifact_contains,
    artifact_exists,
    artifact_matches_golden,
    state_file,
)
from clawspec.assertions.behavioral import decision_routed_to, log_entry
from clawspec.assertions.integration import gateway_response
from clawspec.assertions.precondition import (
    env_present,
    file_absent,
    file_present,
    gateway_healthy,
)
from clawspec.assertions.semantic import llm_judge


class _Response:
    def __init__(self, *, status_code: int, text: str = "", payload: dict | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


def test_file_present_and_file_absent(tmp_path: Path) -> None:
    existing = tmp_path / "exists.txt"
    existing.write_text("hello", encoding="utf-8")

    present_result = file_present({"type": "file_present", "path": str(existing)}, {})
    absent_result = file_absent({"type": "file_absent", "path": str(tmp_path / "missing.txt")}, {})

    assert present_result["status"] == "PASS"
    assert absent_result["status"] == "PASS"


def test_gateway_healthy_and_gateway_response(monkeypatch) -> None:
    def fake_get(url: str, timeout: float = 5.0) -> _Response:
        if url.endswith("/health"):
            return _Response(status_code=200)
        return _Response(status_code=202, text="ok body")

    monkeypatch.setattr(precondition_module.httpx, "get", fake_get)
    monkeypatch.setattr(integration_module.httpx, "get", fake_get)

    health_result = gateway_healthy({"type": "gateway_healthy"}, {})
    response_result = gateway_response(
        {
            "type": "gateway_response",
            "endpoint": "http://localhost:18789/custom",
            "expected_status": 202,
            "expected_body": "ok body",
        },
        {},
    )

    assert health_result["status"] == "PASS"
    assert response_result["status"] == "PASS"


def test_env_present_fails_when_required_env_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("REQUIRED_ENV", raising=False)

    result = env_present({"type": "env_present", "vars": ["REQUIRED_ENV"]}, {})

    assert result["status"] == "FAIL"


def test_artifact_exists_and_contains_pass(tmp_path: Path) -> None:
    artifact = tmp_path / "draft.md"
    artifact.write_text("# hook\n\n## teaching_insight\n\n## cta\n", encoding="utf-8")

    exists_result = artifact_exists({"type": "artifact_exists", "path": str(artifact)}, {})
    contains_result = artifact_contains(
        {
            "type": "artifact_contains",
            "path": str(artifact),
            "sections": ["hook", "teaching_insight", "cta"],
        },
        {},
    )

    assert exists_result["status"] == "PASS"
    assert contains_result["status"] == "PASS"


def test_artifact_assertions_can_require_fresh_outputs(tmp_path: Path) -> None:
    artifact = tmp_path / "draft.md"
    artifact.write_text("# hook\n\n## cta\n", encoding="utf-8")

    stale_at = datetime.now(UTC) - timedelta(minutes=5)
    fresh_after = datetime.now(UTC)
    fresh_at = fresh_after + timedelta(minutes=5)
    os.utime(artifact, (stale_at.timestamp(), stale_at.timestamp()))

    stale_exists = artifact_exists(
        {
            "type": "artifact_exists",
            "path": str(artifact),
            "updated_after": fresh_after.isoformat().replace("+00:00", "Z"),
        },
        {},
    )
    assert stale_exists["status"] == "FAIL"

    artifact.write_text("# hook\n\n## teaching_insight\n\n## cta\n", encoding="utf-8")
    os.utime(artifact, (fresh_at.timestamp(), fresh_at.timestamp()))

    fresh_contains = artifact_contains(
        {
            "type": "artifact_contains",
            "path": str(artifact),
            "updated_after": fresh_after.isoformat().replace("+00:00", "Z"),
            "sections": ["hook", "teaching_insight", "cta"],
        },
        {},
    )

    assert fresh_contains["status"] == "PASS"


def test_artifact_absent_words_fails_when_prohibited_word_is_present(tmp_path: Path) -> None:
    artifact = tmp_path / "draft.md"
    artifact.write_text("This contains sacred language.\n", encoding="utf-8")
    source = tmp_path / "kill-list.yaml"
    source.write_text("brand:\n  kill_list:\n    - sacred\n", encoding="utf-8")

    result = artifact_absent_words(
        {
            "type": "artifact_absent_words",
            "path": str(artifact),
            "source": str(source),
            "key": "brand.kill_list",
        },
        {},
    )

    assert result["status"] == "FAIL"
    assert "sacred" in result["detail"]


def test_artifact_matches_golden_returns_warn_for_low_similarity(tmp_path: Path) -> None:
    artifact = tmp_path / "actual.md"
    golden = tmp_path / "golden.md"
    artifact.write_text("alpha beta", encoding="utf-8")
    golden.write_text("completely different text", encoding="utf-8")

    result = artifact_matches_golden(
        {
            "type": "artifact_matches_golden",
            "path": str(artifact),
            "golden": str(golden),
            "rouge_threshold": 0.8,
        },
        {},
    )

    assert result["status"] == "WARN"
    assert result["score"] < result["threshold"]


def test_state_file_and_decision_routed_to_pass(tmp_path: Path) -> None:
    state_path = tmp_path / "state.yaml"
    state_path.write_text(
        "status: ready\nselected_agent: agents/marketing/brand\n", encoding="utf-8"
    )

    state_result = state_file(
        {
            "type": "state_file",
            "state_path": str(state_path),
            "expected_status": "ready",
            "expected_fields": {"selected_agent": "agents/marketing/brand"},
        },
        {},
    )
    routed_result = decision_routed_to(
        {
            "type": "decision_routed_to",
            "state_path": str(state_path),
            "expected_agent": "agents/marketing/brand",
        },
        {},
    )

    assert state_result["status"] == "PASS"
    assert routed_result["status"] == "PASS"


def test_state_file_can_require_fresh_write(tmp_path: Path) -> None:
    state_path = tmp_path / "state.yaml"
    state_path.write_text(
        "status: ready\nselected_agent: agents/marketing/brand\n", encoding="utf-8"
    )

    stale_at = datetime.now(UTC) - timedelta(minutes=5)
    fresh_after = datetime.now(UTC)
    os.utime(state_path, (stale_at.timestamp(), stale_at.timestamp()))

    stale_result = state_file(
        {
            "type": "state_file",
            "state_path": str(state_path),
            "updated_after": fresh_after.isoformat().replace("+00:00", "Z"),
            "expected_status": "ready",
        },
        {},
    )

    assert stale_result["status"] == "FAIL"


def test_log_entry_supports_presence_and_absence_checks(tmp_path: Path) -> None:
    log_path = tmp_path / "service.log"
    log_path.write_text("pipeline completed\n", encoding="utf-8")

    present_result = log_entry(
        {"type": "log_entry", "path": str(log_path), "pattern": "completed"},
        {},
    )
    absent_result = log_entry(
        {"type": "log_entry", "path": str(log_path), "pattern": "failed", "absent": True},
        {},
    )

    assert present_result["status"] == "PASS"
    assert absent_result["status"] == "PASS"


def test_llm_judge_warns_below_threshold(monkeypatch, tmp_path: Path) -> None:
    artifact = tmp_path / "copy.md"
    artifact.write_text("A short draft.", encoding="utf-8")
    monkeypatch.setattr(
        semantic_module.httpx,
        "post",
        lambda url, json, timeout=30.0: _Response(status_code=200, payload={"score": 2}),
    )

    result = llm_judge(
        {
            "type": "llm_judge",
            "path": str(artifact),
            "rubric": "Score 1-5",
            "pass_threshold": 3,
        },
        {},
    )

    assert result["status"] == "WARN"
    assert result["score"] == 2
