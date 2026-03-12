from __future__ import annotations

from pathlib import Path

from clawspec.runner import run as run_module


def _write_valid_skill(path: Path, *, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
name: {name}
description: "Use when running {name} contract tests."
version: "1.0.0"
permissions:
  filesystem: read
  network: false
metadata:
  openclaw:
    requires:
      bins:
        - python3
      env: []
---

Use python3 to run local QA checks safely.
""",
        encoding="utf-8",
    )


def _write_scenarios(repo_root: Path) -> Path:
    skill_dir = repo_root / "skills" / "newsletter"
    _write_valid_skill(skill_dir / "SKILL.md", name="newsletter")
    scenarios_path = skill_dir / "tests" / "scenarios.yaml"
    scenarios_path.parent.mkdir(parents=True, exist_ok=True)
    scenarios_path.write_text(
        """version: "1.0"
target:
  type: skill
  path: skills/newsletter
  trigger: /send-newsletter

scenarios:
  - name: happy-path
    tags: [smoke]
    given:
      - type: file_absent
        path: "{{repo_root}}/memory/drafts/{{today}}-newsletter.md"
    when:
      invoke: /send-newsletter Sunday Service
      params:
        test_mode: true
    then:
      - type: artifact_exists
        path: "{{repo_root}}/memory/drafts/{{today}}-newsletter.md"

  - name: regression-path
    tags: [regression]
    when:
      invoke: /send-newsletter Replay
      params:
        test_mode: true
    then:
      - type: artifact_exists
        path: "{{repo_root}}/memory/drafts/{{today}}-replay.md"

  - name: rejects-out-of-scope
    tags: [negative]
    when:
      invoke: /send-newsletter do something forbidden
      params:
        test_mode: true
    then:
      - type: artifact_exists
        path: "{{repo_root}}/memory/drafts/{{today}}-forbidden.md"
""",
        encoding="utf-8",
    )
    return scenarios_path


def _write_pipeline(repo_root: Path) -> Path:
    skill_dir = repo_root / "skills" / "webinar-orchestrator"
    _write_valid_skill(skill_dir / "SKILL.md", name="webinar-orchestrator")
    scenarios_path = skill_dir / "tests" / "scenarios.yaml"
    scenarios_path.parent.mkdir(parents=True, exist_ok=True)
    scenarios_path.write_text(
        """version: "1.0"
target:
  type: skill
  path: skills/webinar-orchestrator
  trigger: /webinar-orchestrator

scenarios:
  - name: smoke
    tags: [smoke]
    when:
      invoke: /webinar-orchestrator
      params:
        test_mode: true
    then:
      - type: artifact_exists
        path: "{{repo_root}}/memory/drafts/webinars/{{today}}-outline.md"

  - name: rejects-out-of-scope
    tags: [negative]
    when:
      invoke: /webinar-orchestrator do something forbidden
      params:
        test_mode: true
    then:
      - type: artifact_exists
        path: "{{repo_root}}/memory/drafts/webinars/{{today}}-forbidden.md"
""",
        encoding="utf-8",
    )
    pipeline_path = skill_dir / "tests" / "pipeline.yaml"
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.write_text(
        """version: "1.0"
pipeline:
  name: webinar-orchestrator
  skill_path: skills/webinar-orchestrator
  trigger: /webinar-orchestrator
  stages: 1
  estimated_duration: 5m
stages:
  - name: outline
    agent: agents-marketing-webinar
    produces: memory/drafts/webinars/{{today}}-outline.md
final_assertions:
  deterministic:
    - type: artifact_exists
      path: memory/drafts/webinars/{{today}}-outline.md
pipeline_health: []
""",
        encoding="utf-8",
    )
    return pipeline_path


def _write_pipeline_monitoring_contract(repo_root: Path) -> Path:
    skill_dir = repo_root / "skills" / "webinar-orchestrator"
    _write_valid_skill(skill_dir / "SKILL.md", name="webinar-orchestrator")
    (skill_dir / "tests").mkdir(parents=True, exist_ok=True)
    (skill_dir / "tests" / "scenarios.yaml").write_text(
        """version: "1.0"
target:
  type: skill
  path: skills/webinar-orchestrator
  trigger: /webinar-orchestrator
scenarios:
  - name: smoke
    tags: [smoke]
    when:
      invoke: /webinar-orchestrator
      params:
        test_mode: true
    then:
      - type: artifact_exists
        path: memory/drafts/webinars/{{today}}-copy.md

  - name: rejects-out-of-scope
    tags: [negative]
    when:
      invoke: /webinar-orchestrator do something forbidden
      params:
        test_mode: true
    then:
      - type: artifact_exists
        path: memory/drafts/webinars/{{today}}-forbidden.md
""",
        encoding="utf-8",
    )
    pipeline_path = skill_dir / "tests" / "pipeline.yaml"
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    (skill_dir / "tests" / "handoffs").mkdir(parents=True, exist_ok=True)
    (skill_dir / "tests" / "handoffs" / "orchestrator-to-prism.yaml").write_text(
        """version: "1.0"
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
        encoding="utf-8",
    )
    (skill_dir / "tests" / "handoffs" / "prism-to-quill.yaml").write_text(
        """version: "1.0"
handoff:
  from: agents-marketing-webinar
  to: agents-marketing-brand
  mechanism: sessions_spawn
caller_provides:
  required_context:
    - name: brief_path
      description: Discovery brief
callee_produces:
  required_artifacts:
    - path_pattern: memory/drafts/webinars/{{today}}-copy.md
      description: Webinar copy
      required_sections: [hook, teaching_insight, cta]
""",
        encoding="utf-8",
    )
    pipeline_path.write_text(
        """version: "1.0"
pipeline:
  name: webinar-orchestrator
  skill_path: skills/webinar-orchestrator
  trigger: /webinar-orchestrator
  stages: 3
  estimated_duration: 15m
stages:
  - name: discovery
    agent: agents-marketing-webinar
    produces: memory/drafts/webinars/{{today}}-brief.md
    handoff_contract: tests/handoffs/orchestrator-to-prism.yaml
  - name: approval
    requires_approval: true
  - name: copy
    agent: agents-marketing-brand
    produces: memory/drafts/webinars/{{today}}-copy.md
    handoff_contract: tests/handoffs/prism-to-quill.yaml
final_assertions:
  deterministic:
    - type: artifact_exists
      path: memory/drafts/webinars/{{today}}-copy.md
pipeline_health:
  - description: All artifacts were produced
    check: count(produced_artifacts) == count(stages_with_produces)
  - description: All handoff contracts passed
    check: all handoff contracts passed
  - description: Pipeline duration acceptable
    check: elapsed <= 15m
""",
        encoding="utf-8",
    )
    return pipeline_path


