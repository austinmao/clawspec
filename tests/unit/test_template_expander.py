from datetime import UTC, datetime

import pytest

from clawspec.templates.expander import (
    TemplateExpansionError,
    build_template_context,
    expand_templates,
)


def test_expand_known_variables() -> None:
    context = build_template_context(
        repo_root="/repo/root",
        now=datetime(2026, 3, 11, 14, 22, tzinfo=UTC),
        qa_inbox="qa@example.com",
        extra={
            "run_id": "run-123",
            "handoff.from": "agents-marketing-orchestrator",
            "handoff.to": "agents-marketing-brand",
            "callee_run_id": "run-456",
        },
    )

    expanded = expand_templates(
        {
            "today": "{{today}}",
            "now": "{{now}}",
            "repo_root": "{{repo_root}}",
            "qa_inbox": "{{qa_inbox}}",
            "run_id": "{{run_id}}",
            "handoff": ["{{handoff.from}}", "{{handoff.to}}", "{{callee_run_id}}"],
        },
        context,
    )

    assert expanded == {
        "today": "2026-03-11",
        "now": "2026-03-11T14:22:00Z",
        "repo_root": "/repo/root",
        "qa_inbox": "qa@example.com",
        "run_id": "run-123",
        "handoff": [
            "agents-marketing-orchestrator",
            "agents-marketing-brand",
            "run-456",
        ],
    }


def test_unknown_variable_is_rejected() -> None:
    context = build_template_context(
        repo_root="/repo/root",
        now=datetime(2026, 3, 11, 14, 22, tzinfo=UTC),
    )

    with pytest.raises(TemplateExpansionError, match="unknown.variable"):
        expand_templates("{{unknown.variable}}", context)
