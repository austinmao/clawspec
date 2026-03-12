from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TEMPLATE_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")
DEFAULT_QA_INBOX = "lumina.qa@agentmail.to"
ALLOWED_VARIABLES = frozenset(
    {
        "today",
        "now",
        "repo_root",
        "qa_inbox",
        "run_id",
        "run_started_at",
        "handoff.from",
        "handoff.to",
        "callee_run_id",
    }
)


class TemplateExpansionError(ValueError):
    """Raised when a template variable is invalid or missing from context."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _format_now(value: datetime) -> str:
    normalized = value.astimezone(UTC).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def build_template_context(
    *,
    repo_root: str | Path | None = None,
    now: datetime | None = None,
    qa_inbox: str = DEFAULT_QA_INBOX,
    extra: dict[str, Any] | None = None,
) -> dict[str, str]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    context = {
        "today": current.date().isoformat(),
        "now": _format_now(current),
        "repo_root": str(Path(repo_root) if repo_root is not None else _repo_root()),
        "qa_inbox": qa_inbox,
    }
    if extra:
        context.update({key: str(value) for key, value in extra.items()})
    return context


def iter_template_variables(value: Any) -> list[str]:
    variables: list[str] = []
    if isinstance(value, str):
        variables.extend(match.group(1).strip() for match in TEMPLATE_PATTERN.finditer(value))
    elif isinstance(value, list):
        for item in value:
            variables.extend(iter_template_variables(item))
    elif isinstance(value, dict):
        for item in value.values():
            variables.extend(iter_template_variables(item))
    return variables


def _expand_string(value: str, context: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        variable = match.group(1).strip()
        if variable not in ALLOWED_VARIABLES:
            raise TemplateExpansionError(f"Unknown template variable: {variable}")
        if variable not in context:
            raise TemplateExpansionError(f"Missing template value for: {variable}")
        return context[variable]

    return TEMPLATE_PATTERN.sub(replace, value)


def expand_templates(value: Any, context: dict[str, str]) -> Any:
    if isinstance(value, str):
        return _expand_string(value, context)
    if isinstance(value, list):
        return [expand_templates(item, context) for item in value]
    if isinstance(value, dict):
        return {key: expand_templates(item, context) for key, item in value.items()}
    return value
