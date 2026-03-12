from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {key: _json_safe(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str | None = None


@dataclass
class ValidationReport:
    target: str
    target_type: str
    passed: bool
    checks: list[CheckResult]
    total_checks: int
    passed_checks: int
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @property
    def exit_code(self) -> int:
        return 0 if self.passed else 1


@dataclass
class AssertionResult:
    type: str
    status: str
    expected: Any = None
    actual: Any = None
    detail: str | None = None


@dataclass
class ScenarioResult:
    name: str
    status: str
    assertions: list[AssertionResult]
    duration_ms: int
    run_number: int
    detail: str | None = None
    report_path: str | None = None


@dataclass
class RunSummary:
    total_scenarios: int
    passed: int
    failed: int
    skipped: int
    warned: int


@dataclass
class RunReport:
    target: str
    scenarios: list[ScenarioResult]
    summary: RunSummary
    exit_code: int
    timestamp: str = field(default_factory=utc_now)
    report_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


@dataclass
class GapItem:
    id: str
    path: str
    missing: list[str]


@dataclass
class CoverageReport:
    ledger_path: str
    total_items: int
    covered: int
    uncovered: int
    gaps: list[GapItem]
    coverage_percentage: float
    timestamp: str = field(default_factory=utc_now)
    report_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


@dataclass
class InitReport:
    target: str
    target_type: str
    created: str
    overwritten: bool
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)
