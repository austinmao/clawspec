from __future__ import annotations

import re
from pathlib import Path

from .common import has_secret, read_text, result

REQUIRED_HEADINGS = [
    "Who I Am",
    "Core Principles",
    "Boundaries",
    "Communication Style",
    "Security Rules",
]
CONTRADICTION_RULES = (
    ("never send email", "always send email"),
    ("do not send email", "always send email"),
    ("never publish", "always publish"),
)


def _has_heading(text: str, heading: str) -> bool:
    return re.search(rf"^#+\s+{re.escape(heading)}\s*$", text, re.MULTILINE) is not None


def _section_text(text: str, heading: str) -> str:
    pattern = re.compile(
        rf"^#+\s+{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^#+\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group("body").strip() if match else ""


def _load_companion_rules(agent_path: Path) -> str:
    for filename in ("OPERATIONS.md", "AGENTS.md", "RULES.md"):
        candidate = agent_path.parent / filename
        if candidate.exists():
            return read_text(candidate).casefold()
    return ""


def run_agent_checks(path: str | Path) -> list[dict[str, str | None]]:
    soul_path = Path(path)
    content = read_text(soul_path)
    lowered = content.casefold()
    checks: list[dict[str, str | None]] = []

    missing_sections = [
        heading for heading in REQUIRED_HEADINGS if not _has_heading(content, heading)
    ]
    if missing_sections:
        checks.append(
            result(
                "required_sections",
                "FAIL",
                f"Missing sections: {', '.join(missing_sections)}",
            )
        )
    else:
        checks.append(result("required_sections", "PASS"))

    security_rules = _section_text(content, "Security Rules")
    if security_rules:
        checks.append(result("security_block", "PASS"))
    else:
        checks.append(result("security_block", "FAIL", "Missing Security Rules section"))

    if "<user_data>" in content and "</user_data>" in content:
        checks.append(result("user_data_tags", "PASS"))
    else:
        checks.append(
            result(
                "user_data_tags",
                "FAIL",
                "Security rules must cover <user_data> handling",
            )
        )

    secret = has_secret(content)
    if secret:
        checks.append(result("no_secrets", "FAIL", f"Potential secret detected: {secret}"))
    else:
        checks.append(result("no_secrets", "PASS"))

    if _has_heading(content, "Memory"):
        checks.append(result("memory_section", "PASS"))
    else:
        checks.append(result("memory_section", "FAIL", "Missing Memory section"))

    companion_rules = _load_companion_rules(soul_path)
    contradiction_found = any(
        negative in lowered and positive in companion_rules
        for negative, positive in CONTRADICTION_RULES
    )
    if contradiction_found:
        checks.append(
            result(
                "no_contradictions",
                "WARN",
                "Companion operational rules contradict the agent identity file",
            )
        )
    else:
        checks.append(result("no_contradictions", "PASS"))

    boundaries = _section_text(content, "Boundaries") or _section_text(content, "Scope Limits")
    if re.search(r"^- (I never|I do not|Never|Do not|Not authorized)", boundaries, re.MULTILINE):
        checks.append(result("scope_limits", "PASS"))
    else:
        checks.append(
            result(
                "scope_limits",
                "FAIL",
                "Boundaries must include explicit scope limits",
            )
        )

    return checks
