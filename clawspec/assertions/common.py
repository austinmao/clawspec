from __future__ import annotations

import glob
import json
import time
from pathlib import Path
from typing import Any

import yaml


def elapsed(start: float) -> str:
    return f"{time.perf_counter() - start:.2f}s"


def outcome(name: str, status: str, detail: str | None = None, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "status": status, "detail": detail}
    payload.update(extra)
    return payload


def matching_paths(path_pattern: str) -> list[Path]:
    return [Path(match) for match in sorted(glob.glob(path_pattern))]


def load_text(path_pattern: str) -> tuple[Path | None, str | None]:
    matches = matching_paths(path_pattern)
    if not matches:
        candidate = Path(path_pattern)
        if candidate.exists():
            return candidate, candidate.read_text(encoding="utf-8")
        return None, None
    path = matches[0]
    return path, path.read_text(encoding="utf-8")


def load_structured(path_pattern: str) -> tuple[Path | None, dict[str, Any] | None]:
    path, text = load_text(path_pattern)
    if path is None or text is None:
        return None, None
    if path.suffix == ".json":
        payload = json.loads(text)
    else:
        payload = yaml.safe_load(text)
    return path, payload if isinstance(payload, dict) else None


def resolve_key_path(payload: dict[str, Any], dotted_key: str) -> Any:
    current: Any = payload
    for key in dotted_key.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current
