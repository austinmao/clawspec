from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from clawspec.templates.expander import ALLOWED_VARIABLES, iter_template_variables

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
SCHEMA_FILES = {
    "scenario": SCHEMA_DIR / "scenario.schema.yaml",
    "handoff": SCHEMA_DIR / "handoff.schema.yaml",
    "pipeline": SCHEMA_DIR / "pipeline.schema.yaml",
}
CONTRACT_KEY_MAP = {
    "scenario": "target",
    "handoff": "handoff",
    "pipeline": "pipeline",
}


@dataclass(eq=True)
class ValidationIssue:
    path: str
    message: str


@dataclass
class ValidationResult:
    kind: str
    valid: bool
    errors: list[ValidationIssue]
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["errors"] = [asdict(issue) for issue in self.errors]
        return payload


def _format_error_path(error_path: list[Any]) -> str:
    if not error_path:
        return "$"
    return "/".join(str(part) for part in error_path)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("Contract file must contain a top-level mapping")
    return loaded


def detect_contract_kind(data: dict[str, Any]) -> str:
    present = [kind for kind, key in CONTRACT_KEY_MAP.items() if key in data]
    if len(present) != 1:
        raise ValueError("Expected exactly one of top-level keys: target, handoff, pipeline")
    return present[0]


def _load_schema(kind: str) -> dict[str, Any]:
    with SCHEMA_FILES[kind].open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _find_unknown_template_variables(
    value: Any, path: list[Any] | None = None
) -> list[ValidationIssue]:
    path = path or []
    issues: list[ValidationIssue] = []
    if isinstance(value, str):
        for variable in iter_template_variables(value):
            if variable not in ALLOWED_VARIABLES:
                issues.append(
                    ValidationIssue(
                        path=_format_error_path(path),
                        message=f"Unknown template variable: {variable}",
                    )
                )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            issues.extend(_find_unknown_template_variables(item, path + [index]))
    elif isinstance(value, dict):
        for key, item in value.items():
            issues.extend(_find_unknown_template_variables(item, path + [key]))
    return issues


def _validate_handoff_invariants(data: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    required_context = (
        data.get("caller_provides", {}).get("required_context", [])
        if isinstance(data.get("caller_provides"), dict)
        else []
    )
    names = [item.get("name", "") for item in required_context if isinstance(item, dict)]
    duplicates = sorted({name for name in names if name and names.count(name) > 1})
    for duplicate in duplicates:
        issues.append(
            ValidationIssue(
                path="caller_provides/required_context",
                message=f"Duplicate required_context name: {duplicate}",
            )
        )

    prohibited = (
        data.get("callee_produces", {}).get("prohibited_actions", [])
        if isinstance(data.get("callee_produces"), dict)
        else []
    )
    for index, item in enumerate(prohibited):
        tool = item.get("tool", "") if isinstance(item, dict) else ""
        if not tool.strip() or "*" in tool or "{{" in tool:
            issues.append(
                ValidationIssue(
                    path=f"callee_produces/prohibited_actions/{index}/tool",
                    message="Prohibited actions require a concrete tool id",
                )
            )

    artifacts = (
        data.get("callee_produces", {}).get("required_artifacts", [])
        if isinstance(data.get("callee_produces"), dict)
        else []
    )
    for index, item in enumerate(artifacts):
        path_pattern = item.get("path_pattern", "") if isinstance(item, dict) else ""
        if not path_pattern.strip():
            issues.append(
                ValidationIssue(
                    path=f"callee_produces/required_artifacts/{index}/path_pattern",
                    message="Artifact path_pattern must be non-empty",
                )
            )
    return issues


def _resolve_pipeline_relative_path(
    source_path: Path,
    *,
    skill_path: str,
    relative_path: str,
) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute():
        return relative

    expected_suffix = Path(skill_path) / "tests" / source_path.name
    for ancestor in source_path.parents:
        if ancestor / expected_suffix == source_path:
            return ancestor / skill_path / relative

    if source_path.parent.name == "tests":
        return source_path.parent.parent / relative
    return source_path.parent / relative


def _validate_pipeline_invariants(
    data: dict[str, Any],
    *,
    source_path: Path | None = None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    pipeline = data.get("pipeline", {}) if isinstance(data.get("pipeline"), dict) else {}
    stages = data.get("stages", []) if isinstance(data.get("stages"), list) else []

    declared_stage_count = pipeline.get("stages")
    if isinstance(declared_stage_count, int) and declared_stage_count != len(stages):
        issues.append(
            ValidationIssue(
                path="pipeline/stages",
                message=(
                    "pipeline.stages must match the number of stage definitions "
                    f"({declared_stage_count} declared, {len(stages)} found)"
                ),
            )
        )

    names = [item.get("name", "") for item in stages if isinstance(item, dict)]
    duplicates = sorted({name for name in names if name and names.count(name) > 1})
    for duplicate in duplicates:
        issues.append(
            ValidationIssue(
                path="stages",
                message=f"Duplicate stage name: {duplicate}",
            )
        )

    skill_path = str(pipeline.get("skill_path", "")).strip()
    if source_path is None or not skill_path:
        return issues

    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            continue
        handoff_ref = str(stage.get("handoff_contract", "")).strip()
        if not handoff_ref:
            continue
        handoff_path = _resolve_pipeline_relative_path(
            source_path,
            skill_path=skill_path,
            relative_path=handoff_ref,
        )
        if not handoff_path.exists():
            issues.append(
                ValidationIssue(
                    path=f"stages/{index}/handoff_contract",
                    message=f"Referenced handoff contract does not exist: {handoff_ref}",
                )
            )
    return issues


def validate_contract_data(
    data: dict[str, Any],
    *,
    kind: str,
    source_path: Path | None = None,
) -> ValidationResult:
    schema = _load_schema(kind)
    validator = Draft202012Validator(schema)
    schema_errors = sorted(validator.iter_errors(data), key=lambda item: list(item.path))
    issues = [
        ValidationIssue(
            path=_format_error_path(list(error.absolute_path)),
            message=error.message,
        )
        for error in schema_errors
    ]
    issues.extend(_find_unknown_template_variables(data))
    if kind == "handoff":
        issues.extend(_validate_handoff_invariants(data))
    if kind == "pipeline":
        issues.extend(_validate_pipeline_invariants(data, source_path=source_path))
    return ValidationResult(kind=kind, valid=not issues, errors=issues, data=data)


def validate_contract_file(path: str | Path) -> ValidationResult:
    contract_path = Path(path)
    try:
        data = _load_yaml(contract_path)
        kind = detect_contract_kind(data)
    except Exception as exc:
        return ValidationResult(
            kind="unknown",
            valid=False,
            errors=[ValidationIssue(path="$", message=str(exc))],
        )
    return validate_contract_data(data, kind=kind, source_path=contract_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a QA contract YAML file.")
    parser.add_argument("contract_path", help="Path to a scenario, handoff, or pipeline contract")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of YAML")
    args = parser.parse_args(argv)

    result = validate_contract_file(args.contract_path)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(yaml.safe_dump(payload, sort_keys=False))
    return 0 if result.valid else 3


if __name__ == "__main__":
    raise SystemExit(main())
