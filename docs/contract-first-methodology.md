# Contract-First Methodology

ClawSpec treats QA contracts as the source of truth for OpenClaw behavior.

## Core loop

```text
Write contract -> RED -> implement -> GREEN -> refactor
```

The contract is executable documentation:

- `given`: preconditions
- `when`: trigger invocation
- `then`: deterministic and semantic assertions

## Contract surfaces

| Surface | File |
|---|---|
| Skill or agent scenario | `tests/scenarios.yaml` |
| Handoff | `tests/handoffs/*.yaml` |
| Pipeline | `tests/pipeline.yaml` |
| Structure | `SKILL.md` / `SOUL.md` |

## Assertion categories

- Deterministic assertions should block the run on failure.
- Semantic assertions should surface quality drift as warnings.

Recommended split:

- Deterministic: artifact, tool, permission, precondition, integration, handoff, routing
- Semantic: `llm_judge`, `agent_identity_consistent`

## Negative coverage

Every skill or agent should have at least one scenario tagged `negative`.

```yaml
- name: rejects-out-of-scope
  tags: [negative]
  when:
    invoke: /my-skill forbidden request
    params:
      test_mode: true
  then:
    - type: tool_not_called
      tool: send_message
```

## Template variables

ClawSpec expands variables in paths and invocation payloads:

- `{{today}}`
- `{{now}}`
- `{{repo_root}}`
- `{{run_id}}`
- `{{qa_inbox}}`

## Exit codes

| Code | Meaning |
|---|---|
| `0` | pass |
| `1` | deterministic failure or coverage gaps |
| `2` | runtime or usage error |
| `3` | schema error |

