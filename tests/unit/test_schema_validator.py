from pathlib import Path

from clawspec.schema_validator import validate_contract_file

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _write_pipeline_contract(
    repo_root: Path,
    *,
    pipeline_yaml: str,
    handoffs: dict[str, str] | None = None,
) -> Path:
    skill_dir = repo_root / "skills" / "webinar-orchestrator"
    pipeline_path = skill_dir / "tests" / "pipeline.yaml"
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.write_text(pipeline_yaml, encoding="utf-8")
    for relative_path, content in (handoffs or {}).items():
        handoff_path = skill_dir / relative_path
        handoff_path.parent.mkdir(parents=True, exist_ok=True)
        handoff_path.write_text(content, encoding="utf-8")
    return pipeline_path


def test_valid_scenario_contract_passes() -> None:
    result = validate_contract_file(FIXTURES / "valid_scenario.yaml")

    assert result.valid is True
    assert result.kind == "scenario"
    assert result.errors == []


def test_valid_handoff_contract_passes() -> None:
    result = validate_contract_file(FIXTURES / "valid_handoff.yaml")

    assert result.valid is True
    assert result.kind == "handoff"
    assert result.errors == []


def test_valid_pipeline_contract_passes() -> None:
    result = validate_contract_file(FIXTURES / "valid_pipeline.yaml")

    assert result.valid is True
    assert result.kind == "pipeline"
    assert result.errors == []


def test_missing_then_is_rejected() -> None:
    result = validate_contract_file(FIXTURES / "invalid_scenarios" / "missing_then.yaml")

    assert result.valid is False
    assert any("then" in error.message for error in result.errors)


def test_unknown_assertion_type_is_rejected() -> None:
    result = validate_contract_file(FIXTURES / "invalid_scenarios" / "unknown_type.yaml")

    assert result.valid is False
    assert any("made_up_check" in error.message for error in result.errors)


def test_unsupported_version_is_rejected() -> None:
    result = validate_contract_file(FIXTURES / "invalid_scenarios" / "bad_version.yaml")

    assert result.valid is False
    assert any("1.0" in error.message for error in result.errors)


def test_pipeline_stage_count_must_match_declared_total(tmp_path: Path) -> None:
    pipeline_path = _write_pipeline_contract(
        tmp_path,
        pipeline_yaml="""version: "1.0"
pipeline:
  name: webinar-orchestrator
  skill_path: skills/webinar-orchestrator
  trigger: /webinar-orchestrator
  stages: 2
stages:
  - name: discovery
    produces: memory/drafts/webinars/{{today}}-brief.md
""",
    )

    result = validate_contract_file(pipeline_path)

    assert result.valid is False
    assert any("pipeline.stages" in error.message for error in result.errors)


def test_pipeline_stage_names_must_be_unique(tmp_path: Path) -> None:
    pipeline_path = _write_pipeline_contract(
        tmp_path,
        pipeline_yaml="""version: "1.0"
pipeline:
  name: webinar-orchestrator
  skill_path: skills/webinar-orchestrator
  trigger: /webinar-orchestrator
  stages: 2
stages:
  - name: discovery
    produces: memory/drafts/webinars/{{today}}-brief.md
  - name: discovery
    produces: memory/drafts/webinars/{{today}}-copy.md
""",
    )

    result = validate_contract_file(pipeline_path)

    assert result.valid is False
    assert any("Duplicate stage name" in error.message for error in result.errors)


def test_pipeline_handoff_contracts_must_exist(tmp_path: Path) -> None:
    pipeline_path = _write_pipeline_contract(
        tmp_path,
        pipeline_yaml="""version: "1.0"
pipeline:
  name: webinar-orchestrator
  skill_path: skills/webinar-orchestrator
  trigger: /webinar-orchestrator
  stages: 1
stages:
  - name: discovery
    produces: memory/drafts/webinars/{{today}}-brief.md
    handoff_contract: tests/handoffs/orchestrator-to-prism.yaml
""",
    )

    result = validate_contract_file(pipeline_path)

    assert result.valid is False
    assert any("handoff contract does not exist" in error.message for error in result.errors)


def test_pipeline_with_existing_handoff_contracts_passes(tmp_path: Path) -> None:
    pipeline_path = _write_pipeline_contract(
        tmp_path,
        pipeline_yaml="""version: "1.0"
pipeline:
  name: webinar-orchestrator
  skill_path: skills/webinar-orchestrator
  trigger: /webinar-orchestrator
  stages: 1
stages:
  - name: discovery
    produces: memory/drafts/webinars/{{today}}-brief.md
    handoff_contract: tests/handoffs/orchestrator-to-prism.yaml
""",
        handoffs={
            "tests/handoffs/orchestrator-to-prism.yaml": """version: "1.0"
handoff:
  from: agents-marketing-campaign-orchestrator
  to: agents-marketing-webinar
  mechanism: sessions_spawn
caller_provides:
  required_context:
    - name: topic
      description: Topic to research
callee_produces:
  required_artifacts:
    - path_pattern: memory/drafts/webinars/{{today}}-brief.md
      description: Discovery brief
""",
        },
    )

    result = validate_contract_file(pipeline_path)

    assert result.valid is True
