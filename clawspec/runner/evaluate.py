from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from clawspec.assertions import AssertionDispatchError, dispatch_assertion
from clawspec.schema_validator import validate_contract_file
from clawspec.templates.expander import DEFAULT_QA_INBOX, build_template_context, expand_templates

REPORT_DIR = Path("reports")
_RUNTIME_VOLATILITY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("api rate limit reached", "Provider/API rate limit reached during the run."),
    ("rate limit", "Provider/API rate limit reached during the run."),
    ("too many requests", "Provider/API rate limit reached during the run."),
    ("session lock", "Session lock detected during the run."),
    ("lock is held", "Session lock detected during the run."),
    ("gateway error", "Gateway error detected during the run."),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass
class EvaluationOutcome:
    name: str
    status: str
    detail: str | None
    elapsed: str = "0s"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "evaluation"


def _utc_now() -> datetime:
    return datetime.now(UTC).astimezone(UTC).replace(microsecond=0)


def _classify(assertions: list[dict[str, Any]]) -> str:
    statuses = [assertion["status"] for assertion in assertions]
    if "ERROR" in statuses:
        return "ERROR"
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"


def _build_feedback(assertions: list[dict[str, Any]], source_path: Path) -> dict[str, Any] | None:
    actionable = [
        assertion
        for assertion in assertions
        if assertion["status"] in {"FAIL", "WARN"} and assertion.get("detail")
    ]
    if not actionable:
        return None
    structured = [
        {
            "check": assertion["name"],
            "missing": assertion["detail"],
            "fix_action": f"Address {assertion['name']} before the next run.",
            "fix_reference": str(source_path),
        }
        for assertion in actionable
    ]
    checks = ", ".join(assertion["name"] for assertion in actionable)
    return {
        "for_orchestrator": f"Address the failing QA checks: {checks}.",
        "structured": structured,
    }


def _detect_infrastructure_failure(
    assertion_results: list[dict[str, Any]],
    context: dict[str, Any],
    *,
    completed_at: datetime,
) -> str | None:
    runtime_volatility = _detect_runtime_volatility(context, completed_at=completed_at)
    if runtime_volatility is not None:
        return runtime_volatility

    timed_out = any(
        "timed out" in (result.get("detail") or "").casefold() for result in assertion_results
    )
    if not timed_out:
        return None
    health_result = dispatch_assertion({"type": "gateway_healthy"}, context)
    if health_result["status"] != "PASS":
        return "Gateway became unhealthy during a timed-out run."
    return None


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized).astimezone(UTC)
    except ValueError:
        return None


def _detect_runtime_volatility(
    context: dict[str, Any],
    *,
    completed_at: datetime,
) -> str | None:
    gateway_log_path = Path(_default_gateway_log_path(context))
    if not gateway_log_path.exists():
        return None

    started_at = _parse_timestamp(str(context.get("run_started_at") or ""))
    if started_at is None:
        return None
    finished_at = completed_at.astimezone(UTC)

    for raw_line in gateway_log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        timestamp = None
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            payload = None

        if isinstance(payload, dict):
            timestamp = _parse_timestamp(
                str(payload.get("time") or payload.get("_meta", {}).get("date") or "")
            )
        if timestamp is not None and (timestamp < started_at or timestamp > finished_at):
            continue

        haystack = raw_line.casefold()
        for pattern, detail in _RUNTIME_VOLATILITY_PATTERNS:
            if pattern in haystack:
                return detail
    return None


def _resolve_report_dir(report_dir: str | Path | None, *, repo_root: Path | None) -> Path:
    active = Path(report_dir) if report_dir is not None else REPORT_DIR
    if active.is_absolute():
        return active
    if repo_root is not None:
        return (repo_root / active).resolve()
    return active.resolve()


