from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from clawspec.api import coverage, init, run, validate
from clawspec.config import ClawspecConfig
from clawspec.exceptions import ClawspecError, SchemaError


def _config(target: str | None = None) -> ClawspecConfig:
    start = Path(target).resolve() if target else Path.cwd()
    if start.is_file():
        start = start.parent
    return ClawspecConfig.load(start=start)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="/clawspec")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("target")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("target", nargs="?")
    run_parser.add_argument("--gateway")
    run_parser.add_argument("--scenario")
    run_parser.add_argument("--tags")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--timeout", type=int, default=60)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("target", nargs="?")
    init_parser.add_argument("--force", action="store_true")

    coverage_parser = subparsers.add_parser("coverage")
    coverage_parser.add_argument("--ledger")
    return parser


def _emit(command: str, exit_code: int, data: object) -> int:
    payload = {
        "status": "completed" if exit_code in {0, 1} else "error",
        "command": command,
        "exit_code": exit_code,
        "data": (
            [item.to_dict() if hasattr(item, "to_dict") else item for item in data]
            if isinstance(data, list)
            else data.to_dict()
            if hasattr(data, "to_dict")
            else data
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            report = validate(args.target, config=_config(args.target))
            return _emit("validate", report.exit_code, report)
        if args.command == "run":
            tags = [item.strip() for item in args.tags.split(",")] if args.tags else None
            reports = run(
                args.target,
                gateway=args.gateway,
                scenario=args.scenario,
                tags=tags,
                dry_run=args.dry_run,
                timeout=args.timeout,
                config=_config(args.target),
            )
            return _emit("run", max((item.exit_code for item in reports), default=0), reports)
        if args.command == "init":
            report = init(args.target, force=args.force, config=_config(args.target))
            return _emit("init", 0, report)
        report = coverage(args.ledger, config=_config())
        return _emit("coverage", 1 if report.gaps else 0, report)
    except SchemaError as exc:
        return _emit(args.command, 3, {"detail": str(exc)})
    except FileExistsError as exc:
        return _emit(args.command, 2, {"detail": str(exc)})
    except ClawspecError as exc:
        return _emit(args.command, 2, {"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive wrapper boundary
        return _emit(args.command, 2, {"detail": str(exc)})


if __name__ == "__main__":
    raise SystemExit(main())
