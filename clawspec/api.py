from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from clawspec.config import ClawspecConfig
from clawspec.coverage.reporter import build_summary
from clawspec.exceptions import ClawspecError
from clawspec.interfaces import OpenClawInterface
from clawspec.models import (
    AssertionResult,
    CheckResult,
    CoverageReport,
    GapItem,
    InitReport,
    RunReport,
    RunSummary,
    ScenarioResult,
    ValidationReport,
)
from clawspec.runner.run import run_contracts
from clawspec.templates.scaffold import scaffold_scenarios
from clawspec.validate.validator import validate_target


def _load_config(
    config: ClawspecConfig | None, *, target: str | Path | None = None
) -> ClawspecConfig:
    if config is not None:
        return config
    start = Path(target).resolve() if target is not None else Path.cwd()
    if start.is_file():
        start = start.parent
    return ClawspecConfig.load(start=start)


def validate(target: str | Path, *, config: ClawspecConfig | None = None) -> ValidationReport:
    _ = _load_config(config, target=target)
    payload = validate_target(target)
    check_results = [
        CheckResult(
            name=str(item["name"]),
            status=str(item["status"]).lower(),
            detail=item.get("detail"),
        )
        for item in payload["checks"]
    ]
    report = ValidationReport(
        target=str(payload["target"]),
        target_type=str(payload["target_type"]),
        passed=str(payload["status"]) == "PASS",
        checks=check_results,
        total_checks=len(check_results),
        passed_checks=sum(1 for item in check_results if item.status == "pass"),
    )
    return report


def run(
    target: str | Path | None = None,
    *,
    gateway: str | None = None,
    scenario: str | None = None,
    tags: list[str] | None = None,
    dry_run: bool = False,
    timeout: int = 60,
    config: ClawspecConfig | None = None,
) -> list[RunReport]:
    active_config = _load_config(config, target=target)
    interface = OpenClawInterface(
        gateway_url=gateway or active_config.gateway_base_url,
        token=active_config.gateway_auth_token,
        webhook_endpoint=active_config.gateway_webhook_endpoint,
        cwd=active_config.root_dir,
    )
    raw_reports = run_contracts(
        target=target,
        scenario=scenario,
        tags=tags,
        dry_run=dry_run,
        timeout=timeout,
        config=active_config,
        interface=interface,
    )
    if not raw_reports:
        raise ClawspecError("No scenarios found")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in raw_reports:
        grouped[str(item["target"])].append(item)

    reports: list[RunReport] = []
    for target_name, scenario_reports in sorted(grouped.items()):
        scenarios = [
            ScenarioResult(
                name=str(item["scenario"]),
                status=str(item["status"]).lower(),
                assertions=[
                    AssertionResult(
                        type=str(assertion.get("name") or assertion.get("type") or "unknown"),
                        status=str(assertion.get("status") or "unknown").lower(),
                        detail=assertion.get("detail"),
                    )
                    for assertion in item.get("assertions", [])
                ],
                duration_ms=0,
                run_number=int(item.get("run") or 0),
                detail=item.get("detail"),
                report_path=item.get("report_path"),
            )
            for item in scenario_reports
        ]
        summary = RunSummary(
            total_scenarios=len(scenarios),
            passed=sum(1 for item in scenarios if item.status == "pass"),
            failed=sum(1 for item in scenarios if item.status == "fail"),
            skipped=sum(1 for item in scenarios if item.status == "skip"),
            warned=sum(1 for item in scenarios if item.status == "warn"),
        )
        exit_code = 1 if summary.failed else 0
        if any(item.status == "error" for item in scenarios):
            exit_code = 2
        reports.append(
            RunReport(
                target=target_name,
                scenarios=scenarios,
                summary=summary,
                exit_code=exit_code,
                report_path=next(
                    (item.report_path for item in scenarios if item.report_path), None
                ),
            )
        )
    return reports


def init(
    target: str | Path | None = None,
    *,
    force: bool = False,
    config: ClawspecConfig | None = None,
) -> InitReport:
    active_target = target or Path.cwd()
    _ = _load_config(config, target=active_target)
    created, resolved_target, target_type, overwritten = scaffold_scenarios(
        active_target, force=force
    )
    return InitReport(
        target=resolved_target,
        target_type=target_type,
        created=str(created),
        overwritten=overwritten,
    )


def coverage(
    ledger_path: str | Path | None = None,
    *,
    report_dir: str | Path | None = None,
    config: ClawspecConfig | None = None,
) -> CoverageReport:
    active_config = _load_config(config)
    active_ledger = ledger_path or active_config.ledger_path
    active_report_dir = report_dir or active_config.report_dir
    summary = build_summary(active_ledger, report_root=active_report_dir)

    gaps: list[GapItem] = []
    for wave in summary["waves"].values():
        for target_id in wave.get("missing_targets", []):
            gaps.append(GapItem(id=target_id, path=target_id, missing=["target_missing"]))
        for scenario_path in wave.get("missing_files", []):
            gaps.append(GapItem(id=scenario_path, path=scenario_path, missing=["scenario_file"]))
        for target_id in wave.get("missing_negative_coverage", []):
            gaps.append(GapItem(id=target_id, path=target_id, missing=["negative_test"]))

    total_items = int(summary["total_items"])
    uncovered_ids = {(item.id, tuple(item.missing)) for item in gaps}
    uncovered = len({item[0] for item in uncovered_ids})
    covered = max(total_items - uncovered, 0)
    report_path = summary.get("report_path")
    return CoverageReport(
        ledger_path=str(active_ledger),
        total_items=total_items,
        covered=covered,
        uncovered=uncovered,
        gaps=gaps,
        coverage_percentage=(covered / total_items * 100.0) if total_items else 0.0,
        report_path=report_path,
    )