def test_runner_dry_run_checks_preconditions_only(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_scenarios(tmp_path)

    def _unexpected_trigger(*args, **kwargs):
        raise AssertionError("dry-run should not trigger")

    monkeypatch.setattr(run_module, "_trigger_scenario", _unexpected_trigger)

    exit_code = run_module.main(
        ["--repo-root", str(tmp_path), "--target", "newsletter", "--dry-run"]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "DRY-RUN" in output
    assert "happy-path" in output


def test_runner_evaluate_only_skips_trigger(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_scenarios(tmp_path)

    def _unexpected_trigger(*args, **kwargs):
        raise AssertionError("evaluate-only should not trigger")

    monkeypatch.setattr(run_module, "_trigger_scenario", _unexpected_trigger)
    monkeypatch.setattr(
        run_module,
        "evaluate_contract",
        lambda *args, **kwargs: [
            {
                "workflow": "newsletter",
                "scenario": kwargs["scenario_name"],
                "run": 1,
                "status": "PASS",
                "report_path": str(tmp_path / "memory/logs/qa/pass.yaml"),
                "infrastructure_failure": False,
                "assertions": [],
                "feedback": None,
            }
        ],
    )

    exit_code = run_module.main(
        ["--repo-root", str(tmp_path), "--target", "newsletter", "--evaluate-only"]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PASS" in output


def test_runner_filters_by_tags(tmp_path: Path, monkeypatch) -> None:
    _write_scenarios(tmp_path)
    called: list[str] = []

    monkeypatch.setattr(
        run_module,
        "_trigger_scenario",
        lambda *args, **kwargs: {"run_id": "run-123", "status": "accepted"},
    )

    def _fake_evaluate(*args, **kwargs):
        called.append(kwargs["scenario_name"])
        return [
            {
                "workflow": "newsletter",
                "scenario": kwargs["scenario_name"],
                "run": 1,
                "status": "PASS",
                "report_path": str(tmp_path / "memory/logs/qa/pass.yaml"),
                "infrastructure_failure": False,
                "assertions": [],
                "feedback": None,
            }
        ]

    monkeypatch.setattr(run_module, "evaluate_contract", _fake_evaluate)

    exit_code = run_module.main(
        ["--repo-root", str(tmp_path), "--target", "newsletter", "--tags", "smoke"]
    )

    assert exit_code == 0
    assert called == ["happy-path"]


def test_runner_pipeline_evaluate_only_uses_pipeline_contract(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _write_pipeline(tmp_path)
    monkeypatch.setattr(
        run_module,
        "evaluate_contract",
        lambda *args, **kwargs: [
            {
                "workflow": "webinar-orchestrator",
                "scenario": "pipeline",
                "run": 1,
                "status": "PASS",
                "report_path": str(tmp_path / "memory/logs/qa/pipeline.yaml"),
                "infrastructure_failure": False,
                "assertions": [],
                "feedback": None,
            }
        ],
    )

    exit_code = run_module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--target",
            "webinar-orchestrator",
            "--pipeline",
            "--evaluate-only",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "pipeline" in output


def test_pipeline_runner_monitors_stages_and_evaluates_handoffs(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _write_pipeline_monitoring_contract(tmp_path)
    artifact_dir = tmp_path / "memory" / "drafts" / "webinars"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "2026-03-11-brief.md").write_text("# brief", encoding="utf-8")
    (artifact_dir / "2026-03-11-copy.md").write_text(
        "# hook\n\n# teaching_insight\n\n# cta\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_module,
        "_utc_now",
        lambda: __import__("datetime").datetime(
            2026, 3, 11, tzinfo=__import__("datetime").timezone.utc
        ),
    )
    monkeypatch.setattr(
        run_module,
        "_trigger_scenario",
        lambda *args, **kwargs: {"run_id": "pipeline-run", "status": "accepted"},
    )

    evaluated_paths: list[str] = []

    def _fake_evaluate(contract_path, *args, **kwargs):
        evaluated_paths.append(str(contract_path))
        if str(contract_path).endswith("pipeline.yaml"):
            return [
                {
                    "workflow": "webinar-orchestrator",
                    "scenario": "pipeline",
                    "run": 1,
                    "status": "PASS",
                    "report_path": str(tmp_path / "memory/logs/qa/pipeline.yaml"),
                    "infrastructure_failure": False,
                    "assertions": [],
                    "feedback": None,
                }
            ]
        return [
            {
                "workflow": Path(contract_path).stem,
                "scenario": Path(contract_path).stem,
                "run": 1,
                "status": "PASS",
                "report_path": str(
                    tmp_path / "memory/logs/qa" / f"{Path(contract_path).stem}.yaml"
                ),
                "infrastructure_failure": False,
                "assertions": [],
                "feedback": None,
            }
        ]

    monkeypatch.setattr(run_module, "evaluate_contract", _fake_evaluate)

    exit_code = run_module.main(
        ["--repo-root", str(tmp_path), "--target", "webinar-orchestrator", "--pipeline"]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert any(path.endswith("orchestrator-to-prism.yaml") for path in evaluated_paths)
    assert any(path.endswith("prism-to-quill.yaml") for path in evaluated_paths)
    assert evaluated_paths[-1].endswith("pipeline.yaml")
    assert "PASS" in output


def test_pipeline_health_fails_when_required_stage_is_missing(tmp_path: Path) -> None:
    _write_pipeline_monitoring_contract(tmp_path)
    artifact_dir = tmp_path / "memory" / "drafts" / "webinars"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "2026-03-11-brief.md").write_text("# brief", encoding="utf-8")

    contract = run_module._load_yaml(
        tmp_path / "skills" / "webinar-orchestrator" / "tests" / "pipeline.yaml"
    )
    state = run_module._monitor_pipeline_stages(
        contract=contract,
        repo_root=tmp_path,
        now=__import__("datetime").datetime(
            2026, 3, 11, tzinfo=__import__("datetime").timezone.utc
        ),
        evaluate_handoff=lambda path, run_id: {
            "workflow": Path(path).stem,
            "scenario": Path(path).stem,
            "status": "PASS",
        },
    )
    health_results = run_module._evaluate_pipeline_health(
        contract.get("pipeline_health", []),
        state=state,
        elapsed_seconds=60,
    )

    assert any(result["status"] == "FAIL" for result in health_results)
    assert any("count(produced_artifacts)" in (result["detail"] or "") for result in health_results)


def test_runner_pipeline_dry_run_newsletter_contract(tmp_path: Path, capsys) -> None:
    _write_pipeline(tmp_path)
    exit_code = run_module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--target",
            "webinar-orchestrator",
            "--pipeline",
            "--dry-run",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PIPELINE" in output
    assert "PASS" in output
    assert "DRY-RUN" in output


def test_runner_pipeline_dry_run_campaign_workflow_contract(tmp_path: Path, capsys) -> None:
    _write_pipeline_monitoring_contract(tmp_path)
    exit_code = run_module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--target",
            "webinar-orchestrator",
            "--pipeline",
            "--dry-run",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PIPELINE" in output
    assert "PASS" in output
    assert "DRY-RUN" in output