def _write_report(
    report: dict[str, Any],
    *,
    workflow: str,
    scenario: str,
    run_number: int,
    report_dir: str | Path | None,
    repo_root: Path | None,
) -> Path:
    active_report_dir = _resolve_report_dir(report_dir, repo_root=repo_root)
    active_report_dir.mkdir(parents=True, exist_ok=True)
    report_path = active_report_dir / (
        f"{report['completed_at'][:10]}-{_slug(workflow)}-{_slug(scenario)}-r{run_number}.yaml"
    )
    with report_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(report, handle, sort_keys=False)
    return report_path


def _default_gateway_log_path(context: dict[str, Any]) -> str:
    return str(context.get("gateway_log_path", f"/tmp/openclaw/openclaw-{context['today']}.log"))


def _build_default_handoff_assertions(
    contract: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    required_artifacts = contract["callee_produces"]["required_artifacts"]
    prohibited_actions = contract["callee_produces"].get("prohibited_actions", [])
    pre_delegation = [
        {
            "type": "delegation_occurred",
            "from_agent": contract["handoff"]["from"],
            "to_agent": contract["handoff"]["to"],
            "log_path": _default_gateway_log_path(context),
            "run_id": context.get("run_id", ""),
        }
    ]
    post_delegation: list[dict[str, Any]] = []
    for artifact in required_artifacts:
        post_delegation.append(
            {
                "type": "artifact_exists",
                "path": artifact["path_pattern"],
            }
        )
        if artifact.get("required_sections"):
            post_delegation.append(
                {
                    "type": "artifact_contains",
                    "path": artifact["path_pattern"],
                    "sections": artifact["required_sections"],
                }
            )
    for action in prohibited_actions:
        post_delegation.append(
            {
                "type": "tool_not_called",
                "tool": action["tool"],
                "log_path": _default_gateway_log_path(context),
                "run_id": context.get("callee_run_id", ""),
            }
        )
    return {"pre_delegation": pre_delegation, "post_delegation": post_delegation}


def _evaluate_assertions(
    assertions: list[dict[str, Any]], context: dict[str, Any]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for assertion in assertions:
        try:
            result = dispatch_assertion(assertion, context)
        except AssertionDispatchError as exc:
            result = asdict(
                EvaluationOutcome(
                    name=assertion.get("type", "unknown"), status="ERROR", detail=str(exc)
                )
            )
        results.append(result)
    return results


def _workflow_name(kind: str, data: dict[str, Any], source_path: Path) -> str:
    if kind == "scenario":
        return Path(data["target"]["path"]).name
    if kind == "handoff":
        return f"{data['handoff']['from']}-to-{data['handoff']['to']}"
    if kind == "pipeline":
        return data["pipeline"]["name"]
    return source_path.stem


def evaluate_contract(
    contract_path: str | Path,
    *,
    run_number: int = 1,
    scenario_name: str | None = None,
    extra_context: dict[str, Any] | None = None,
    report_dir: str | Path | None = None,
    repo_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    source_path = Path(contract_path)
    validation = validate_contract_file(source_path)
    if not validation.valid:
        raise ValueError(validation.errors[0].message)

    started_at = _utc_now()
    active_repo_root = Path(repo_root).resolve() if repo_root is not None else _repo_root()
    default_context = {
        "run_id": "",
        "callee_run_id": "",
        "gateway_log_path": f"/tmp/openclaw/openclaw-{started_at.date().isoformat()}.log",
        "run_started_at": started_at.isoformat().replace("+00:00", "Z"),
    }
    if extra_context:
        default_context.update(extra_context)
    base_context = build_template_context(
        repo_root=active_repo_root,
        now=started_at,
        qa_inbox=DEFAULT_QA_INBOX,
        extra=default_context,
    )
    if validation.kind == "handoff":
        handoff = validation.data["handoff"]
        base_context = {
            **base_context,
            "handoff.from": handoff["from"],
            "handoff.to": handoff["to"],
        }
    expanded = expand_templates(validation.data, base_context)
    workflow = _workflow_name(validation.kind, expanded, source_path)
    reports: list[dict[str, Any]] = []

    if validation.kind == "scenario":
        scenarios = expanded["scenarios"]
        if scenario_name is not None:
            scenarios = [item for item in scenarios if item["name"] == scenario_name]
        for scenario in scenarios:
            assertion_results = _evaluate_assertions(
                scenario.get("then", []),
                {"workflow": workflow, "scenario": scenario["name"], **base_context},
            )
            completed_at = _utc_now()
            infrastructure_failure = _detect_infrastructure_failure(
                assertion_results,
                {"workflow": workflow, "scenario": scenario["name"], **base_context},
                completed_at=completed_at,
            )
            report = {
                "workflow": workflow,
                "scenario": scenario["name"],
                "run": run_number,
                "status": "ERROR" if infrastructure_failure else _classify(assertion_results),
                "started_at": started_at.isoformat().replace("+00:00", "Z"),
                "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
                "assertions": assertion_results,
                "detail": infrastructure_failure,
                "feedback": _build_feedback(assertion_results, source_path),
                "infrastructure_failure": infrastructure_failure is not None,
            }
            report["report_path"] = str(
                _write_report(
                    report,
                    workflow=workflow,
                    scenario=scenario["name"],
                    run_number=run_number,
                    report_dir=report_dir,
                    repo_root=active_repo_root,
                )
            )
            reports.append(report)
        return reports

    contract_name = source_path.stem
    assertion_blocks: list[dict[str, Any]] = []
    if validation.kind == "handoff":
        assertions = expanded.get("assertions") or _build_default_handoff_assertions(
            expanded, base_context
        )
        assertion_blocks = assertions.get("pre_delegation", []) + assertions.get(
            "post_delegation", []
        )
    elif validation.kind == "pipeline":
        final_assertions = expanded.get("final_assertions", {})
        assertion_blocks = final_assertions.get("deterministic", []) + final_assertions.get(
            "semantic", []
        )

    context = {"workflow": workflow, "scenario": contract_name, **base_context}
    assertion_results = _evaluate_assertions(assertion_blocks, context)
    completed_at = _utc_now()
    infrastructure_failure = _detect_infrastructure_failure(
        assertion_results,
        context,
        completed_at=completed_at,
    )
    report = {
        "workflow": workflow,
        "scenario": contract_name,
        "run": run_number,
        "status": "ERROR" if infrastructure_failure else _classify(assertion_results),
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        "assertions": assertion_results,
        "detail": infrastructure_failure,
        "feedback": _build_feedback(assertion_results, source_path),
        "infrastructure_failure": infrastructure_failure is not None,
    }
    report["report_path"] = str(
        _write_report(
            report,
            workflow=workflow,
            scenario=contract_name,
            run_number=run_number,
            report_dir=report_dir,
            repo_root=active_repo_root,
        )
    )
    return [report]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate QA contracts against existing artifacts."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scenario-file")
    group.add_argument("--handoff")
    group.add_argument("--pipeline")
    parser.add_argument("--scenario-name")
    parser.add_argument("--run-number", type=int, default=1)
    parser.add_argument("--report-dir")
    parser.add_argument("--repo-root")
    parser.add_argument(
        "--evaluate-only",
        action="store_true",
        help="Accepted for CLI compatibility; evaluation mode is the default behavior.",
    )
    args = parser.parse_args(argv)

    contract_path = args.scenario_file or args.handoff or args.pipeline
    validation = validate_contract_file(contract_path)
    if not validation.valid:
        payload = validation.to_dict()
        print(yaml.safe_dump(payload, sort_keys=False))
        return 3

    try:
        reports = evaluate_contract(
            contract_path,
            run_number=args.run_number,
            scenario_name=args.scenario_name,
            report_dir=args.report_dir,
            repo_root=args.repo_root,
        )
    except Exception as exc:
        print(
            yaml.safe_dump(
                {"status": "ERROR", "detail": str(exc), "contract_path": contract_path},
                sort_keys=False,
            )
        )
        return 2

    print(yaml.safe_dump(reports, sort_keys=False))
    statuses = [report["status"] for report in reports]
    if any(status == "FAIL" for status in statuses):
        return 1
    if any(status == "ERROR" for status in statuses):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
