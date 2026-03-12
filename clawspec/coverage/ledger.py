from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_ledger(path: str | Path) -> dict[str, Any]:
    ledger_path = Path(path)
    payload = yaml.safe_load(ledger_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"{ledger_path} must contain a top-level mapping")
    waves = payload.get("waves")
    if not isinstance(waves, dict):
        raise ValueError(f"{ledger_path} is missing a top-level waves mapping")
    return payload


def resolve_repo_root(ledger_path: str | Path) -> Path:
    path = Path(ledger_path).resolve()
    if path.parent.name == "testing" and path.parent.parent.name == "docs":
        return path.parents[2]
    return path.parent


def resolve_target_path(entry: dict[str, Any], *, repo_root: Path) -> Path:
    target_id = str(entry.get("path") or entry.get("id") or "").strip()
    if not target_id:
        return repo_root
    return repo_root / target_id


def resolve_contract_path(path: str | Path, *, repo_root: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else repo_root / candidate


def scenario_has_negative_coverage(path: Path) -> bool | None:
    if not path.exists():
        return None
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    scenarios = payload.get("scenarios", [])
    if not isinstance(scenarios, list):
        return False
    return any(
        isinstance(scenario, dict) and "negative" in set(scenario.get("tags", []) or [])
        for scenario in scenarios
    )


def detect_item_state(entry: dict[str, Any], *, repo_root: Path) -> dict[str, Any]:
    contracts = entry.get("contracts", {}) if isinstance(entry.get("contracts"), dict) else {}
    target_path = resolve_target_path(entry, repo_root=repo_root)
    scenario_file = str(contracts.get("scenario_file") or "").strip()
    scenario_path = (
        resolve_contract_path(scenario_file, repo_root=repo_root) if scenario_file else None
    )
    scenario_present = bool(scenario_path and scenario_path.exists())
    negative_present = scenario_has_negative_coverage(scenario_path) if scenario_path else None
    return {
        "target_exists": target_path.exists(),
        "scenario_present": scenario_present,
        "negative_present": bool(negative_present),
        "target_path": str(target_path),
        "scenario_path": str(scenario_path) if scenario_path else None,
    }
