from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from clawspec.coverage.ledger import (
    detect_item_state,
    load_ledger,
    resolve_repo_root,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


DEFAULT_LEDGER_PATH = Path("coverage-ledger.yaml")


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolve_path(path: str | Path, *, repo_root: Path) -> Path:
    target = Path(path)
    return target if target.is_absolute() else repo_root / target


def find_contract_gaps(entry: dict[str, Any], *, repo_root: Path | None = None) -> dict[str, Any]:
    active_root = repo_root or _repo_root()
    contracts = entry.get("contracts", {}) if isinstance(entry.get("contracts"), dict) else {}
    state = detect_item_state(entry, repo_root=active_root)

    missing_files: list[str] = []
    missing_targets: list[str] = []

    scenario_file = str(contracts.get("scenario_file") or "").strip()
    scenario_path = _resolve_path(scenario_file, repo_root=active_root) if scenario_file else None
    if scenario_file and scenario_path and not scenario_path.exists():
        missing_files.append(scenario_file)
    coverage = entry.get("coverage", {}) if isinstance(entry.get("coverage"), dict) else {}
    declared_negative_coverage = bool(coverage.get("negative"))
    if not state["target_exists"]:
        missing_targets.append(str(entry.get("id")))

    pipeline_file = str(contracts.get("pipeline_file") or "").strip()
    missing_pipeline = False
    if entry.get("tier") == "orchestrator":
        if not pipeline_file:
            missing_pipeline = True
        else:
            pipeline_path = _resolve_path(pipeline_file, repo_root=active_root)
            if not pipeline_path.exists():
                missing_pipeline = True
                missing_files.append(pipeline_file)

    handoff_files = contracts.get("handoff_files", []) or []
    missing_handoffs = False
    if entry.get("tier") == "orchestrator":
        if not isinstance(handoff_files, list) or not handoff_files:
            missing_handoffs = True
        else:
            for handoff_file in handoff_files:
                handoff_path = _resolve_path(handoff_file, repo_root=active_root)
                if not handoff_path.exists():
                    missing_handoffs = True
                    missing_files.append(str(handoff_file))

    missing_negative = (not declared_negative_coverage) or (
        scenario_path is not None and scenario_path.exists() and not state["negative_present"]
    )

    return {
        "missing_files": missing_files,
        "missing_negative_coverage": missing_negative,
        "missing_targets": missing_targets,
        "orchestrator_missing_pipeline": missing_pipeline,
        "orchestrator_missing_handoffs": missing_handoffs,
    }


def _increment(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def build_summary(
    ledger_path: str | Path,
    report_root: str | Path,
    date: str | None = None,
    wave: str | None = None,
) -> dict[str, Any]:
    active_ledger_path = Path(ledger_path)
    repo_root = resolve_repo_root(active_ledger_path)
    ledger = load_ledger(ledger_path)
    all_waves = ledger["waves"]
    if wave is not None:
        if wave not in all_waves:
            raise KeyError(wave)
        selected_waves = {wave: all_waves[wave]}
    else:
        selected_waves = all_waves

    counts_by_status: dict[str, int] = {}
    counts_by_tier: dict[str, int] = {}
    counts_by_wave: dict[str, int] = {}
    missing_files: list[str] = []
    missing_negative_coverage: list[str] = []
    missing_targets: list[str] = []
    orchestrators_missing_pipeline: list[str] = []
    orchestrators_missing_handoffs: list[str] = []
    wave_summaries: dict[str, dict[str, Any]] = {}
    total_items = 0
    active_report_root = Path(report_root)
    if active_report_root.exists():
        pattern = f"{date}-*.yaml" if date else "*.yaml"
        recent_report_count = len(sorted(active_report_root.glob(pattern)))
    else:
        recent_report_count = 0

    for wave_name, wave_data in selected_waves.items():
        items = wave_data.get("items", []) if isinstance(wave_data, dict) else []
        wave_statuses: dict[str, int] = {}
        wave_tiers: dict[str, int] = {}
        wave_missing_files: list[str] = []
        wave_missing_negative_coverage: list[str] = []
        wave_missing_targets: list[str] = []
        wave_missing_pipeline: list[str] = []
        wave_missing_handoffs: list[str] = []

        for entry in items:
            if not isinstance(entry, dict):
                continue
            total_items += 1
            _increment(counts_by_wave, wave_name)
            status = str(entry.get("status") or "unknown")
            tier = str(entry.get("tier") or "unknown")
            _increment(counts_by_status, status)
            _increment(counts_by_tier, tier)
            _increment(wave_statuses, status)
            _increment(wave_tiers, tier)

            gaps = find_contract_gaps(entry, repo_root=repo_root)
            missing_files.extend(gaps["missing_files"])
            wave_missing_files.extend(gaps["missing_files"])
            if gaps["missing_negative_coverage"]:
                missing_negative_coverage.append(str(entry.get("id")))
                wave_missing_negative_coverage.append(str(entry.get("id")))
            if gaps["missing_targets"]:
                missing_targets.extend(gaps["missing_targets"])
                wave_missing_targets.extend(gaps["missing_targets"])
            if gaps["orchestrator_missing_pipeline"]:
                orchestrators_missing_pipeline.append(str(entry.get("id")))
                wave_missing_pipeline.append(str(entry.get("id")))
            if gaps["orchestrator_missing_handoffs"]:
                orchestrators_missing_handoffs.append(str(entry.get("id")))
                wave_missing_handoffs.append(str(entry.get("id")))

        wave_summaries[wave_name] = {
            "status": wave_data.get("status"),
            "total_items": sum(wave_statuses.values()),
            "counts_by_status": dict(sorted(wave_statuses.items())),
            "counts_by_tier": dict(sorted(wave_tiers.items())),
            "missing_files": sorted(set(wave_missing_files)),
            "missing_negative_coverage": sorted(set(wave_missing_negative_coverage)),
            "missing_targets": sorted(set(wave_missing_targets)),
            "orchestrators_missing_pipeline": sorted(set(wave_missing_pipeline)),
            "orchestrators_missing_handoffs": sorted(set(wave_missing_handoffs)),
            "recent_report_count": recent_report_count,
        }

    repo_root_str = str(repo_root)

    def _relative(p: Path | str) -> str:
        s = str(p)
        if s.startswith(repo_root_str):
            return s[len(repo_root_str) :].lstrip("/")
        return s

    return {
        "generated_at": _utc_now(),
        "ledger_path": _relative(active_ledger_path),
        "report_root": _relative(active_report_root),
        "selected_wave": wave,
        "total_items": total_items,
        "counts_by_wave": dict(sorted(counts_by_wave.items())),
        "counts_by_status": dict(sorted(counts_by_status.items())),
        "counts_by_tier": dict(sorted(counts_by_tier.items())),
        "waves": dict(sorted(wave_summaries.items())),
        "missing_files": sorted(set(missing_files)),
        "missing_negative_coverage": sorted(set(missing_negative_coverage)),
        "missing_targets": sorted(set(missing_targets)),
        "orchestrators_missing_pipeline": sorted(set(orchestrators_missing_pipeline)),
        "orchestrators_missing_handoffs": sorted(set(orchestrators_missing_handoffs)),
        "recent_report_count": recent_report_count,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize Marketing Wave coverage from the coverage ledger."
    )
    parser.add_argument(
        "--ledger",
        default=str(DEFAULT_LEDGER_PATH),
        help="Path to docs/testing/coverage-ledger.yaml",
    )
    parser.add_argument("--wave", help="Filter to a specific wave id")
    parser.add_argument("--date", help="Optional report date in YYYY-MM-DD format")
    parser.add_argument(
        "--report-root", help="Override the QA report directory used for recent report counts"
    )
    parser.add_argument(
        "--write-json", action="store_true", help="Write the summary to coverage-summary.json"
    )
    args = parser.parse_args(argv)

    active_report_root = (
        Path(args.report_root)
        if args.report_root
        else resolve_repo_root(args.ledger) / "memory" / "logs" / "qa"
    )

    try:
        payload = build_summary(
            ledger_path=args.ledger,
            report_root=active_report_root,
            date=args.date,
            wave=args.wave,
        )
    except KeyError:
        print(json.dumps({"status": "ERROR", "detail": f"Wave not found: {args.wave}"}, indent=2))
        return 2
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "detail": str(exc)}, indent=2))
        return 2

    if args.write_json:
        output_path = active_report_root / "coverage-summary.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        payload["report_path"] = str(output_path)
    else:
        payload["report_path"] = None

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
