from __future__ import annotations

from typing import Any

from clawspec.interfaces import AgentInterface


def trigger_target(
    interface: AgentInterface,
    *,
    target_id: str,
    message: str,
    timeout: int = 60,
    **kwargs: Any,
) -> dict[str, Any]:
    return interface.invoke(target_id, message, timeout=timeout, **kwargs)
