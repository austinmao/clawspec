from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import httpx

from .exceptions import GatewayError, TriggerTimeoutError


class AgentInterface(Protocol):
    def list_agents(self) -> list[dict[str, str]]:
        """Return registered agents as [{id, workspace, name}]."""

    def invoke(
        self, agent_id: str, message: str, *, timeout: int = 60, **kwargs: Any
    ) -> dict[str, Any]:
        """Invoke a skill or agent and return a structured response."""

    def health_check(self) -> bool:
        """Return True when the runtime is reachable."""


class OpenClawInterface:
    def __init__(
        self,
        gateway_url: str = "http://127.0.0.1:18789",
        token: str | None = None,
        *,
        webhook_endpoint: str = "/webhook/mcp-skill-invoke",
        cwd: str | Path | None = None,
    ) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.token = token
        self.webhook_endpoint = webhook_endpoint
        self.cwd = Path(cwd).resolve() if cwd is not None else None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def list_agents(self) -> list[dict[str, str]]:
        if shutil.which("openclaw") is None:
            return []
        try:
            result = subprocess.run(
                ["openclaw", "agents", "list", "--json"],
                check=True,
                capture_output=True,
                text=True,
                cwd=str(self.cwd) if self.cwd else None,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            return []
        return payload if isinstance(payload, list) else []

    def invoke(
        self, agent_id: str, message: str, *, timeout: int = 60, **kwargs: Any
    ) -> dict[str, Any]:
        target_type = kwargs.get("target_type", "agent")
        if target_type == "agent":
            return self._invoke_agent(
                agent_id, message, timeout=timeout, repo_root=kwargs.get("repo_root")
            )
        return self._invoke_skill(
            agent_id,
            message,
            timeout=timeout,
            params=kwargs.get("params"),
            trigger=kwargs.get("trigger"),
            requested_session_key=kwargs.get("requested_session_key"),
        )

    def _invoke_agent(
        self,
        agent_id: str,
        message: str,
        *,
        timeout: int,
        repo_root: str | Path | None,
    ) -> dict[str, Any]:
        if shutil.which("openclaw") is None:
            raise GatewayError("openclaw CLI is not available for agent invocation")
        try:
            result = subprocess.run(
                [
                    "openclaw",
                    "agent",
                    "--local",
                    "--agent",
                    agent_id,
                    "--message",
                    message,
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
                cwd=str(Path(repo_root).resolve())
                if repo_root is not None
                else str(self.cwd)
                if self.cwd
                else None,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise TriggerTimeoutError(f"Agent invocation timed out after {timeout}s") from exc
        except subprocess.CalledProcessError as exc:
            raise GatewayError(exc.stderr.strip() or exc.stdout.strip() or str(exc)) from exc
        payload = _parse_json_payload(result.stdout or "{}")
        run_id = (
            payload.get("meta", {}).get("agentMeta", {}).get("sessionId")
            if isinstance(payload.get("meta"), dict)
            else None
        )
        return {"status": "completed", "run_id": run_id or str(uuid4()), "response": payload}

    def _invoke_skill(
        self,
        skill_command: str,
        message: str,
        *,
        timeout: int,
        params: dict[str, Any] | None = None,
        trigger: str | None = None,
        requested_session_key: str | None = None,
    ) -> dict[str, Any]:
        invoke = message.strip()
        payload_params = params or {}
        if invoke.startswith("/"):
            body: dict[str, Any] = {
                "skill_command": invoke,
                "payload": json.dumps(payload_params, sort_keys=True) if payload_params else "",
                "test_mode": bool(payload_params.get("test_mode", True)),
            }
        else:
            body = {
                "skill_command": trigger or skill_command,
                "payload": json.dumps({"invoke": invoke, "params": payload_params}, sort_keys=True),
                "test_mode": bool(payload_params.get("test_mode", True)),
            }
        if requested_session_key:
            body["session_key"] = requested_session_key

        endpoint = f"{self.gateway_url}{self.webhook_endpoint}"
        try:
            with httpx.Client(timeout=float(timeout)) as client:
                response = client.post(endpoint, headers=self._headers(), json=body)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise TriggerTimeoutError(f"Skill invocation timed out after {timeout}s") from exc
        except httpx.HTTPError as exc:
            raise GatewayError(str(exc)) from exc
        payload = response.json() if response.content else {}
        if not isinstance(payload, dict):
            payload = {}
        return {
            "status": payload.get("status", "accepted"),
            "run_id": payload.get("runId") or payload.get("run_id") or str(uuid4()),
            "response": payload,
        }

    def health_check(self) -> bool:
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.gateway_url}/health", headers=self._headers())
                return response.status_code == 200
        except httpx.HTTPError:
            return False


def _parse_json_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {}
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < start:
            raise GatewayError("Expected JSON object payload") from exc
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise GatewayError("Expected JSON object payload")
    return payload
