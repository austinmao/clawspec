from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from clawspec import __version__
from clawspec.api import coverage, init, run, validate
from clawspec.config import ClawspecConfig
from clawspec.exceptions import ClawspecError, SchemaError


def _config_from_args(
    args: argparse.Namespace, *, target: str | Path | None = None
) -> ClawspecConfig:
    start = Path(target).resolve() if target is not None else Path.cwd()
    if start.is_file():
        start = start.parent
    return ClawspecConfig.load(path=args.config, start=start)


def _emit(payload: Any, *, as_json: bool) -> None:
    if hasattr(payload, "to_json") and as_json:
        print(payload.to_json())
        return
    if hasattr(payload, "to_dict") and as_json:
        print(json.dumps(payload.to_dict(), indent=2, sort_keys=True))
        return
    if isinstance(payload, list):
        if as_json:
            print(
                json.dumps(
                    [item.to_dict() if hasattr(item, "to_dict") else item for item in payload],
                    indent=2,
                    sort_keys=True,
                )
            )
            return
        for item in payload:
            _emit(item, as_json=False)
        return
    if hasattr(payload, "checks"):
        total = getattr(payload, "total_checks", 0)
        passed = getattr(payload, "passed_checks", 0)
        for check in payload.checks:
            marker = "PASS" if check.status == "pass" else "FAIL"
            detail = f" - {check.detail}" if check.detail else ""
            print(f"{marker} {check.name}{detail}")
        print(f"{passed}/{total} checks passed")
        return
    if hasattr(payload, "scenarios"):
        for scenario in payload.scenarios:
            print(f"{scenario.status.upper():4} {scenario.name}")
        print(
            f"{payload.summary.total_scenarios} scenarios, "
            f"{payload.summary.failed} failures, {payload.summary.warned} warnings"
        )
        if payload.report_path:
            print(f"Report written to: {payload.report_path}")
        return
    if hasattr(payload, "gaps"):
        coverage = (
            f"Coverage: {payload.covered}/{payload.total_items} items "
            f"({payload.coverage_percentage:.1f}%)"
        )
        print(coverage)
        if payload.gaps:
            print("\nGaps:")
            for gap in payload.gaps:
                print(f"  - {gap.path} — missing {', '.join(gap.missing)}")
        if payload.report_path:
            print(f"\nReport written to: {payload.report_path}")
        return
    if hasattr(payload, "created"):
        print(f"Created {payload.created} for {payload.target_type} at {payload.target}")
        return
    print(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clawspec")
    parser.add_argument("--config")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("target")
    validate_parser.add_argument("--json", action="store_true")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("target", nargs="?")
    run_parser.add_argument("--gateway")
    run_parser.add_argument("--scenario")
    run_parser.add_argument("--tags")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--json", action="store_true")
    run_parser.add_argument("--timeout", type=int, default=60)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("target", nargs="?")
    init_parser.add_argument("--force", action="store_true")
    init_parser.add_argument("--json", action="store_true")

    coverage_parser = subparsers.add_parser("coverage")
    coverage_parser.add_argument("--ledger")
    coverage_parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            payload = validate(args.target, config=_config_from_args(args, target=args.target))
            _emit(payload, as_json=args.json)
            return payload.exit_code
        if args.command == "run":
            tags = (
                [item.strip() for item in args.tags.split(",")]
                if getattr(args, "tags", None)
                else None
            )
            payload = run(
                args.target,
                gateway=args.gateway,
                scenario=args.scenario,
                tags=tags,
                dry_run=args.dry_run,
                timeout=args.timeout,
                config=_config_from_args(args, target=args.target),
            )
            _emit(payload, as_json=args.json)
            return max((item.exit_code for item in payload), default=0)
        if args.command == "init":
            payload = init(
                args.target, force=args.force, config=_config_from_args(args, target=args.target)
            )
            _emit(payload, as_json=args.json)
            return 0
        payload = coverage(args.ledger, config=_config_from_args(args))
        _emit(payload, as_json=args.json)
        return 1 if payload.gaps else 0
    except SchemaError as exc:
        print(str(exc))
        return 3
    except FileExistsError as exc:
        print(str(exc))
        return 2
    except ClawspecError as exc:
        print(str(exc))
        return 2
