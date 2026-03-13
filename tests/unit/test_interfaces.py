from __future__ import annotations

from clawspec import interfaces as interfaces_module
from clawspec.interfaces import OpenClawInterface


def test_openclaw_interface_includes_skill_identity_in_webhook_body(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        content = b'{"ok":true,"runId":"run-123"}'

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"ok": True, "runId": "run-123"}

    class _Client:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, url, *, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _Response()

    monkeypatch.setattr(interfaces_module.httpx, "Client", _Client)

    interface = OpenClawInterface(gateway_url="http://127.0.0.1:19011", token="token-123")
    result = interface.invoke(
        "/newsletter-brief",
        "/newsletter-brief Sunday Service",
        timeout=240,
        target_type="skill",
        params={"test_mode": True},
        trigger="/newsletter-brief",
        target_path="skills/newsletter/sub-skills/brief",
        target_skill_name="newsletter-brief",
    )

    assert result["run_id"] == "run-123"
    assert captured["url"] == "http://127.0.0.1:19011/webhook/mcp-skill-invoke"
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer token-123",
    }
    assert captured["json"] == {
        "skill_command": "/newsletter-brief Sunday Service",
        "payload": '{"test_mode": true}',
        "test_mode": True,
        "target_path": "skills/newsletter/sub-skills/brief",
        "target_type": "skill",
        "target_skill_name": "newsletter-brief",
    }
    assert captured["timeout"] == 240.0
