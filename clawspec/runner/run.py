from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import yaml

from clawspec.assertions import AssertionDispatchError, dispatch_assertion
from clawspec.config import ClawspecConfig
from clawspec.exceptions import SchemaError
from clawspec.interfaces import AgentInterface, OpenClawInterface
from clawspec.runner.discover import discover_scenarios
from clawspec.runner.evaluate import evaluate_contract
from clawspec.schema_validator import validate_contract_file
from clawspec.templates.expander import build_template_context, expand_templates
from clawspec.validate.validator import validate_target

GATEWAY_BASE = "http://127.0.0.1:18789"
DEFAULT_TRIGGER_TIMEOUT = 60


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_timestamp(value: datetime | None = None) -> str:
    return (
        (value or _utc_now())
        .astimezone(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "run"


def _load_yaml(path: str | Path) -> dict[str, Any]:
    loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a top-level mapping")
    return loaded


def _scenario_lookup(scenario_file: str | Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    contract = _load_yaml(scenario_file)
    scenarios = contract.get("scenarios", [])
    if not isinstance(scenarios, list):
        raise ValueError(f"{scenario_file} is missing a scenarios list")
    mapping = {
        str(item.get("name")): item
        for item in scenarios
        if isinstance(item, dict) and item.get("name")
    }
    return contract, mapping


def _contract_defaults(contract: dict[str, Any]) -> dict[str, Any]:
    defaults = contract.get("defaults", {})
    return defaults if isinstance(defaults, dict) else {}


def _effective_trigger_timeout(
    *,
    contract: dict[str, Any],
    cli_timeout: int | None,
) -> int:
    if cli_timeout is not None:
        return int(cli_timeout)

    contract_timeout = _contract_defaults(contract).get("timeout")
    if contract_timeout is not None:
        return int(contract_timeout)
    return DEFAULT_TRIGGER_TIMEOUT


def _resolve_target_file(repo_root: Path, *, target_type: str, target_path: str) -> Path:
    file_name = "SKILL.md" if target_type == "skill" else "SOUL.md"
    return repo_root / target_path / file_name


def _skill_target_metadata(entry: dict[str, Any], *, invoke: str) -> dict[str, str]:
    trigger = str(entry.get("trigger") or invoke).strip()
    command = trigger.split()[0] if trigger else ""
    skill_name = command[1:] if command.startswith("/") else command
    metadata = {
        "target_path": str(entry.get("target_path") or "").strip(),
        "target_type": str(entry.get("target_type") or "").strip(),
        "target_skill_name": skill_name.strip(),
    }
    return {key: value for key, value in metadata.items() if value}


def _target_label(entry: dict[str, Any]) -> str:
    return (
        entry.get("target_path") or entry.get("target_name") or entry.get("target_type") or "target"
    )


def _resolve_report_dir(path: str | Path, *, repo_root: Path) -> Path:
    target = Path(path)
    return target if target.is_absolute() else (repo_root / target).resolve()


def _next_run_number(
    report_dir: str | Path, *, workflow: str, scenario: str, repo_root: Path
) -> int:
    active_report_dir = _resolve_report_dir(report_dir, repo_root=repo_root)
    if not active_report_dir.exists():
        return 1
    pattern = f"*-{_slug(workflow)}-{_slug(scenario)}-r*.yaml"
    existing = list(active_report_dir.glob(pattern))
    if not existing:
        return 1

    run_numbers: list[int] = []
    for report in existing:
        match = re.search(r"-r(\d+)\.yaml$", report.name)
        if match:
            run_numbers.append(int(match.group(1)))
    return max(run_numbers, default=0) + 1


def _evaluate_preconditions(
    scenario: dict[str, Any],
    *,
    repo_root: Path,
    run_id: str,
    gateway_log_path: str,
    run_started_at: str,
) -> list[dict[str, Any]]:
    context = build_template_context(
        repo_root=repo_root,
        now=_utc_now(),
        extra={
            "run_id": run_id,
            "gateway_log_path": gateway_log_path,
            "run_started_at": run_started_at,
        },
    )
    expanded = expand_templates(scenario.get("given", []), context)
    results: list[dict[str, Any]] = []
    for assertion in expanded:
        try:
            result = dispatch_assertion(assertion, context)
        except AssertionDispatchError as exc:
            result = {
                "name": assertion.get("type", "unknown"),
                "status": "ERROR",
                "detail": str(exc),
                "elapsed": "0s",
            }
        results.append(result)
    return results


def _preconditions_passed(results: list[dict[str, Any]]) -> bool:
    return all(item.get("status") == "PASS" for item in results)


def _negative_coverage_errors(
    discovered: list[dict[str, Any]],
    *,
    target_paths: set[str],
) -> list[str]:
    by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in discovered:
        if entry["target_path"] in target_paths:
            by_target[entry["target_path"]].append(entry)

    missing: list[str] = []
    for target_path in sorted(target_paths):
        scenarios = by_target.get(target_path, [])
        if not any("negative" in item.get("tags", []) for item in scenarios):
            missing.append(target_path)
    return missing


def _hooks_token(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    return os.environ.get("HOOKS_TOKEN") or os.environ.get("OPENCLAW_HOOKS_TOKEN")


def _expand_scenario_for_execution(
    scenario: dict[str, Any],
    *,
    repo_root: Path,
    run_id: str,
    gateway_log_path: str,
    run_started_at: str,
) -> dict[str, Any]:
    context = build_template_context(
        repo_root=repo_root,
        now=_utc_now(),
        extra={
            "run_id": run_id,
            "gateway_log_path": gateway_log_path,
            "run_started_at": run_started_at,
        },
    )
    expanded = expand_templates(scenario, context)
    if not isinstance(expanded, dict):
        raise ValueError(f"Expanded scenario must remain a mapping: {scenario.get('name')}")
    return expanded


def _registered_agents(interface: AgentInterface | None = None) -> tuple[dict[str, Any], ...]:
    if interface is not None:
        payload = interface.list_agents()
    else:
        command = ["openclaw", "agents", "list", "--json"]
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout or "[]")
    if not isinstance(payload, list):
        raise ValueError("openclaw agents list --json must return a list")
    return tuple(item for item in payload if isinstance(item, dict))


def _registered_agents_with_profile(openclaw_profile: str) -> tuple[dict[str, Any], ...]:
    result = subprocess.run(
        [*_openclaw_cli_prefix(openclaw_profile), "agents", "list", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout or "[]")
    if not isinstance(payload, list):
        raise ValueError("openclaw agents list --json must return a list")
    return tuple(item for item in payload if isinstance(item, dict))


def _openclaw_cli_prefix(openclaw_profile: str | None) -> list[str]:
    command = ["openclaw"]
    if openclaw_profile:
        command.extend(["--profile", openclaw_profile])
    return command


def _effective_openclaw_profile(
    *,
    interface: AgentInterface | None,
    openclaw_profile: str | None,
) -> str | None:
    if openclaw_profile:
        return openclaw_profile
    if isinstance(interface, OpenClawInterface):
        return interface.openclaw_profile
    return None


def _configured_gateway_workspace(
    *,
    repo_root: Path,
    openclaw_profile: str | None = None,
) -> Path | None:
    result = subprocess.run(
        [
            *_openclaw_cli_prefix(openclaw_profile),
            "config",
            "get",
            "agents.defaults.workspace",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    if not value:
        return None
    return Path(value).expanduser().resolve()


def _using_local_default_gateway(
    *,
    gateway_base: str,
    openclaw_profile: str | None,
) -> bool:
    return (
        gateway_base.rstrip("/") == str(GATEWAY_BASE).rstrip("/")
        or openclaw_profile is not None
    )


def _gateway_workspace_mismatch(
    *,
    repo_root: Path,
    gateway_base: str,
    interface: AgentInterface | None = None,
    openclaw_profile: str | None = None,
) -> str | None:
    active_profile = _effective_openclaw_profile(
        interface=interface,
        openclaw_profile=openclaw_profile,
    )
    if not _using_local_default_gateway(
        gateway_base=gateway_base,
        openclaw_profile=active_profile,
    ):
        return None

    configured = _configured_gateway_workspace(
        repo_root=repo_root,
        openclaw_profile=active_profile,
    )
    expected = repo_root.resolve()
    if configured is None:
        return (
            "Could not determine the configured OpenClaw workspace from "
            "`openclaw config get agents.defaults.workspace`."
        )
    if configured != expected:
        return (
            f"Gateway workspace mismatch: configured workspace {configured} does not match "
            f"repo root {expected}. Start or point OpenClaw at the correct workspace before "
            "running QA scenarios."
        )
    return None


def _agent_id_from_trigger(trigger: str) -> str | None:
    match = re.search(r'agentId:\s*["\']?([^,"\')]+)', trigger)
    if match:
        return match.group(1).strip()
    return None


def _resolve_agent_id(
    entry: dict[str, Any],
    *,
    repo_root: Path,
    interface: AgentInterface | None = None,
    openclaw_profile: str | None = None,
) -> str:
    workspace = str((repo_root / entry["target_path"]).resolve())
    try:
        if interface is None and openclaw_profile is None:
            registry = _registered_agents()
        elif interface is None:
            registry = _registered_agents_with_profile(openclaw_profile)
        else:
            registry = _registered_agents(interface)
        matches = [
            str(item.get("id", "")).strip()
            for item in registry
            if str(item.get("workspace", "")).strip() == workspace
        ]
    except Exception:
        matches = []

    if len(matches) == 1 and matches[0]:
        return matches[0]

    trigger = str(entry.get("trigger", "")).strip()
    parsed = _agent_id_from_trigger(trigger)
    if parsed:
        return parsed
    if trigger:
        return trigger
    raise ValueError(f"Unable to resolve agent id for {entry.get('target_path')}")


def _agent_registration_mismatch(
    entry: dict[str, Any],
    *,
    repo_root: Path,
    gateway_base: str,
    interface: AgentInterface | None = None,
    openclaw_profile: str | None = None,
) -> str | None:
    if entry.get("target_type") != "agent":
        return None
    active_profile = _effective_openclaw_profile(
        interface=interface,
        openclaw_profile=openclaw_profile,
    )
    if not _using_local_default_gateway(
        gateway_base=gateway_base,
        openclaw_profile=active_profile,
    ):
        return None

    expected_workspace = str((repo_root / entry["target_path"]).resolve())
    try:
        if interface is None and active_profile is None:
            registry = _registered_agents()
        elif interface is None:
            registry = _registered_agents_with_profile(active_profile)
        else:
            registry = _registered_agents(interface)
        matches = [
            str(item.get("id", "")).strip()
            for item in registry
            if str(item.get("workspace", "")).strip() == expected_workspace
        ]
    except Exception as exc:
        return f"Could not inspect registered OpenClaw agents: {exc}"

    if matches:
        return None

    configured = _configured_gateway_workspace(
        repo_root=repo_root,
        openclaw_profile=active_profile,
    )
    configured_text = str(configured) if configured is not None else "unknown"
    trigger = str(entry.get("trigger", "")).strip() or "<missing trigger>"
    return (
        f"No registered OpenClaw agent matches workspace {expected_workspace} "
        f"(trigger {trigger}). Configured gateway workspace: {configured_text}."
    )


def _agent_message(scenario: dict[str, Any]) -> str:
    when = scenario.get("when", {}) if isinstance(scenario.get("when"), dict) else {}
    invoke = str(when.get("invoke", "")).strip()
    params = when.get("params", {}) if isinstance(when.get("params"), dict) else {}
    if invoke == "sessions_spawn":
        task = str(params.get("task", "")).strip()
        if not task:
            raise ValueError(f"Scenario {scenario.get('name')} is missing when.params.task")
        return task
    if invoke:
        return invoke
    raise ValueError(f"Scenario {scenario.get('name')} is missing when.invoke")


def _parse_json_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {}
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < start:
            raise
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Expected JSON object payload")
    return payload


def _trigger_agent_scenario(
    entry: dict[str, Any],
    scenario: dict[str, Any],
    *,
    repo_root: Path,
    interface: AgentInterface | None = None,
    openclaw_profile: str | None = None,
    timeout: int = DEFAULT_TRIGGER_TIMEOUT,
) -> dict[str, Any]:
    agent_id = _resolve_agent_id(
        entry,
        repo_root=repo_root,
        interface=interface,
        openclaw_profile=openclaw_profile,
    )
    message = _agent_message(scenario)

    if interface is not None:
        return interface.invoke(
            agent_id,
            message,
            timeout=timeout,
            target_type="agent",
            repo_root=repo_root,
        )

    result = subprocess.run(
        [
            *_openclaw_cli_prefix(openclaw_profile),
            "agent",
            "--local",
            "--agent",
            agent_id,
            "--message",
            message,
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        timeout=timeout,
    )
    payload = _parse_json_payload(result.stdout or "{}")
    run_id = (
        payload.get("meta", {}).get("agentMeta", {}).get("sessionId")
        if isinstance(payload.get("meta"), dict)
        else None
    )
    return {
        "status": "completed",
        "run_id": run_id or str(uuid4()),
        "response": payload,
    }


def _trigger_scenario(
    entry: dict[str, Any],
    scenario: dict[str, Any],
    *,
    repo_root: Path,
    gateway_base: str,
    hooks_token: str | None,
    requested_session_key: str | None = None,
    interface: AgentInterface | None = None,
    openclaw_profile: str | None = None,
    timeout: int = DEFAULT_TRIGGER_TIMEOUT,
) -> dict[str, Any]:
    mismatch = _gateway_workspace_mismatch(
        repo_root=repo_root,
        gateway_base=gateway_base,
        interface=interface,
        openclaw_profile=openclaw_profile,
    )
    if mismatch:
        raise RuntimeError(mismatch)

    agent_mismatch = _agent_registration_mismatch(
        entry,
        repo_root=repo_root,
        gateway_base=gateway_base,
        interface=interface,
        openclaw_profile=openclaw_profile,
    )
    if agent_mismatch:
        raise RuntimeError(agent_mismatch)

    if entry.get("target_type") == "agent":
        return _trigger_agent_scenario(
            entry,
            scenario,
            repo_root=repo_root,
            interface=interface,
            openclaw_profile=openclaw_profile,
            timeout=timeout,
        )

    invoke = str(scenario.get("when", {}).get("invoke", "")).strip()
    params = scenario.get("when", {}).get("params", {}) or {}
    if not invoke:
        raise ValueError(f"Scenario {scenario.get('name')} is missing when.invoke")

    target_metadata = _skill_target_metadata(entry, invoke=invoke)
    if interface is not None:
        return interface.invoke(
            str(entry.get("trigger") or invoke),
            invoke,
            timeout=timeout,
            target_type="skill",
            params=params,
            trigger=str(entry.get("trigger") or invoke),
            requested_session_key=requested_session_key,
            repo_root=repo_root,
            target_path=target_metadata.get("target_path"),
            target_skill_name=target_metadata.get("target_skill_name"),
        )

    headers = {"Content-Type": "application/json"}
    if hooks_token:
        headers["Authorization"] = f"Bearer {hooks_token}"

    endpoint = f"{gateway_base}/webhook/mcp-skill-invoke"
    if invoke.startswith("/"):
        body = {
            "skill_command": invoke,
            "payload": json.dumps(params, sort_keys=True) if params else "",
            "test_mode": bool(params.get("test_mode", True)),
        }
    else:
        body = {
            "skill_command": entry.get("trigger") or invoke,
            "payload": json.dumps(
                {
                    "invoke": invoke,
                    "params": params,
                    "target": entry.get("target_path"),
                    "target_type": entry.get("target_type"),
                },
                sort_keys=True,
            ),
            "test_mode": bool(params.get("test_mode", True)),
        }
    body.update(target_metadata)
    if requested_session_key:
        body["session_key"] = requested_session_key

    response = httpx.post(endpoint, headers=headers, json=body, timeout=float(timeout))
    response.raise_for_status()
    payload = response.json() if response.content else {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "status": payload.get("status", "accepted"),
        "run_id": payload.get("runId") or payload.get("run_id") or str(uuid4()),
        "response": payload,
    }


def _result_bucket(report: dict[str, Any]) -> str:
    if report.get("infrastructure_failure") or report.get("status") == "ERROR":
        return "INFRASTRUCTURE"
    if report.get("status") == "FAIL":
        return "FAIL"
    if report.get("status") == "WARN":
        return "WARN"
    return "PASS"


def _synthetic_report(
    *,
    entry: dict[str, Any],
    scenario_name: str,
    mode: str,
    status: str,
    detail: str,
    assertions: list[dict[str, Any]] | None = None,
    infrastructure_failure: bool = False,
    repo_root: Path | None = None,
    report_dir: str | Path | None = None,
    run_number: int | None = None,
) -> dict[str, Any]:
    completed_at = _iso_timestamp()
    report = {
        "target": entry["target_path"],
        "workflow": Path(entry["target_path"]).name,
        "scenario": scenario_name,
        "run": 0,
        "status": status,
        "detail": detail,
        "report_path": None,
        "infrastructure_failure": infrastructure_failure,
        "assertions": assertions or [],
        "mode": mode,
        "started_at": completed_at,
        "completed_at": completed_at,
    }
    if repo_root is None or report_dir is None or mode == "DRY-RUN":
        return report

    report["run"] = run_number or _next_run_number(
        report_dir,
        workflow=report["workflow"],
        scenario=scenario_name,
        repo_root=repo_root,
    )
    active_report_dir = _resolve_report_dir(report_dir, repo_root=repo_root)
    active_report_dir.mkdir(parents=True, exist_ok=True)
    report_path = active_report_dir / (
        f"{completed_at[:10]}-{_slug(report['workflow'])}-{_slug(scenario_name)}-r{report['run']}.yaml"
    )
    report["report_path"] = str(report_path)
    with report_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(report, handle, sort_keys=False)
    return report


def _resolve_pipeline_relative_path(
    contract_path: Path,
    *,
    skill_path: str,
    relative_path: str,
) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute():
        return relative

    expected_suffix = Path(skill_path) / "tests" / contract_path.name
    for ancestor in contract_path.parents:
        if ancestor / expected_suffix == contract_path:
            return ancestor / skill_path / relative

    if contract_path.parent.name == "tests":
        return contract_path.parent.parent / relative
    return contract_path.parent / relative


def _expand_path_pattern(
    value: str,
    *,
    repo_root: Path,
    now: datetime,
    extra: dict[str, Any] | None = None,
) -> str:
    context = build_template_context(repo_root=repo_root, now=now, extra=extra or {})
    expanded = expand_templates(value, context)
    if isinstance(expanded, str) and not Path(expanded).is_absolute():
        return str(repo_root / expanded)
    return str(expanded)


def _artifact_matches(
    pattern: str,
    *,
    repo_root: Path,
    now: datetime,
    extra: dict[str, Any] | None = None,
) -> list[Path]:
    expanded = _expand_path_pattern(pattern, repo_root=repo_root, now=now, extra=extra)
    return sorted(Path(path) for path in glob.glob(expanded))


def _parse_duration_literal(value: str) -> int:
    literal = value.strip().lower()
    match = re.fullmatch(r"(\d+)([mh])", literal)
    if not match:
        raise ValueError(f"Unsupported duration literal: {value}")
    amount = int(match.group(1))
    unit = match.group(2)
    return amount * 60 if unit == "m" else amount * 3600


def _handoff_passed(report: dict[str, Any]) -> bool:
    if report.get("infrastructure_failure"):
        return False
    return str(report.get("status")) in {"PASS", "WARN"}


def _classify_assertions(assertions: list[dict[str, Any]]) -> str:
    statuses = [str(assertion.get("status")) for assertion in assertions]
    if "ERROR" in statuses:
        return "ERROR"
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"


def _monitor_pipeline_stages(
    *,
    contract: dict[str, Any],
    repo_root: Path,
    now: datetime,
    evaluate_handoff,
    run_id: str = "",
    contract_path: Path | None = None,
) -> dict[str, Any]:
    stages = contract.get("stages", []) if isinstance(contract.get("stages"), list) else []
    pipeline = contract.get("pipeline", {}) if isinstance(contract.get("pipeline"), dict) else {}
    skill_path = str(pipeline.get("skill_path", "")).strip()

    stage_results: list[dict[str, Any]] = []
    handoff_reports: list[dict[str, Any]] = []
    produced_artifacts = 0
    stages_with_produces = 0

    for stage in stages:
        if not isinstance(stage, dict):
            continue
        produces = str(stage.get("produces", "")).strip()
        requires_approval = bool(stage.get("requires_approval", False))
        artifacts: list[str] = []
        produced = False
        skipped = False
        if produces:
            stages_with_produces += 1
            matches = _artifact_matches(produces, repo_root=repo_root, now=now)
            artifacts = [str(path) for path in matches]
            produced = bool(matches)
            if produced:
                produced_artifacts += 1
            elif not requires_approval:
                skipped = True

        handoff_ref = str(stage.get("handoff_contract", "")).strip()
        handoff_report = None
        if handoff_ref and contract_path is not None and (produced or not produces):
            handoff_path = _resolve_pipeline_relative_path(
                contract_path,
                skill_path=skill_path,
                relative_path=handoff_ref,
            )
            handoff_report = evaluate_handoff(handoff_path, run_id)
            handoff_reports.append(handoff_report)

        stage_results.append(
            {
                "name": stage.get("name"),
                "agent": stage.get("agent"),
                "produces": produces or None,
                "artifacts": artifacts,
                "produced": produced,
                "requires_approval": requires_approval,
                "skipped": skipped,
                "handoff_contract": handoff_ref or None,
                "handoff_status": handoff_report.get("status")
                if isinstance(handoff_report, dict)
                else None,
            }
        )

    return {
        "stages": stage_results,
        "produced_artifacts": produced_artifacts,
        "stages_with_produces": stages_with_produces,
        "handoff_reports": handoff_reports,
    }


def _evaluate_pipeline_health(
    checks: list[dict[str, Any]],
    *,
    state: dict[str, Any],
    elapsed_seconds: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    produced_artifacts = int(state.get("produced_artifacts", 0))
    stages_with_produces = int(state.get("stages_with_produces", 0))
    handoff_reports = state.get("handoff_reports", []) or []

    for check in checks:
        description = str(check.get("description", "pipeline health")).strip() or "pipeline health"
        expression = str(check.get("check", "")).strip()
        status = "PASS"
        detail = None
        try:
            if expression == "count(produced_artifacts) == count(stages_with_produces)":
                passed = produced_artifacts == stages_with_produces
                if not passed:
                    status = "FAIL"
                    detail = (
                        "count(produced_artifacts) == count(stages_with_produces) failed: "
                        f"{produced_artifacts} != {stages_with_produces}"
                    )
            elif expression == "all handoff contracts passed":
                passed = all(_handoff_passed(report) for report in handoff_reports)
                if not passed:
                    status = "FAIL"
                    detail = "all handoff contracts passed failed"
            else:
                match = re.fullmatch(r"elapsed\s*<=\s*(\d+[mh])", expression.lower())
                if match:
                    limit_seconds = _parse_duration_literal(match.group(1))
                    if elapsed_seconds > limit_seconds:
                        status = "FAIL"
                        detail = (
                            f"elapsed <= {match.group(1)} failed: "
                            f"{elapsed_seconds}s > {limit_seconds}s"
                        )
                else:
                    status = "ERROR"
                    detail = f"Unsupported pipeline health expression: {expression}"
        except Exception as exc:
            status = "ERROR"
            detail = str(exc)

        results.append(
            {
                "name": f"pipeline_health:{description}",
                "status": status,
                "detail": detail,
                "elapsed": "0s",
            }
        )
    return results


def _print_table(title: str, reports: list[dict[str, Any]]) -> None:
    if not reports:
        return
    print(title)
    print("| Scenario | Status | Mode | Detail | Report |")
    print("|----------|--------|------|--------|--------|")
    for report in reports:
        detail = str(report.get("detail") or "").replace("\n", " ").strip()
        print(
            f"| {report['scenario']} | {report['status']} | {report.get('mode', 'RUN')} | "
            f"{detail or '-'} | {report.get('report_path') or '-'} |"
        )
    print()


def _execute_entry(
    entry: dict[str, Any],
    contract: dict[str, Any],
    scenario: dict[str, Any],
    *,
    repo_root: Path,
    args: argparse.Namespace,
    interface: AgentInterface | None = None,
) -> dict[str, Any]:
    gateway_log_path = args.gateway_log_pattern.format(date=_utc_now().date().isoformat())
    provisional_run_id = str(uuid4())
    run_started_at = _iso_timestamp()
    scenario_for_execution = _expand_scenario_for_execution(
        scenario,
        repo_root=repo_root,
        run_id=provisional_run_id,
        gateway_log_path=gateway_log_path,
        run_started_at=run_started_at,
    )
    preconditions = _evaluate_preconditions(
        scenario_for_execution,
        repo_root=repo_root,
        run_id=provisional_run_id,
        gateway_log_path=gateway_log_path,
        run_started_at=run_started_at,
    )
    if not _preconditions_passed(preconditions):
        details = "; ".join(
            f"{item['name']}: {item.get('detail') or item['status']}"
            for item in preconditions
            if item.get("status") != "PASS"
        )
        return _synthetic_report(
            entry=entry,
            scenario_name=scenario["name"],
            mode="DRY-RUN" if args.dry_run else "RUN",
            status="FAIL",
            detail=f"Preconditions failed: {details}",
            assertions=preconditions,
            repo_root=repo_root,
            report_dir=args.report_dir,
        )

    if args.dry_run:
        return _synthetic_report(
            entry=entry,
            scenario_name=scenario["name"],
            mode="DRY-RUN",
            status="PASS",
            detail="DRY-RUN: preconditions passed; scenario was not triggered.",
            assertions=preconditions,
        )

    run_id = provisional_run_id
    if not args.evaluate_only:
        timeout = _effective_trigger_timeout(
            contract=contract,
            cli_timeout=getattr(args, "timeout", None),
        )
        requested_session_key = (
            f"hook:qa:{_slug(entry['target_path'])}:{_slug(scenario['name'])}:{provisional_run_id}"
            if entry.get("target_type") == "skill"
            else None
        )
        trigger = _trigger_scenario(
            entry,
            scenario_for_execution,
            repo_root=repo_root,
            gateway_base=args.gateway_base,
            hooks_token=args.hooks_token,
            requested_session_key=requested_session_key,
            interface=interface,
            openclaw_profile=getattr(args, "openclaw_profile", None),
            timeout=timeout,
        )
        run_id = str(trigger["run_id"])

    run_number = _next_run_number(
        args.report_dir,
        workflow=Path(entry["target_path"]).name,
        scenario=scenario["name"],
        repo_root=repo_root,
    )
    reports = evaluate_contract(
        entry["scenario_file"],
        run_number=run_number,
        scenario_name=scenario["name"],
        extra_context={
            "run_id": run_id,
            "gateway_log_path": gateway_log_path,
            "run_started_at": run_started_at,
        },
        report_dir=args.report_dir,
        repo_root=repo_root,
    )
    report = reports[0]
    report["mode"] = "EVALUATE-ONLY" if args.evaluate_only else "RUN"
    report.setdefault("detail", "")
    report["target"] = entry["target_path"]
    return report


def _run_pipeline(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    target = args.target or ""
    target_path = target if target.startswith("skills/") else f"skills/{target}"
    pipeline_path = repo_root / target_path / "tests" / "pipeline.yaml"
    target_file = _resolve_target_file(repo_root, target_type="skill", target_path=target_path)

    try:
        validation = validate_target(target_file)
    except Exception as exc:
        print(f"Structural validation failed for {target_file}: {exc}")
        return 1
    if validation["status"] == "FAIL":
        print(f"Structural validation failed for {target_file}")
        for check in validation["checks"]:
            if check["status"] == "FAIL":
                print(f"- {check['name']}: {check.get('detail') or 'no detail'}")
        return 1

    pipeline_validation = validate_contract_file(pipeline_path)
    if not pipeline_validation.valid:
        print(f"Pipeline contract is invalid: {pipeline_path}")
        for issue in pipeline_validation.errors:
            print(f"- {issue.path}: {issue.message}")
        return 1

    contract = pipeline_validation.data or {}
    trigger = str(contract.get("pipeline", {}).get("trigger", "")).strip()
    if not trigger:
        print(f"Pipeline contract is missing pipeline.trigger: {pipeline_path}")
        return 1

    if args.dry_run:
        detail = "DRY-RUN: pipeline contract validated; target was not triggered."
        print("PIPELINE")
        print("| Scenario | Status | Mode | Detail | Report |")
        print("|----------|--------|------|--------|--------|")
        print(f"| pipeline | PASS | DRY-RUN | {detail} | - |")
        return 0

    run_id = str(uuid4())
    started_at = _utc_now()
    if not args.evaluate_only:
        entry = {
            "target_path": target_path,
            "target_type": "skill",
            "trigger": trigger,
        }
        scenario = {"name": "pipeline", "when": {"invoke": trigger, "params": {"test_mode": True}}}
        try:
            response = _trigger_scenario(
                entry,
                scenario,
                repo_root=repo_root,
                gateway_base=args.gateway_base,
                hooks_token=args.hooks_token,
                openclaw_profile=getattr(args, "openclaw_profile", None),
                timeout=(
                    int(args.timeout)
                    if getattr(args, "timeout", None) is not None
                    else DEFAULT_TRIGGER_TIMEOUT
                ),
            )
            run_id = str(response["run_id"])
        except Exception as exc:
            report = _synthetic_report(
                entry=entry,
                scenario_name="pipeline",
                mode="RUN",
                status="ERROR",
                detail=str(exc).replace("|", "/"),
                infrastructure_failure=True,
                repo_root=repo_root,
                report_dir=args.report_dir,
            )
            _print_table("INFRASTRUCTURE", [report])
            return 1

    def _evaluate_handoff(handoff_path: Path, active_run_id: str) -> dict[str, Any]:
        reports = evaluate_contract(
            handoff_path,
            run_number=1,
            extra_context={"run_id": active_run_id, "callee_run_id": active_run_id},
            report_dir=args.report_dir,
            repo_root=repo_root,
        )
        report = reports[0]
        report["source_path"] = str(handoff_path)
        return report

    pipeline_state = _monitor_pipeline_stages(
        contract=contract,
        repo_root=repo_root,
        now=started_at,
        evaluate_handoff=_evaluate_handoff,
        run_id=run_id,
        contract_path=pipeline_path,
    )

    run_number = _next_run_number(
        args.report_dir,
        workflow=Path(target_path).name,
        scenario="pipeline",
        repo_root=repo_root,
    )
    try:
        reports = evaluate_contract(
            pipeline_path,
            run_number=run_number,
            extra_context={"run_id": run_id},
            report_dir=args.report_dir,
            repo_root=repo_root,
        )
    except Exception as exc:
        mode = "EVALUATE-ONLY" if args.evaluate_only else "RUN"
        report = _synthetic_report(
            entry={"target_path": target_path, "target_type": "skill", "trigger": trigger},
            scenario_name="pipeline",
            mode=mode,
            status="ERROR",
            detail=str(exc).replace("|", "/"),
            infrastructure_failure=True,
            repo_root=repo_root,
            report_dir=args.report_dir,
        )
        _print_table("INFRASTRUCTURE", [report])
        return 1

    report = reports[0]
    health_results = _evaluate_pipeline_health(
        contract.get("pipeline_health", []),
        state=pipeline_state,
        elapsed_seconds=max(int((_utc_now() - started_at).total_seconds()), 0),
    )
    report["assertions"] = list(report.get("assertions", [])) + health_results
    report["status"] = _classify_assertions(report["assertions"])
    report["stages"] = pipeline_state["stages"]
    report["handoff_reports"] = pipeline_state["handoff_reports"]
    produced = pipeline_state["produced_artifacts"]
    stage_total = pipeline_state["stages_with_produces"]
    handoff_total = len(pipeline_state["handoff_reports"])
    handoff_passes = sum(1 for item in pipeline_state["handoff_reports"] if _handoff_passed(item))
    report["detail"] = (
        f"Stages produced {produced}/{stage_total} artifacts; "
        f"handoffs passed {handoff_passes}/{handoff_total}."
    )
    report["mode"] = "EVALUATE-ONLY" if args.evaluate_only else "RUN"
    bucket = _result_bucket(report)
    _print_table(bucket, [report])
    return 1 if bucket in {"FAIL", "INFRASTRUCTURE"} else 0


def _consistency_config(scenario: dict[str, Any]) -> tuple[int, str]:
    consistency = scenario.get("consistency", {})
    if not isinstance(consistency, dict):
        return 1, "pass_at_k"
    k = int(consistency.get("k", 1) or 1)
    mode = str(consistency.get("mode", "pass_at_k") or "pass_at_k")
    return max(k, 1), mode


def _normalize_target_filter(target: str | Path | None, *, repo_root: Path) -> str | None:
    if target is None:
        return None

    raw = str(target)
    root = repo_root.resolve()
    candidates = [Path(raw)]
    if not Path(raw).is_absolute():
        candidates.append(root / raw)

    for candidate in candidates:
        resolved = candidate.resolve()
        if not resolved.exists():
            continue
        if resolved.is_file():
            resolved = resolved.parent
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError:
            return raw

    return raw


def _aggregate_consistency_reports(
    reports: list[dict[str, Any]],
    *,
    mode: str,
) -> dict[str, Any]:
    if not reports:
        raise ValueError("Consistency aggregation requires at least one report")
    if len(reports) == 1:
        return reports[0]

    statuses = [report.get("status") for report in reports]
    pass_statuses = {"PASS", "WARN"}
    passed_runs = sum(1 for status in statuses if status in pass_statuses)
    aggregate = dict(reports[-1])
    aggregate["consistency"] = {
        "k": len(reports),
        "mode": mode,
        "passed_runs": passed_runs,
    }
    aggregate["detail"] = f"Consistency {mode}: {passed_runs}/{len(reports)} passing runs."
    if mode == "pass_all_k":
        aggregate["status"] = "PASS" if passed_runs == len(reports) else "FAIL"
    else:
        aggregate["status"] = "PASS" if passed_runs else "FAIL"
    return aggregate


def run_contracts(
    *,
    target: str | Path | None = None,
    scenario: str | None = None,
    tags: list[str] | None = None,
    dry_run: bool = False,
    evaluate_only: bool = False,
    timeout: int | None = None,
    config: ClawspecConfig,
    interface: AgentInterface | None = None,
) -> list[dict[str, Any]]:
    repo_root = config.root_dir.resolve()
    target_filter = _normalize_target_filter(target, repo_root=repo_root)
    discovered = discover_scenarios(
        repo_root=repo_root,
        target=target_filter,
        tags=None,
        patterns=config.scenario_patterns,
    )
    if not discovered:
        return []

    selected = discovered
    if tags:
        requested_tags = set(tags)
        selected = [item for item in selected if requested_tags.issubset(set(item.get("tags", [])))]
    if scenario:
        selected = [item for item in selected if item.get("name") == scenario]
    if not selected:
        return []

    target_paths = {item["target_path"] for item in selected}
    missing_negative = _negative_coverage_errors(discovered, target_paths=target_paths)
    reports: list[dict[str, Any]] = []
    if missing_negative:
        for target_path in missing_negative:
            entry = {
                "target_path": target_path,
                "target_type": "unknown",
                "scenario_file": "",
            }
            reports.append(
                _synthetic_report(
                    entry=entry,
                    scenario_name="negative-coverage",
                    mode="RUN",
                    status="FAIL",
                    detail=f"Negative coverage is missing for {target_path}",
                    repo_root=repo_root,
                    report_dir=config.report_dir,
                )
            )
        return reports

    validation_failures: list[tuple[str, str, str]] = []
    for target_type, target_path in sorted(
        {(item["target_type"], item["target_path"]) for item in selected}
    ):
        target_file = _resolve_target_file(
            repo_root, target_type=target_type, target_path=target_path
        )
        try:
            validation = validate_target(target_file)
        except Exception as exc:
            validation_failures.append((target_path, "validator_error", str(exc)))
            continue
        if validation["status"] == "FAIL":
            for check in validation["checks"]:
                if check["status"] == "FAIL":
                    validation_failures.append(
                        (target_path, str(check["name"]), str(check.get("detail") or "no detail"))
                    )
    if validation_failures:
        by_target: dict[str, list[str]] = defaultdict(list)
        for target_path, check_name, detail in validation_failures:
            by_target[target_path].append(f"{check_name}: {detail}")
        for target_path, details in by_target.items():
            entry = {"target_path": target_path, "target_type": "unknown", "scenario_file": ""}
            reports.append(
                _synthetic_report(
                    entry=entry,
                    scenario_name="structural-validation",
                    mode="RUN",
                    status="FAIL",
                    detail="Structural validation failed: " + "; ".join(details),
                    repo_root=repo_root,
                    report_dir=config.report_dir,
                )
            )
        return reports

    contract_cache: dict[str, tuple[dict[str, Any], dict[str, dict[str, Any]]]] = {}
    run_args = argparse.Namespace(
        dry_run=dry_run,
        evaluate_only=evaluate_only,
        gateway_base=config.gateway_base_url,
        hooks_token=config.gateway_auth_token or _hooks_token(),
        openclaw_profile=config.openclaw_profile,
        timeout=timeout,
        report_dir=config.report_dir,
        gateway_log_pattern=config.gateway_log_pattern,
    )
    active_interface = interface or OpenClawInterface(
        gateway_url=config.gateway_base_url,
        token=config.gateway_auth_token,
        openclaw_profile=config.openclaw_profile,
        webhook_endpoint=config.gateway_webhook_endpoint,
        cwd=repo_root,
    )

    for entry in selected:
        scenario_file = entry["scenario_file"]
        contract_validation = validate_contract_file(scenario_file)
        if not contract_validation.valid:
            issue_lines = [f"{issue.path}: {issue.message}" for issue in contract_validation.errors]
            raise SchemaError(f"Scenario contract invalid: {'; '.join(issue_lines)}")

        cached = contract_cache.get(scenario_file)
        if cached is None:
            cached = _scenario_lookup(scenario_file)
            contract_cache[scenario_file] = cached
        contract, scenarios = cached
        scenario_payload = scenarios.get(entry["name"])
        if scenario_payload is None:
            reports.append(
                _synthetic_report(
                    entry=entry,
                    scenario_name=entry["name"],
                    mode="RUN",
                    status="FAIL",
                    detail=f"Scenario {entry['name']} not found in {scenario_file}",
                    repo_root=repo_root,
                    report_dir=config.report_dir,
                )
            )
            continue

        k, mode = _consistency_config(scenario_payload)
        scenario_runs: list[dict[str, Any]] = []
        for _ in range(k):
            try:
                scenario_runs.append(
                    _execute_entry(
                        entry,
                        contract,
                        scenario_payload,
                        repo_root=repo_root,
                        args=run_args,
                        interface=active_interface,
                    )
                )
            except Exception as exc:
                scenario_runs.append(
                    _synthetic_report(
                        entry=entry,
                        scenario_name=entry["name"],
                        mode="EVALUATE-ONLY" if evaluate_only else "RUN",
                        status="ERROR",
                        detail=str(exc),
                        infrastructure_failure=True,
                        repo_root=repo_root,
                        report_dir=config.report_dir,
                    )
                )
        reports.append(_aggregate_consistency_reports(scenario_runs, mode=mode))

    return reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run QA scenario contracts for skills and agents.")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--target", help="Target skill or agent name/path")
    scope.add_argument("--all", action="store_true", help="Run all discovered scenarios")
    parser.add_argument("--scenario", help="Run a single scenario name")
    parser.add_argument("--tags", nargs="*", default=[], help="Filter scenarios by tags")
    parser.add_argument("--dry-run", action="store_true", help="Check preconditions only")
    parser.add_argument(
        "--evaluate-only",
        action="store_true",
        help="Skip trigger and evaluate existing outputs only",
    )
    parser.add_argument("--pipeline", action="store_true", help="Run a pipeline contract")
    parser.add_argument("--repo-root", default=str(_repo_root()), help="Override repository root")
    parser.add_argument("--gateway-base", default=GATEWAY_BASE, help="Override gateway base URL")
    parser.add_argument(
        "--openclaw-profile",
        help=(
            "Use a specific local OpenClaw profile for config lookup, "
            "agent registry, and agent invocation"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        help="Override per-scenario trigger timeout in seconds",
    )
    parser.add_argument(
        "--report-dir",
        default="memory/logs/qa",
        help="Directory for YAML reports in legacy compatibility mode",
    )
    parser.add_argument(
        "--gateway-log-pattern",
        default="/tmp/openclaw/openclaw-{date}.log",
        help="Template for gateway log discovery in legacy compatibility mode",
    )
    parser.add_argument(
        "--hooks-token",
        default=_hooks_token(),
        help="Override HOOKS_TOKEN/OPENCLAW_HOOKS_TOKEN for gateway requests",
    )
    args = parser.parse_args(argv)

    if args.pipeline:
        if args.all:
            print("--pipeline requires --target")
            return 1
        return _run_pipeline(args)

    repo_root = Path(args.repo_root).resolve()
    discovered = discover_scenarios(
        repo_root=repo_root,
        target=None if args.all else args.target,
        tags=None,
    )
    if not discovered:
        print("No scenarios discovered.")
        return 1

    selected = discovered
    if args.tags:
        requested_tags = set(args.tags)
        selected = [item for item in selected if requested_tags.issubset(set(item.get("tags", [])))]
    if args.scenario:
        selected = [item for item in selected if item.get("name") == args.scenario]
    if not selected:
        print("No scenarios matched the requested filters.")
        return 1

    target_paths = {item["target_path"] for item in selected}
    missing_negative = _negative_coverage_errors(discovered, target_paths=target_paths)
    if missing_negative:
        print("Negative coverage is missing for these targets:")
        for target_path in missing_negative:
            print(f"- {target_path}")
        return 1

    validation_failures: list[str] = []
    for entry in sorted(
        {
            (
                item["target_type"],
                item["target_path"],
            )
            for item in selected
        }
    ):
        target_type, target_path = entry
        target_file = _resolve_target_file(
            repo_root, target_type=target_type, target_path=target_path
        )
        try:
            validation = validate_target(target_file)
        except Exception as exc:
            validation_failures.append(f"- {target_path}: {exc}")
            continue
        if validation["status"] == "FAIL":
            validation_failures.append(f"- {target_path}: structural errors present")
            for check in validation["checks"]:
                if check["status"] == "FAIL":
                    validation_failures.append(
                        f"  - {check['name']}: {check.get('detail') or 'no detail'}"
                    )
    if validation_failures:
        print("Structural validation failed:")
        for line in validation_failures:
            print(line)
        return 1

    if not args.dry_run:
        ledger_path = repo_root / "docs" / "testing" / "coverage-ledger.yaml"
        if ledger_path.exists():
            import yaml as _yaml

            ledger = _yaml.safe_load(ledger_path.read_text(encoding="utf-8")) or {}
            for wave_data in (ledger.get("waves") or {}).values():
                for item in wave_data.get("items") or []:
                    if not isinstance(item, dict):
                        continue
                    item_path = item.get("id", "")
                    if item_path not in target_paths:
                        continue
                    verification = item.get("verification") or {}
                    if not verification.get("approved_smoke_scenario"):
                        print(
                            f"Approval gate: {item_path} has no approved_smoke_scenario "
                            f"in the coverage ledger. Run with --dry-run or get approval first."
                        )
                        return 1

    contract_cache: dict[str, tuple[dict[str, Any], dict[str, dict[str, Any]]]] = {}
    reports: list[dict[str, Any]] = []
    for entry in selected:
        scenario_file = entry["scenario_file"]
        contract_validation = validate_contract_file(scenario_file)
        if not contract_validation.valid:
            issue_lines = [f"{issue.path}: {issue.message}" for issue in contract_validation.errors]
            reports.append(
                _synthetic_report(
                    entry=entry,
                    scenario_name=entry["name"],
                    mode="RUN",
                    status="FAIL",
                    detail=f"Scenario contract invalid: {'; '.join(issue_lines)}",
                    repo_root=repo_root,
                    report_dir=args.report_dir,
                )
            )
            continue

        cached = contract_cache.get(scenario_file)
        if cached is None:
            cached = _scenario_lookup(scenario_file)
            contract_cache[scenario_file] = cached
        contract, scenarios = cached
        scenario = scenarios.get(entry["name"])
        if scenario is None:
            reports.append(
                _synthetic_report(
                    entry=entry,
                    scenario_name=entry["name"],
                    mode="RUN",
                    status="FAIL",
                    detail=f"Scenario {entry['name']} not found in {scenario_file}",
                    repo_root=repo_root,
                    report_dir=args.report_dir,
                )
            )
            continue

        try:
            report = _execute_entry(entry, contract, scenario, repo_root=repo_root, args=args)
        except Exception as exc:
            report = _synthetic_report(
                entry=entry,
                scenario_name=entry["name"],
                mode="EVALUATE-ONLY" if args.evaluate_only else "RUN",
                status="ERROR",
                detail=str(exc),
                infrastructure_failure=True,
                repo_root=repo_root,
                report_dir=args.report_dir,
            )
        reports.append(report)

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        buckets[_result_bucket(report)].append(report)

    _print_table("FAIL", buckets.get("FAIL", []))
    _print_table("WARN", buckets.get("WARN", []))
    _print_table("INFRASTRUCTURE", buckets.get("INFRASTRUCTURE", []))
    _print_table("PASS", buckets.get("PASS", []))

    totals = {
        name: len(buckets.get(name, [])) for name in ("PASS", "WARN", "FAIL", "INFRASTRUCTURE")
    }
    print(
        "Totals: "
        f"PASS={totals['PASS']} WARN={totals['WARN']} "
        f"FAIL={totals['FAIL']} INFRASTRUCTURE={totals['INFRASTRUCTURE']}"
    )

    return 1 if totals["FAIL"] or totals["INFRASTRUCTURE"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
