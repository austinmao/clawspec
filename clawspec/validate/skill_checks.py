from __future__ import annotations

import re
from pathlib import Path

from .common import (
    find_binary_references,
    find_env_references,
    has_secret,
    parse_frontmatter,
    read_text,
    result,
)

TRIGGER_DESCRIPTION_PATTERN = re.compile(r"^(use|run|trigger) when\b", re.IGNORECASE)
KEBAB_CASE_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def run_skill_checks(path: str | Path) -> list[dict[str, str | None]]:
    skill_path = Path(path)
    content = read_text(skill_path)
    frontmatter, body, frontmatter_error = parse_frontmatter(content)

    metadata = frontmatter.get("metadata", {}) if isinstance(frontmatter, dict) else {}
    openclaw = metadata.get("openclaw", {}) if isinstance(metadata, dict) else {}
    requires = openclaw.get("requires", {}) if isinstance(openclaw, dict) else {}
    declared_envs = set(requires.get("env", []) or [])
    declared_bins = set(requires.get("bins", []) or [])
    permissions = frontmatter.get("permissions") if isinstance(frontmatter, dict) else None
    name = frontmatter.get("name") if isinstance(frontmatter, dict) else None
    description = frontmatter.get("description") if isinstance(frontmatter, dict) else None

    checks: list[dict[str, str | None]] = []

    if frontmatter_error or not name or not description:
        detail = frontmatter_error or "Frontmatter requires both name and description"
        checks.append(result("frontmatter_required", "FAIL", detail))
    else:
        checks.append(result("frontmatter_required", "PASS"))

    if isinstance(name, str) and KEBAB_CASE_PATTERN.fullmatch(name):
        checks.append(result("name_kebab_case", "PASS"))
    else:
        checks.append(result("name_kebab_case", "FAIL", "name must be kebab-case"))

    if isinstance(permissions, dict) and {"filesystem", "network"} <= set(permissions):
        checks.append(result("permissions_declared", "PASS"))
    else:
        checks.append(
            result(
                "permissions_declared",
                "FAIL",
                "permissions must declare filesystem and network",
            )
        )

    referenced_envs = find_env_references(body)
    missing_envs = sorted(env for env in referenced_envs if env not in declared_envs)
    if missing_envs:
        checks.append(
            result(
                "env_gates_match_usage",
                "FAIL",
                f"Undeclared env gates: {', '.join(missing_envs)}",
            )
        )
    else:
        checks.append(result("env_gates_match_usage", "PASS"))

    referenced_bins = find_binary_references(body)
    missing_bins = sorted(binary for binary in referenced_bins if binary not in declared_bins)
    if missing_bins:
        checks.append(
            result(
                "bin_gates_declared",
                "FAIL",
                f"Undeclared binary gates: {', '.join(missing_bins)}",
            )
        )
    else:
        checks.append(result("bin_gates_declared", "PASS"))

    secret = has_secret(content)
    if secret:
        checks.append(result("no_secrets", "FAIL", f"Potential secret detected: {secret}"))
    else:
        checks.append(result("no_secrets", "PASS"))

    if "clawhub" in content.casefold():
        checks.append(result("no_clawhub_origin", "FAIL", "ClawHub references are prohibited"))
    else:
        checks.append(result("no_clawhub_origin", "PASS"))

    if frontmatter.get("version"):
        checks.append(result("version_present", "PASS"))
    else:
        checks.append(result("version_present", "FAIL", "version is required"))

    scenarios_path = skill_path.parent / "tests" / "scenarios.yaml"
    if scenarios_path.exists():
        checks.append(result("scenarios_exist", "PASS"))
    else:
        checks.append(result("scenarios_exist", "FAIL", f"Missing {scenarios_path.name}"))

    if isinstance(description, str) and TRIGGER_DESCRIPTION_PATTERN.search(description):
        checks.append(result("description_is_trigger_phrase", "PASS"))
    else:
        checks.append(
            result(
                "description_is_trigger_phrase",
                "FAIL",
                "description should begin with a trigger phrase such as 'Use when'",
            )
        )

    return checks
