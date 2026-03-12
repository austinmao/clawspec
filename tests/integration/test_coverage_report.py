from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from clawspec.coverage.reporter import build_summary, main

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "coverage"


def _write_yaml(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _seed_repo(tmp_path: Path) -> Path:
    ledger_path = tmp_path / "coverage-ledger.yaml"
    shutil.copyfile(FIXTURE_ROOT / "coverage-ledger.yaml", ledger_path)
    _write_yaml(
        tmp_path / "skills" / "newsletter" / "tests" / "scenarios.yaml",
        {
            "version": "1.0",
            "target": {"type": "skill", "path": "skills/newsletter", "trigger": "/send-newsletter"},
            "scenarios": [
                {
                    "name": "smoke",
                    "tags": ["smoke"],
                    "when": {"invoke": "/send-newsletter"},
                    "then": [{"type": "artifact_exists", "path": "memory/drafts/out.md"}],
                },
                {
                    "name": "negative",
                    "tags": ["negative"],
                    "when": {"invoke": "/send-newsletter forbidden"},
                    "then": [{"type": "tool_not_called", "tool": "resend.send"}],
                },
            ],
        },
    )
    _write_yaml(
        tmp_path / "agents" / "marketing" / "email" / "tests" / "scenarios.yaml",
        {
            "version": "1.0",
            "target": {
                "type": "agent",
                "path": "agents/marketing/email",
                "trigger": "agents-marketing-email",
            },
            "scenarios": [
                {
                    "name": "smoke",
                    "tags": ["smoke"],
                    "when": {"invoke": "draft"},
                    "then": [{"type": "artifact_exists", "path": "memory/drafts/out.md"}],
                },
                {
                    "name": "negative",
                    "tags": ["negative"],
                    "when": {"invoke": "send"},
                    "then": [{"type": "tool_not_called", "tool": "resend.send"}],
                },
            ],
        },
    )
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        FIXTURE_ROOT / "reports" / "2026-03-11-newsletter-smoke-r1.yaml",
        report_dir / "2026-03-11-newsletter-smoke-r1.yaml",
    )
    return ledger_path


def test_build_summary_reports_generic_gaps(tmp_path: Path) -> None:
    ledger_path = _seed_repo(tmp_path)

    summary = build_summary(ledger_path, report_root=tmp_path / "reports", date="2026-03-11")

    assert summary["counts_by_wave"] == {"marketing-core": 4, "ops-core": 1}
    assert "skills/newsletter/sub-skills/analytics/tests/scenarios.yaml" in summary["missing_files"]
    assert "skills/newsletter/sub-skills/analytics" in summary["missing_negative_coverage"]
    assert "skills/campaign-workflow" in summary["orchestrators_missing_pipeline"]


def test_coverage_main_writes_json_report(tmp_path: Path, monkeypatch, capsys) -> None:
    ledger_path = _seed_repo(tmp_path)
    report_root = tmp_path / "reports"
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "--ledger",
            str(ledger_path),
            "--wave",
            "marketing-core",
            "--date",
            "2026-03-11",
            "--report-root",
            str(report_root),
            "--write-json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["selected_wave"] == "marketing-core"
    assert (report_root / "coverage-summary.json").exists()
