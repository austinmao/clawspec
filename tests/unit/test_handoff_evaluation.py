from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from clawspec.runner import evaluate as evaluate_module
from clawspec.schema_validator import validate_contract_file

GATEWAY_LOG = (
    Path(__file__).resolve().parents[1] / "fixtures" / "sample_gateway_logs" / "with_delegation.log"
)


def _write_handoff_contract(tmp_path: Path, *, include_assertions: bool) -> Path:
    contract_path = tmp_path / "handoff.yaml"
    assertions_block = ""
    if include_assertions:
        assertions_block = """
assertions:
  pre_delegation:
    - type: delegation_occurred
      from_agent: "{{handoff.from}}"
      to_agent: "{{handoff.to}}"
      log_path: "__GATEWAY_LOG__"
      run_id: "{{run_id}}"
  post_delegation:
    - type: artifact_exists
      path: "{{repo_root}}/memory/drafts/{{today}}-copy.md"
    - type: tool_not_called
      tool: resend.send
      log_path: "__GATEWAY_LOG__"
      run_id: "{{callee_run_id}}"
"""
    contents = f"""version: "1.0"
handoff:
  from: agents-marketing-campaign-orchestrator
  to: agents-marketing-brand
  mechanism: sessions_spawn
caller_provides:
  required_context:
    - name: topic
      description: Subject matter
callee_produces:
  required_artifacts:
    - path_pattern: "{{{{repo_root}}}}/memory/drafts/{{{{today}}}}-copy.md"
      description: Copy output
      required_sections: [hook, cta]
  prohibited_actions:
    - tool: resend.send
      reason: Brand agent only drafts
{assertions_block}
"""
    contract_path.write_text(
        contents.replace("__GATEWAY_LOG__", str(GATEWAY_LOG)),
        encoding="utf-8",
    )
    return contract_path


def test_handoff_validator_rejects_duplicate_required_context_names(tmp_path: Path) -> None:
    contract = tmp_path / "invalid_handoff.yaml"
    contract.write_text(
        """version: "1.0"
handoff:
  from: agents-marketing-campaign-orchestrator
  to: agents-marketing-brand
  mechanism: sessions_spawn
caller_provides:
  required_context:
    - name: topic
      description: One
    - name: topic
      description: Two
callee_produces:
  required_artifacts:
    - path_pattern: memory/drafts/{{today}}-copy.md
      description: Copy output
""",
        encoding="utf-8",
    )

    result = validate_contract_file(contract)

    assert result.valid is False
    assert any("duplicate" in error.message.casefold() for error in result.errors)


def test_default_handoff_assertions_are_generated_and_pass(tmp_path: Path, monkeypatch) -> None:
    contract_path = _write_handoff_contract(tmp_path, include_assertions=False)
    fixed_now = datetime(2026, 3, 11, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(evaluate_module, "_utc_now", lambda: fixed_now)
    monkeypatch.setattr(evaluate_module, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(evaluate_module, "REPORT_DIR", tmp_path / "reports")

    artifact = tmp_path / "memory" / "drafts" / "2026-03-11-copy.md"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("# hook\n\n## cta\n", encoding="utf-8")

    reports = evaluate_module.evaluate_contract(
        contract_path,
        run_number=1,
        extra_context={
            "run_id": "run-456",
            "callee_run_id": "run-789",
            "gateway_log_path": str(GATEWAY_LOG),
        },
    )

    assertion_names = [item["name"] for item in reports[0]["assertions"]]
    assert reports[0]["status"] == "PASS"
    assert assertion_names == [
        "delegation_occurred",
        "artifact_exists",
        "artifact_contains",
        "tool_not_called",
    ]


def test_handoff_template_variables_and_pre_post_order_are_preserved(
    tmp_path: Path, monkeypatch
) -> None:
    contract_path = _write_handoff_contract(tmp_path, include_assertions=True)
    fixed_now = datetime(2026, 3, 11, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(evaluate_module, "_utc_now", lambda: fixed_now)
    monkeypatch.setattr(evaluate_module, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(evaluate_module, "REPORT_DIR", tmp_path / "reports")

    artifact = tmp_path / "memory" / "drafts" / "2026-03-11-copy.md"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("# hook\n\n## cta\n", encoding="utf-8")

    reports = evaluate_module.evaluate_contract(
        contract_path,
        run_number=2,
        extra_context={
            "run_id": "run-456",
            "callee_run_id": "run-789",
            "gateway_log_path": str(GATEWAY_LOG),
        },
    )

    assertion_names = [item["name"] for item in reports[0]["assertions"]]
    assert reports[0]["status"] == "PASS"
    assert assertion_names[0] == "delegation_occurred"
    assert assertion_names[-1] == "tool_not_called"
