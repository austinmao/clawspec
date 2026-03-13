from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from clawspec.runner import evaluate as evaluate_module

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "valid_scenario.yaml"


class _JudgeResponse:
    def __init__(self, score: int) -> None:
        self.status_code = 200
        self._score = score

    def json(self) -> dict[str, int]:
        return {"score": self._score}


def test_evaluate_scenario_writes_warn_report_and_returns_zero(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    fixed_now = datetime(2026, 3, 11, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(evaluate_module, "_utc_now", lambda: fixed_now)
    monkeypatch.setattr(evaluate_module, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(evaluate_module, "REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr(
        "clawspec.assertions.semantic.httpx.post",
        lambda url, json, timeout=30.0: _JudgeResponse(2),
    )

    draft_path = tmp_path / "memory" / "drafts" / "2026-03-11-newsletter.md"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text("# hook\n\nA clean draft.\n", encoding="utf-8")

    exit_code = evaluate_module.main(["--scenario-file", str(FIXTURE), "--run-number", "2"])
    output = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert output[0]["status"] == "WARN"
    report_path = Path(output[0]["report_path"])
    assert report_path.exists()

    persisted = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "WARN"
    assert persisted["feedback"]["structured"][0]["check"] == "llm_judge"


def test_evaluate_main_accepts_evaluate_only_flag(monkeypatch, tmp_path: Path, capsys) -> None:
    fixed_now = datetime(2026, 3, 11, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(evaluate_module, "_utc_now", lambda: fixed_now)
    monkeypatch.setattr(evaluate_module, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(evaluate_module, "REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr(
        "clawspec.assertions.semantic.httpx.post",
        lambda url, json, timeout=30.0: _JudgeResponse(3),
    )

    draft_path = tmp_path / "memory" / "drafts" / "2026-03-11-newsletter.md"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text("# hook\n\nA clean draft.\n", encoding="utf-8")

    exit_code = evaluate_module.main(
        ["--scenario-file", str(FIXTURE), "--run-number", "1", "--evaluate-only"]
    )
    output = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert output[0]["status"] == "PASS"


def test_evaluate_contract_defaults_run_id_for_template_expansion(
    monkeypatch, tmp_path: Path
) -> None:
    fixed_now = datetime(2026, 3, 11, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(evaluate_module, "_utc_now", lambda: fixed_now)
    monkeypatch.setattr(evaluate_module, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(evaluate_module, "REPORT_DIR", tmp_path / "reports")

    scenario_path = tmp_path / "skills" / "newsletter" / "tests" / "scenarios.yaml"
    scenario_path.parent.mkdir(parents=True, exist_ok=True)
    scenario_path.write_text(
        """version: "1.0"
target:
  type: skill
  path: skills/newsletter
  trigger: /send-newsletter
scenarios:
  - name: rejects-out-of-scope
    tags: [negative]
    when:
      invoke: /send-newsletter do something forbidden
    then:
      - type: tool_not_called
        tool: resend.send
        log_path: /tmp/openclaw/openclaw-{{today}}.log
        run_id: "{{run_id}}"
""",
        encoding="utf-8",
    )

    reports = evaluate_module.evaluate_contract(scenario_path, run_number=1)

    assert reports[0]["status"] == "PASS"


def test_evaluate_contract_marks_rate_limit_runs_as_infrastructure(
    monkeypatch, tmp_path: Path
) -> None:
    fixed_now = datetime(2026, 3, 11, 12, 2, tzinfo=UTC)
    monkeypatch.setattr(evaluate_module, "_utc_now", lambda: fixed_now)
    monkeypatch.setattr(evaluate_module, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(evaluate_module, "REPORT_DIR", tmp_path / "reports")

    log_path = tmp_path / "gateway.log"
    log_path.write_text(
        json.dumps(
            {
                "time": "2026-03-11T12:00:30Z",
                "message": "embedded run agent end: error=API rate limit reached",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    scenario_path = tmp_path / "skills" / "newsletter" / "tests" / "scenarios.yaml"
    scenario_path.parent.mkdir(parents=True, exist_ok=True)
    scenario_path.write_text(
        """version: "1.0"
target:
  type: skill
  path: skills/newsletter
  trigger: /send-newsletter
scenarios:
  - name: smoke
    tags: [smoke]
    when:
      invoke: /send-newsletter Sunday Service
    then:
      - type: artifact_exists
        path: memory/drafts/{{today}}-newsletter.md
""",
        encoding="utf-8",
    )

    reports = evaluate_module.evaluate_contract(
        scenario_path,
        run_number=1,
        extra_context={
            "run_started_at": "2026-03-11T12:00:00Z",
            "gateway_log_path": str(log_path),
        },
    )

    assert reports[0]["status"] == "ERROR"
    assert reports[0]["infrastructure_failure"] is True
    assert "rate limit" in reports[0]["detail"].casefold()


def test_evaluate_contract_ignores_rate_limit_logs_outside_run_window(
    monkeypatch, tmp_path: Path
) -> None:
    fixed_now = datetime(2026, 3, 11, 12, 2, tzinfo=UTC)
    monkeypatch.setattr(evaluate_module, "_utc_now", lambda: fixed_now)
    monkeypatch.setattr(evaluate_module, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(evaluate_module, "REPORT_DIR", tmp_path / "reports")

    log_path = tmp_path / "gateway.log"
    log_path.write_text(
        json.dumps(
            {
                "time": "2026-03-11T11:59:30Z",
                "message": "embedded run agent end: error=API rate limit reached",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    scenario_path = tmp_path / "skills" / "newsletter" / "tests" / "scenarios.yaml"
    scenario_path.parent.mkdir(parents=True, exist_ok=True)
    scenario_path.write_text(
        """version: "1.0"
target:
  type: skill
  path: skills/newsletter
  trigger: /send-newsletter
scenarios:
  - name: smoke
    tags: [smoke]
    when:
      invoke: /send-newsletter Sunday Service
    then:
      - type: artifact_exists
        path: memory/drafts/{{today}}-newsletter.md
""",
        encoding="utf-8",
    )

    reports = evaluate_module.evaluate_contract(
        scenario_path,
        run_number=1,
        extra_context={
            "run_started_at": "2026-03-11T12:00:00Z",
            "gateway_log_path": str(log_path),
        },
    )

    assert reports[0]["status"] == "FAIL"
    assert reports[0]["infrastructure_failure"] is False
    assert reports[0]["detail"] is None
