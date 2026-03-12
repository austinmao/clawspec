from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


def _candidate_target_names(target_path: str) -> set[str]:
    path = target_path.strip("/")
    pieces = [piece for piece in path.split("/") if piece]
    candidates = {path}
    if pieces and pieces[0] in {"skills", "agents"}:
        trimmed = "/".join(pieces[1:])
        if trimmed:
            candidates.add(trimmed)
    if pieces:
        candidates.add(pieces[-1])
    return candidates


def _load_scenarios(scenario_file: Path) -> list[dict[str, Any]]:
    payload = yaml.safe_load(scenario_file.read_text(encoding="utf-8")) or {}
    target = payload.get("target", {})
    scenarios = payload.get("scenarios", [])
    if not isinstance(target, dict) or not isinstance(scenarios, list):
        return []

    target_path = str(target.get("path", ""))
    entries: list[dict[str, Any]] = []
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict):
            continue
        entries.append(
            {
                "name": scenario.get("name"),
                "tags": list(scenario.get("tags", []) or []),
                "scenario_file": str(scenario_file.resolve()),
                "target_type": target.get("type"),
                "target_path": target_path,
                "target_name": Path(target_path).name if target_path else "",
                "trigger": target.get("trigger"),
                "_scenario_index": index,
            }
        )
    return entries


def discover_scenarios(
    *,
    repo_root: str | Path,
    target: str | None = None,
    tags: list[str] | None = None,
    patterns: list[str] | None = None,
) -> list[dict[str, Any]]:
    root = Path(repo_root)
    search_patterns = patterns or [
        "skills/**/tests/scenarios.yaml",
        "agents/**/tests/scenarios.yaml",
    ]
    scenario_files: list[Path] = []
    for pattern in search_patterns:
        scenario_files.extend(sorted(root.glob(pattern)))

    requested_tags = set(tags or [])
    discovered: list[dict[str, Any]] = []
    for scenario_file in scenario_files:
        for entry in _load_scenarios(scenario_file):
            if target and target not in _candidate_target_names(entry["target_path"]):
                continue
            if requested_tags and not requested_tags.issubset(set(entry["tags"])):
                continue
            discovered.append(entry)

    ordered = sorted(discovered, key=lambda item: (item["scenario_file"], item["_scenario_index"]))
    for item in ordered:
        item.pop("_scenario_index", None)
    return ordered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover skill and agent scenario files.")
    parser.add_argument("--target", help="Filter to a specific target name or path")
    parser.add_argument("--tags", nargs="*", default=[], help="Filter scenarios by tags")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[2]),
        help="Override repository root for discovery",
    )
    parser.add_argument("--pattern", action="append", default=[], help="Additional glob pattern")
    args = parser.parse_args(argv)

    payload = discover_scenarios(
        repo_root=args.repo_root,
        target=args.target,
        tags=args.tags,
        patterns=args.pattern or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
