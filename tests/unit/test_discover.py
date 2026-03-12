from __future__ import annotations

import json
from pathlib import Path

from clawspec.runner.discover import discover_scenarios, main


def _write_scenarios(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_discover_scenarios_recursively_finds_skill_and_agent_entries(tmp_path: Path) -> None:
    _write_scenarios(
        tmp_path / "skills/newsletter/tests/scenarios.yaml",
        """version: "1.0"
target:
  type: skill
  path: skills/newsletter
  trigger: /send-newsletter
scenarios:
  - name: newsletter-smoke
    tags: [smoke, p0]
    when:
      invoke: /send-newsletter
    then:
      - type: artifact_exists
        path: memory/drafts/out.md
""",
    )
    _write_scenarios(
        tmp_path / "agents/marketing/brand/tests/scenarios.yaml",
        """version: "1.0"
target:
  type: agent
  path: agents/marketing/brand
  trigger: 'sessions_spawn(agentId: "agents-marketing-brand")'
scenarios:
  - name: brand-negative
    tags: [negative, smoke]
    when:
      invoke: sessions_spawn
    then:
      - type: tool_not_called
        tool: resend.send
""",
    )

    discovered = discover_scenarios(repo_root=tmp_path)

    assert [item["name"] for item in discovered] == ["brand-negative", "newsletter-smoke"]
    assert discovered[0]["target_type"] == "agent"
    assert discovered[0]["target_path"] == "agents/marketing/brand"
    assert discovered[0]["scenario_file"] == str(
        (tmp_path / "agents/marketing/brand/tests/scenarios.yaml").resolve()
    )


def test_discover_scenarios_filters_by_target_and_tags(tmp_path: Path) -> None:
    _write_scenarios(
        tmp_path / "skills/newsletter/tests/scenarios.yaml",
        """version: "1.0"
target:
  type: skill
  path: skills/newsletter
  trigger: /send-newsletter
scenarios:
  - name: smoke-only
    tags: [smoke]
    when:
      invoke: /send-newsletter
    then:
      - type: artifact_exists
        path: memory/drafts/out.md
  - name: regression-only
    tags: [regression]
    when:
      invoke: /send-newsletter
    then:
      - type: artifact_exists
        path: memory/drafts/out.md
""",
    )
    _write_scenarios(
        tmp_path / "agents/marketing/brand/tests/scenarios.yaml",
        """version: "1.0"
target:
  type: agent
  path: agents/marketing/brand
  trigger: 'sessions_spawn(agentId: "agents-marketing-brand")'
scenarios:
  - name: brand-smoke
    tags: [smoke]
    when:
      invoke: sessions_spawn
    then:
      - type: tool_not_called
        tool: resend.send
""",
    )

    target_filtered = discover_scenarios(repo_root=tmp_path, target="newsletter")
    tag_filtered = discover_scenarios(repo_root=tmp_path, tags=["smoke"])

    assert [item["name"] for item in target_filtered] == ["smoke-only", "regression-only"]
    assert [item["name"] for item in tag_filtered] == ["brand-smoke", "smoke-only"]


def test_discover_main_outputs_json(tmp_path: Path, capsys) -> None:
    _write_scenarios(
        tmp_path / "skills/qa/evaluate/tests/scenarios.yaml",
        """version: "1.0"
target:
  type: skill
  path: skills/qa/evaluate
  trigger: /evaluate
scenarios:
  - name: evaluate-smoke
    tags: [smoke]
    when:
      invoke: /evaluate tests/fixtures/valid_scenario.yaml
    then:
      - type: artifact_exists
        path: memory/logs/qa/report.yaml
""",
    )

    exit_code = main(["--repo-root", str(tmp_path), "--target", "evaluate"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload[0]["target_name"] == "evaluate"
    assert payload[0]["tags"] == ["smoke"]
