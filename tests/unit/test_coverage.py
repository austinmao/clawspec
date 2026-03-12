from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from clawspec.coverage.reporter import build_summary, find_contract_gaps, load_ledger, main

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "coverage"


def _copy_ledger_fixture(tmp_path: Path) -> Path:
    ledger_path = tmp_path / "docs" / "testing" / "coverage-ledger.yaml"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE_ROOT / "coverage-ledger.yaml", ledger_path)
    return ledger_path


def _write_yaml(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _seed_contract_files(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "skills" / "newsletter" / "tests" / "scenarios.yaml",
        {
            "version": "1.0",
            "target": {"type": "skill", "path": "skills/newsletter", "trigger": "/send-newsletter"},
            "scenarios": [
                {
                    "name": "sunday-service-smoke",
                    "tags": ["smoke"],
                    "when": {"invoke": "/send-newsletter"},
                    "then": [{"type": "artifact_exists", "path": "memory/drafts/out.md"}],
                },
                {
                    "name": "rejects-out-of-scope",
                    "tags": ["negative"],
                    "when": {"invoke": "/send-newsletter bad"},
                    "then": [{"type": "tool_not_called", "tool": "resend.send"}],
                },
            ],
        },
    )
    _write_yaml(
        tmp_path / "skills" / "newsletter" / "tests" / "pipeline.yaml",
        {
            "version": "1.0",
            "pipeline": {
                "name": "newsletter",
                "skill_path": "skills/newsletter",
                "trigger": "/send-newsletter",
                "stages": 1,
            },
            "stages": [{"name": "draft"}],
        },
    )
    _write_yaml(
        tmp_path / "skills" / "newsletter" / "tests" / "handoffs" / "newsletter-to-segment.yaml",
        {
            "version": "1.0",
            "handoff": {
                "from": "skills-newsletter",
                "to": "agents-marketing-email",
                "mechanism": "sessions_spawn",
            },
            "caller_provides": {"required_context": [{"name": "topic", "description": "topic"}]},
            "callee_produces": {
                "required_artifacts": [
                    {"path_pattern": "memory/segments/out.yaml", "description": "segment"}
                ]
            },
        },
    )
    _write_yaml(
        tmp_path / "agents" / "marketing" / "email" / "tests" / "scenarios.yaml",
        {
            "version": "1.0",
            "target": {
                "type": "agent",
                "path": "agents/marketing/email",
                "trigger": 'sessions_spawn(agentId: "agents-marketing-email")',
            },
            "scenarios": [
                {
                    "name": "email-agent-smoke",
                    "tags": ["smoke"],
                    "when": {"invoke": "draft"},
                    "then": [{"type": "artifact_exists", "path": "memory/drafts/out.md"}],
                },
                {
                    "name": "email-agent-negative",
                    "tags": ["negative"],
                    "when": {"invoke": "send"},
                    "then": [{"type": "tool_not_called", "tool": "resend.send"}],
                },
            ],
        },
    )
    report_dir = tmp_path / "memory" / "logs" / "qa"
    report_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        FIXTURE_ROOT / "reports" / "2026-03-11-newsletter-smoke-r1.yaml",
        report_dir / "2026-03-11-newsletter-smoke-r1.yaml",
    )


def test_load_ledger_returns_wave_mapping(tmp_path: Path) -> None:
    ledger_path = _copy_ledger_fixture(tmp_path)

    payload = load_ledger(ledger_path)

    assert set(payload["waves"]) == {"marketing-core", "ops-core"}
    assert len(payload["waves"]["marketing-core"]["items"]) == 4


def test_find_contract_gaps_reports_missing_contracts_and_orchestrator_gaps(tmp_path: Path) -> None:
    ledger_path = _copy_ledger_fixture(tmp_path)
    _seed_contract_files(tmp_path)
    payload = load_ledger(ledger_path)
    analytics_entry = payload["waves"]["marketing-core"]["items"][1]
    orchestrator_entry = payload["waves"]["marketing-core"]["items"][2]

    analytics_gaps = find_contract_gaps(analytics_entry, repo_root=tmp_path)
    orchestrator_gaps = find_contract_gaps(orchestrator_entry, repo_root=tmp_path)

    assert analytics_gaps["missing_files"] == [
        "skills/newsletter/sub-skills/analytics/tests/scenarios.yaml"
    ]
    assert analytics_gaps["missing_negative_coverage"] is True
    assert orchestrator_gaps["orchestrator_missing_pipeline"] is True
    assert orchestrator_gaps["orchestrator_missing_handoffs"] is True


def test_build_summary_counts_by_status_and_wave(tmp_path: Path) -> None:
    ledger_path = _copy_ledger_fixture(tmp_path)
    _seed_contract_files(tmp_path)

    summary = build_summary(
        ledger_path, report_root=tmp_path / "memory" / "logs" / "qa", date="2026-03-11"
    )

    assert summary["counts_by_wave"] == {"marketing-core": 4, "ops-core": 1}
    assert summary["waves"]["marketing-core"]["counts_by_status"]["uncovered"] == 2
    assert summary["waves"]["marketing-core"]["counts_by_status"]["authored"] == 1
    assert summary["waves"]["marketing-core"]["counts_by_status"]["live-pass"] == 1
    assert summary["waves"]["marketing-core"]["counts_by_tier"]["orchestrator"] == 2
    assert summary["waves"]["marketing-core"]["recent_report_count"] == 1


def test_build_summary_collects_missing_files_and_coverage_gaps(tmp_path: Path) -> None:
    ledger_path = _copy_ledger_fixture(tmp_path)
    _seed_contract_files(tmp_path)

    summary = build_summary(
        ledger_path, report_root=tmp_path / "memory" / "logs" / "qa", date="2026-03-11"
    )
    marketing = summary["waves"]["marketing-core"]

    assert (
        "skills/newsletter/sub-skills/analytics/tests/scenarios.yaml" in marketing["missing_files"]
    )
    assert marketing["missing_negative_coverage"] == [
        "skills/newsletter/sub-skills/analytics",
        "skills/ops-triage",
    ] or marketing["missing_negative_coverage"] == ["skills/newsletter/sub-skills/analytics"]
    assert marketing["orchestrators_missing_pipeline"] == ["skills/campaign-workflow"]
    assert marketing["orchestrators_missing_handoffs"] == ["skills/campaign-workflow"]


def test_main_writes_json_summary_file(tmp_path: Path, monkeypatch, capsys) -> None:
    ledger_path = _copy_ledger_fixture(tmp_path)
    _seed_contract_files(tmp_path)
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "--ledger",
            str(ledger_path),
            "--wave",
            "marketing-core",
            "--date",
            "2026-03-11",
            "--write-json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    written = tmp_path / "memory" / "logs" / "qa" / "coverage-summary.json"

    assert exit_code == 0
    assert payload["selected_wave"] == "marketing-core"
    assert written.exists()
    written_payload = json.loads(written.read_text(encoding="utf-8"))
    assert written_payload["selected_wave"] == "marketing-core"
