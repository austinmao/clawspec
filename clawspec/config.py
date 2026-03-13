from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

_ENV_MAP = {
    "gateway_base_url": "CLAWSPEC_GATEWAY_BASE_URL",
    "gateway_webhook_endpoint": "CLAWSPEC_GATEWAY_WEBHOOK_ENDPOINT",
    "gateway_auth_token": "CLAWSPEC_GATEWAY_AUTH_TOKEN",
    "openclaw_profile": "CLAWSPEC_OPENCLAW_PROFILE",
    "report_dir": "CLAWSPEC_REPORT_DIR",
    "gateway_log_pattern": "CLAWSPEC_GATEWAY_LOG_PATTERN",
    "scenario_patterns": "CLAWSPEC_SCENARIO_PATTERNS",
    "ledger_path": "CLAWSPEC_LEDGER_PATH",
}


def _cwd() -> Path:
    return Path.cwd().resolve()


def _discover_config(start: Path) -> Path | None:
    for directory in (start, *start.parents):
        candidate = directory / "clawspec.yaml"
        if candidate.exists():
            return candidate
    return None


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a top-level mapping")
    return payload


@dataclass
class ClawspecConfig:
    gateway_base_url: str = "http://127.0.0.1:18789"
    gateway_webhook_endpoint: str = "/webhook/mcp-skill-invoke"
    gateway_auth_token: str | None = None
    openclaw_profile: str | None = None
    report_dir: Path = Path("reports")
    gateway_log_pattern: str = "/tmp/openclaw/openclaw-{date}.log"
    scenario_patterns: list[str] = field(
        default_factory=lambda: [
            "skills/**/tests/scenarios.yaml",
            "agents/**/tests/scenarios.yaml",
        ]
    )
    ledger_path: Path = Path("coverage-ledger.yaml")
    root_dir: Path = field(default_factory=_cwd)

    @classmethod
    def load(
        cls,
        path: str | Path | None = None,
        *,
        start: str | Path | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> ClawspecConfig:
        start_dir = Path(start).resolve() if start is not None else _cwd()
        config_path = Path(path).resolve() if path is not None else _discover_config(start_dir)
        root_dir = config_path.parent if config_path is not None else start_dir
        data: dict[str, Any] = {}
        if config_path is not None:
            data = _load_yaml(config_path)

        env_values: dict[str, Any] = {}
        for field_name, env_name in _ENV_MAP.items():
            value = os.environ.get(env_name)
            if value is None:
                continue
            if field_name == "scenario_patterns":
                env_values[field_name] = [item.strip() for item in value.split(",") if item.strip()]
            else:
                env_values[field_name] = value

        if "gateway_auth_token" not in env_values:
            fallback_token = os.environ.get("HOOKS_TOKEN") or os.environ.get("OPENCLAW_HOOKS_TOKEN")
            if fallback_token:
                env_values["gateway_auth_token"] = fallback_token

        merged = {**data, **env_values, **(overrides or {})}
        merged["root_dir"] = root_dir
        if "report_dir" in merged:
            merged["report_dir"] = Path(merged["report_dir"])
        if "ledger_path" in merged:
            merged["ledger_path"] = Path(merged["ledger_path"])
        return cls(**merged)

    def resolve_path(self, path: str | Path) -> Path:
        value = Path(path)
        if value.is_absolute():
            return value
        return (self.root_dir / value).resolve()

    def with_overrides(self, **kwargs: Any) -> ClawspecConfig:
        return replace(self, **kwargs)
