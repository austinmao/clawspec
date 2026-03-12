from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from clawspec.exceptions import ClawspecError
from clawspec.validate.common import parse_frontmatter, read_text


def _detect_runtime_target(target: Path) -> tuple[str, Path]:
    if target.is_file():
        if target.name == "SKILL.md":
            return "skill", target
        if target.name == "SOUL.md":
            return "agent", target
        raise ClawspecError("Target must be a SKILL.md, SOUL.md, or their containing directory")
    skill_path = target / "SKILL.md"
    agent_path = target / "SOUL.md"
    if skill_path.exists():
        return "skill", skill_path
    if agent_path.exists():
        return "agent", agent_path
    raise ClawspecError("No SKILL.md or SOUL.md found at target")


def _trigger_for_skill(skill_path: Path) -> tuple[str, str]:
    frontmatter, _, error = parse_frontmatter(read_text(skill_path))
    if error:
        raise ClawspecError(error)
    name = str(frontmatter.get("name") or skill_path.parent.name).strip()
    triggers = frontmatter.get("triggers", [])
    trigger = ""
    if isinstance(triggers, list) and triggers:
        first = triggers[0]
        if isinstance(first, dict):
            trigger = str(first.get("command") or "").strip()
    if not trigger:
        trigger = f"/{skill_path.parent.name}"
    return name, trigger


def _agent_name(agent_path: Path) -> str:
    return agent_path.parent.name


def _runtime_target_path(source_file: Path) -> str:
    parts = source_file.parent.parts
    for marker in ("skills", "agents"):
        if marker in parts:
            index = parts.index(marker)
            return "/".join(parts[index:])
    return source_file.parent.name


def scaffold_scenarios(
    target: str | Path,
    *,
    force: bool = False,
) -> tuple[Path, str, str, bool]:
    target_path = Path(target).resolve()
    target_type, source_file = _detect_runtime_target(target_path)
    output_path = source_file.parent / "tests" / "scenarios.yaml"
    overwritten = output_path.exists()
    if overwritten and not force:
        raise FileExistsError(f"{output_path} already exists")

    if target_type == "skill":
        name, trigger = _trigger_for_skill(source_file)
        payload: dict[str, Any] = {
            "version": "1.0",
            "target": {
                "type": "skill",
                "path": _runtime_target_path(source_file),
                "trigger": trigger,
            },
            "scenarios": [
                {
                    "name": f"{name}-smoke",
                    "tags": ["smoke"],
                    "when": {"invoke": trigger, "params": {"test_mode": True}},
                    "then": [
                        {
                            "type": "artifact_exists",
                            "path": "memory/drafts/{{today}}-output.md",
                        }
                    ],
                },
                {
                    "name": f"{name}-negative",
                    "tags": ["negative"],
                    "when": {
                        "invoke": f"{trigger} forbidden-request",
                        "params": {"test_mode": True},
                    },
                    "then": [{"type": "tool_not_called", "tool": "send_message"}],
                },
            ],
        }
    else:
        name = _agent_name(source_file)
        payload = {
            "version": "1.0",
            "target": {
                "type": "agent",
                "path": _runtime_target_path(source_file),
                "trigger": source_file.parent.as_posix().replace("/", "-"),
            },
            "scenarios": [
                {
                    "name": f"{name}-smoke",
                    "tags": ["smoke"],
                    "when": {
                        "invoke": (
                            f"Create a draft artifact for {name} "
                            "without taking external actions."
                        ),
                        "params": {"test_mode": True},
                    },
                    "then": [
                        {"type": "artifact_exists", "path": "memory/drafts/{{today}}-output.md"}
                    ],
                },
                {
                    "name": f"{name}-negative",
                    "tags": ["negative"],
                    "when": {
                        "invoke": "Refuse an out-of-scope request and do not send anything.",
                        "params": {"test_mode": True},
                    },
                    "then": [{"type": "tool_not_called", "tool": "send_message"}],
                },
            ],
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return output_path, str(target_path), target_type, overwritten
