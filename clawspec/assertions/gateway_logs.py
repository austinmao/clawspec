from __future__ import annotations

import re
from typing import Any

from .common import load_text

TOOL_PATTERN = re.compile(
    r"run_id=(?P<run_id>\S+).*tool=(?P<tool>\S+).*agent=(?P<agent>\S+)(?:.*params\.agentId=(?P<target_agent>\S+))?(?:.*child_run_id=(?P<child_run_id>\S+))?"
)
SESSION_PATTERN = re.compile(r"run_id=(?P<run_id>\S+).*session_started agent=(?P<agent>\S+)")
TOKEN_PATTERN = re.compile(
    r"run_id=(?P<run_id>\S+).*token_usage "
    r"input=(?P<input>\d+) output=(?P<output>\d+) total=(?P<total>\d+)"
)


def _lines(path_pattern: str) -> list[str]:
    _, text = load_text(path_pattern)
    return text.splitlines() if text else []


def parse_tool_calls(path_pattern: str, *, run_id: str | None = None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in _lines(path_pattern):
        match = TOOL_PATTERN.search(line)
        if not match:
            continue
        payload = match.groupdict()
        if run_id and payload["run_id"] != run_id:
            continue
        entries.append(payload)
    return entries


def parse_sessions(path_pattern: str, *, run_id: str | None = None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in _lines(path_pattern):
        match = SESSION_PATTERN.search(line)
        if not match:
            continue
        payload = match.groupdict()
        if run_id and payload["run_id"] != run_id:
            continue
        entries.append(payload)
    return entries


def parse_token_usage(path_pattern: str, *, run_id: str | None = None) -> dict[str, int] | None:
    for line in _lines(path_pattern):
        match = TOKEN_PATTERN.search(line)
        if not match:
            continue
        payload = match.groupdict()
        if run_id and payload["run_id"] != run_id:
            continue
        return {
            "input": int(payload["input"]),
            "output": int(payload["output"]),
            "total": int(payload["total"]),
        }
    return None
