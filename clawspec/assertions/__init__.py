from __future__ import annotations

from collections.abc import Callable
from typing import Any

AssertionHandler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
_REGISTRY: dict[str, AssertionHandler] = {}
SHIPPED_ASSERTION_TYPES = (
    "file_present",
    "file_absent",
    "gateway_healthy",
    "env_present",
    "gateway_response",
    "artifact_exists",
    "artifact_contains",
    "artifact_absent_words",
    "artifact_matches_golden",
    "state_file",
    "log_entry",
    "decision_routed_to",
    "llm_judge",
    "tool_was_called",
    "tool_not_called",
    "delegation_occurred",
    "agent_identity_consistent",
    "token_budget",
    "tool_not_permitted",
)


class AssertionDispatchError(KeyError):
    """Raised when an assertion type has no registered handler."""


def register_assertion(assertion_type: str, handler: AssertionHandler) -> None:
    _REGISTRY[assertion_type] = handler


def get_registered_assertions() -> dict[str, AssertionHandler]:
    load_default_assertions()
    return dict(_REGISTRY)


def load_default_assertions() -> None:
    if _REGISTRY:
        return
    from .artifact import HANDLERS as artifact_handlers
    from .behavioral import HANDLERS as behavioral_handlers
    from .handoff import HANDLERS as handoff_handlers
    from .identity import HANDLERS as identity_handlers
    from .integration import HANDLERS as integration_handlers
    from .operational import HANDLERS as operational_handlers
    from .permission import HANDLERS as permission_handlers
    from .precondition import HANDLERS as precondition_handlers
    from .semantic import HANDLERS as semantic_handlers
    from .tool import HANDLERS as tool_handlers

    for mapping in (
        precondition_handlers,
        integration_handlers,
        artifact_handlers,
        behavioral_handlers,
        semantic_handlers,
        tool_handlers,
        handoff_handlers,
        identity_handlers,
        operational_handlers,
        permission_handlers,
    ):
        _REGISTRY.update(mapping)


def dispatch_assertion(assertion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    load_default_assertions()
    assertion_type = assertion.get("type")
    if not assertion_type:
        raise AssertionDispatchError("Assertion is missing a type")
    try:
        handler = _REGISTRY[assertion_type]
    except KeyError as exc:
        raise AssertionDispatchError(f"Unknown assertion type: {assertion_type}") from exc

    result = handler(assertion, context)
    if "name" not in result:
        result["name"] = assertion_type
    return result
