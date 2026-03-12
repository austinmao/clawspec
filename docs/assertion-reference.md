# Assertion Reference

ClawSpec v0.1 ships 19 assertion types.

## Preconditions

| Type | Required fields | Example |
|---|---|---|
| `file_present` | `path` | `- {type: file_present, path: SKILL.md}` |
| `file_absent` | `path` | `- {type: file_absent, path: memory/drafts/{{today}}-output.md}` |
| `gateway_healthy` | none | `- {type: gateway_healthy}` |
| `env_present` | `vars` | `- {type: env_present, vars: [RESEND_API_KEY]}` |

## Integration

| Type | Required fields | Example |
|---|---|---|
| `gateway_response` | `endpoint`, `expected_status` | `- {type: gateway_response, endpoint: http://127.0.0.1:18789/health, expected_status: 200}` |

## Artifact

| Type | Required fields | Example |
|---|---|---|
| `artifact_exists` | `path` | `- {type: artifact_exists, path: memory/drafts/{{today}}-output.md}` |
| `artifact_contains` | `path` plus `sections` or `fields` | `- {type: artifact_contains, path: memory/drafts/{{today}}-output.md, sections: [hook, cta]}` |
| `artifact_absent_words` | `path` plus `words` or `source` and `key` | `- {type: artifact_absent_words, path: memory/drafts/{{today}}-output.md, words: [urgent, guaranteed]}` |
| `artifact_matches_golden` | `path`, `golden` | `- {type: artifact_matches_golden, path: memory/drafts/{{today}}-output.md, golden: tests/golden/output.md}` |
| `state_file` | `path` or `state_path` | `- {type: state_file, path: memory/state.yaml, expected_status: ready}` |

## Behavioral

| Type | Required fields | Example |
|---|---|---|
| `log_entry` | `path`, `pattern` | `- {type: log_entry, path: memory/logs/run.log, pattern: \"approved\"}` |
| `decision_routed_to` | `state_path`, `expected_agent` | `- {type: decision_routed_to, state_path: memory/router-state.yaml, expected_agent: agents/marketing/brand}` |

## Tool and Handoff

| Type | Required fields | Example |
|---|---|---|
| `tool_was_called` | `tool`, `log_path`, `run_id` | `- {type: tool_was_called, tool: sessions_spawn, log_path: /tmp/openclaw/openclaw-{{today}}.log, run_id: \"{{run_id}}\"}` |
| `tool_not_called` | `tool`, `log_path`, `run_id` | `- {type: tool_not_called, tool: resend.send, log_path: /tmp/openclaw/openclaw-{{today}}.log, run_id: \"{{run_id}}\"}` |
| `delegation_occurred` | `to_agent`, `log_path`, `run_id` | `- {type: delegation_occurred, to_agent: agents-marketing-brand, log_path: /tmp/openclaw/openclaw-{{today}}.log, run_id: \"{{run_id}}\"}` |

## Permission and Operations

| Type | Required fields | Example |
|---|---|---|
| `tool_not_permitted` | `allowed_tools`, `log_path`, `run_id` | `- {type: tool_not_permitted, allowed_tools: [read, write], log_path: /tmp/openclaw/openclaw-{{today}}.log, run_id: \"{{run_id}}\"}` |
| `token_budget` | `log_path`, `run_id` plus at least one max field | `- {type: token_budget, log_path: /tmp/openclaw/openclaw-{{today}}.log, run_id: \"{{run_id}}\", max_total_tokens: 12000}` |

## Semantic

| Type | Required fields | Example |
|---|---|---|
| `llm_judge` | `path`, `rubric` | `- {type: llm_judge, path: memory/drafts/{{today}}-output.md, rubric: \"Score 1-5: Is this clear and safe?\"}` |
| `agent_identity_consistent` | `output_path`, `soul_path` | `- {type: agent_identity_consistent, output_path: memory/drafts/{{today}}-output.md, soul_path: agents/marketing/brand/SOUL.md}` |

## Notes

- Most artifact assertions also accept `timeout` and `updated_after`.
- `llm_judge` accepts `pass_threshold`, `section`, and `consistency`.
- `artifact_matches_golden` uses a ROUGE-style threshold via `rouge_threshold`.
- `state_file` also accepts `expected_fields`.

