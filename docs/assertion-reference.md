# Assertion Reference

ClawSpec ships 29 assertion types across five categories.

- **Precondition** (4) — validate the environment before running
- **Artifact** (5) — inspect files written by the agent
- **Behavioral** (8) — inspect logs, routing decisions, and tool calls
- **Trace** (10) — inspect live execution data from observability (requires observability backend)
- **Semantic** (2) — LLM-graded quality checks

---

## Precondition Assertions

Preconditions run before the scenario step and abort early if they fail. Use them to avoid false negatives caused by missing environment setup.

### `file_present`

Asserts a file exists at the given path.

| Field | Required | Description |
|---|---|---|
| `path` | yes | Path to check. Supports `{{today}}` template. |

```yaml
- type: file_present
  path: SKILL.md
```

### `file_absent`

Asserts a file does not exist. Use to verify cleanup or ensure a stale artifact does not carry over.

| Field | Required | Description |
|---|---|---|
| `path` | yes | Path that must not exist. Supports templates. |

```yaml
- type: file_absent
  path: memory/drafts/{{today}}-output.md
```

### `gateway_healthy`

Asserts the gateway responds with HTTP 200 on its health endpoint. No fields required.

```yaml
- type: gateway_healthy
```

### `env_present`

Asserts that one or more environment variables are set (non-empty).

| Field | Required | Description |
|---|---|---|
| `vars` | yes | List of environment variable names. |

```yaml
- type: env_present
  vars: [RESEND_API_KEY, ATTIO_API_KEY]
```

---

## Artifact Assertions

Artifact assertions inspect files produced by the agent during the scenario step.

### `artifact_exists`

Asserts a file exists after the step completes.

| Field | Required | Description |
|---|---|---|
| `path` | yes | File path to check. |
| `timeout` | no | Seconds to wait for the file to appear (default: 0). |
| `updated_after` | no | ISO timestamp; asserts the file was modified after this time. |

```yaml
- type: artifact_exists
  path: memory/drafts/{{today}}-output.md
```

### `artifact_contains`

Asserts a file contains required sections (heading names) or required fields (YAML keys).

| Field | Required | Description |
|---|---|---|
| `path` | yes | File path to inspect. |
| `sections` | one of | List of strings that must appear as headings in the file. |
| `fields` | one of | List of YAML keys that must be present. |
| `timeout` | no | Seconds to wait for the file before failing. |

```yaml
- type: artifact_contains
  path: memory/drafts/{{today}}-output.md
  sections: [hook, body, cta]
```

### `artifact_absent_words`

Asserts that certain words or phrases do not appear in the file. Useful for brand safety and tone enforcement.

| Field | Required | Description |
|---|---|---|
| `path` | yes | File path to inspect. |
| `words` | one of | List of words or phrases to check for absence. |
| `source` + `key` | one of | Load the word list from a YAML file at `source`, under `key`. |

```yaml
- type: artifact_absent_words
  path: memory/drafts/{{today}}-output.md
  words: [urgent, guaranteed, limited time]
```

### `artifact_matches_golden`

Asserts a file's content is similar enough to a golden reference file using ROUGE-style scoring.

| Field | Required | Description |
|---|---|---|
| `path` | yes | File path to compare. |
| `golden` | yes | Path to the golden reference file. |
| `rouge_threshold` | no | Minimum ROUGE similarity score (default: 0.7). |

```yaml
- type: artifact_matches_golden
  path: memory/drafts/{{today}}-output.md
  golden: tests/golden/email-output.md
  rouge_threshold: 0.8
```

### `state_file`

Asserts a YAML state file contains an expected status or set of fields.

| Field | Required | Description |
|---|---|---|
| `path` or `state_path` | yes | Path to the YAML state file. |
| `expected_status` | no | Value that the `status` key must equal. |
| `expected_fields` | no | Dict of key-value pairs that must be present. |

```yaml
- type: state_file
  path: memory/state.yaml
  expected_status: ready
  expected_fields:
    phase: complete
    retries: 0
```

---

## Behavioral Assertions

Behavioral assertions inspect gateway logs, routing state, tool invocations, and permission records.

### `gateway_response`

Makes a live HTTP request to an endpoint and asserts the response status code.

| Field | Required | Description |
|---|---|---|
| `endpoint` | yes | Full URL to request. |
| `expected_status` | yes | Expected HTTP status code (integer). |

```yaml
- type: gateway_response
  endpoint: http://127.0.0.1:18789/health
  expected_status: 200
```

### `log_entry`

Asserts a log file contains at least one line matching a pattern.

| Field | Required | Description |
|---|---|---|
| `path` | yes | Log file path. Supports `{{today}}` template. |
| `pattern` | yes | Substring or regex pattern to search for. |

```yaml
- type: log_entry
  path: memory/logs/run.log
  pattern: "approved"
```

### `decision_routed_to`

Asserts that a routing state file records a decision to a specific agent.

| Field | Required | Description |
|---|---|---|
| `state_path` | yes | Path to the YAML router state file. |
| `expected_agent` | yes | Agent ID or path that must appear as the routing decision. |

```yaml
- type: decision_routed_to
  state_path: memory/router-state.yaml
  expected_agent: agents/marketing/brand
```

### `tool_was_called`

Asserts a specific tool appears in the gateway log for a given run.

| Field | Required | Description |
|---|---|---|
| `tool` | yes | Tool name to look for. |
| `log_path` | yes | Path to the gateway log file. |
| `run_id` | yes | Run ID to scope the search. |

```yaml
- type: tool_was_called
  tool: sessions_spawn
  log_path: /tmp/openclaw/openclaw-{{today}}.log
  run_id: "{{run_id}}"
```

### `tool_not_called`

Asserts a specific tool does not appear in the gateway log for a given run. Use to enforce that certain tools (e.g., `resend.send`) are not invoked during test runs.

| Field | Required | Description |
|---|---|---|
| `tool` | yes | Tool name that must not appear. |
| `log_path` | yes | Path to the gateway log file. |
| `run_id` | yes | Run ID to scope the search. |

```yaml
- type: tool_not_called
  tool: resend.send
  log_path: /tmp/openclaw/openclaw-{{today}}.log
  run_id: "{{run_id}}"
```

### `delegation_occurred`

Asserts that a delegation to a named agent appears in the gateway log.

| Field | Required | Description |
|---|---|---|
| `to_agent` | yes | Agent ID to look for in the delegation record. |
| `log_path` | yes | Path to the gateway log file. |
| `run_id` | yes | Run ID to scope the search. |

```yaml
- type: delegation_occurred
  to_agent: agents-marketing-brand
  log_path: /tmp/openclaw/openclaw-{{today}}.log
  run_id: "{{run_id}}"
```

### `tool_not_permitted`

Asserts no tools outside the allowed list were invoked during the run.

| Field | Required | Description |
|---|---|---|
| `allowed_tools` | yes | List of permitted tool names. Any other tool found in the log causes a failure. |
| `log_path` | yes | Path to the gateway log file. |
| `run_id` | yes | Run ID to scope the search. |

```yaml
- type: tool_not_permitted
  allowed_tools: [read, write, memory.search]
  log_path: /tmp/openclaw/openclaw-{{today}}.log
  run_id: "{{run_id}}"
```

### `token_budget`

Asserts total token usage during the run stays within bounds. Reads token data from the gateway log.

| Field | Required | Description |
|---|---|---|
| `log_path` | yes | Path to the gateway log file. |
| `run_id` | yes | Run ID to scope the search. |
| `max_total_tokens` | one of | Maximum total token count. |
| `max_input_tokens` | one of | Maximum input token count. |
| `max_output_tokens` | one of | Maximum output token count. |

At least one `max_*` field is required.

```yaml
- type: token_budget
  log_path: /tmp/openclaw/openclaw-{{today}}.log
  run_id: "{{run_id}}"
  max_total_tokens: 12000
  max_output_tokens: 4000
```

---

## Trace Assertions

Trace assertions require an observability backend to be configured and active. They evaluate live span data retrieved from the backend after the scenario completes. If no trace is found or the backend is unavailable, all trace assertions in the scenario are marked `skip` rather than `fail`.

See [observability-integration.md](observability-integration.md) for setup instructions.

### `llm_call_count`

Asserts the number of LLM spans in the trace is within bounds.

| Field | Required | Description |
|---|---|---|
| `min` | no | Minimum number of LLM calls. |
| `max` | no | Maximum number of LLM calls. |

At least one of `min` or `max` is required.

```yaml
- type: llm_call_count
  min: 1
  max: 4
```

**Fail conditions:** `actual < min` or `actual > max`.

### `tool_sequence`

Asserts tool calls appear in the expected order. Supports three modes.

| Field | Required | Description |
|---|---|---|
| `expected` | yes | Ordered list of tool names. |
| `mode` | no | `"ordered"` (default), `"strict"`, or `"contains"`. |

**Modes:**

- `ordered` — The expected tools must appear as an ordered subsequence in the actual tool list. Other tools may appear between them.
- `strict` — The actual tool list must exactly equal the expected list (same tools, same order, nothing extra).
- `contains` — All expected tools must appear somewhere in the actual list (order and extras ignored).

```yaml
# Ordered subsequence (default)
- type: tool_sequence
  expected: [memory.search, resend.send]

# Exact match
- type: tool_sequence
  mode: strict
  expected: [memory.search, attio.read, resend.send]

# Unordered presence check
- type: tool_sequence
  mode: contains
  expected: [memory.search, attio.read]
```

### `model_used`

Asserts a specific model was or was not used in the LLM spans. Matching is by substring — `"sonnet"` matches `"claude-sonnet-4-6"`.

| Field | Required | Description |
|---|---|---|
| `expected` | one of | Model name substring that must appear in at least one LLM span. |
| `not_expected` | one of | Model name substring that must not appear in any LLM span. |

Exactly one of `expected` or `not_expected` must be provided.

```yaml
# Assert a specific model was used
- type: model_used
  expected: claude-sonnet-4-6

# Assert a prohibited model was not used
- type: model_used
  not_expected: claude-opus-4-6
```

### `delegation_path`

Asserts that sub-agent delegations followed the expected path. Uses span-level sub-agent data when available; falls back to routing state files when sub-agent spans are absent.

| Field | Required | Description |
|---|---|---|
| `expected` | yes | Ordered list of agent names. Matched as an ordered subsequence. |
| `routing_path` / `routing_decisions` / `state_path` | no | Fallback sources for routing data when no sub-agent spans are found. |

```yaml
- type: delegation_path
  expected: [orchestrator, copywriter, brand-guardian]
```

**Status `warn`** (not `fail`) is returned when no sub-agent spans are found and no fallback routing data is available. This avoids false negatives when the observability backend does not capture sub-agent spans.

### `per_span_budget`

Asserts that no individual span exceeds a token budget.

| Field | Required | Description |
|---|---|---|
| `max_tokens` | yes | Maximum token count per span. |
| `span_type` | no | Span type to filter to (default: `"llm"`). |
| `span_name` | no | Substring filter on span name. Only spans with matching names are checked. |

```yaml
- type: per_span_budget
  max_tokens: 8000
  span_type: llm

# Only check spans named like "summarize"
- type: per_span_budget
  max_tokens: 4000
  span_name: summarize
```

**Fail condition:** Any matching span has `total_tokens > max_tokens`. The report lists all violating spans with their actual token counts.

### `trace_token_budget`

Asserts the total token usage across all spans in the trace stays within bounds.

| Field | Required | Description |
|---|---|---|
| `max_input_tokens` | one of | Maximum total input tokens across all spans. |
| `max_output_tokens` | one of | Maximum total output tokens across all spans. |

At least one field is required.

```yaml
- type: trace_token_budget
  max_input_tokens: 20000
  max_output_tokens: 8000
```

### `trace_duration`

Asserts the wall-clock duration of the entire trace does not exceed a maximum.

Duration is computed from the trace envelope timestamps when available, falling back to span timestamps, then to summing individual `duration_ms` values.

| Field | Required | Description |
|---|---|---|
| `max_ms` | yes | Maximum allowed trace duration in milliseconds. |

```yaml
- type: trace_duration
  max_ms: 30000
```

### `trace_cost`

Asserts the total cost of the trace does not exceed a maximum. Uses native cost data from the backend when available; falls back to `model_pricing` estimation when not.

| Field | Required | Description |
|---|---|---|
| `max_usd` | yes | Maximum allowed cost in USD. |

```yaml
- type: trace_cost
  max_usd: 0.05
```

**Status `warn`** is returned when no cost data is available and no `model_pricing` is configured. Configure `model_pricing` in `clawspec.yaml` to enable cost estimation.

### `no_span_errors`

Asserts that no spans in the trace have an `error` field set. Catches silent failures in tool calls and sub-agent invocations that do not surface in the final artifact.

No fields required.

```yaml
- type: no_span_errors
```

**Fail condition:** Any span has a non-empty `error` value. The report lists all errored spans with their type and error message.

### `tool_not_invoked`

Asserts a specific tool was not called during the trace. This is the trace-layer complement to the log-based `tool_not_called` behavioral assertion — use this when observability is enabled and you prefer span-level verification.

| Field | Required | Description |
|---|---|---|
| `tool` | yes | Tool name that must not appear in any tool span. |

```yaml
- type: tool_not_invoked
  tool: resend.send
```

---

## Semantic Assertions

Semantic assertions use an LLM as a judge to evaluate subjective quality criteria that cannot be checked mechanically.

### `llm_judge`

Uses an LLM to score an artifact against a rubric and passes or fails based on a threshold.

| Field | Required | Description |
|---|---|---|
| `path` | yes | File path to evaluate. |
| `rubric` | yes | Scoring instruction for the LLM (e.g., `"Score 1-5: Is this clear and safe?"`). |
| `pass_threshold` | no | Minimum score to pass (default: 3 on a 1-5 scale). |
| `section` | no | Extract a specific section from the file before scoring. |
| `consistency` | no | If `true`, run multiple judge calls and require consistent results. |

```yaml
- type: llm_judge
  path: memory/drafts/{{today}}-output.md
  rubric: "Score 1-5: Is this email persuasive and brand-safe?"
  pass_threshold: 4
```

### `agent_identity_consistent`

Asserts that an agent's output is consistent with the persona and principles defined in its `SOUL.md`. Useful for catching identity drift in long-running agents.

| Field | Required | Description |
|---|---|---|
| `output_path` | yes | Path to the agent's output file. |
| `soul_path` | yes | Path to the agent's `SOUL.md`. |

```yaml
- type: agent_identity_consistent
  output_path: memory/drafts/{{today}}-output.md
  soul_path: agents/marketing/brand/SOUL.md
```

---

## Notes

- Most artifact assertions also accept `timeout` (seconds to wait for the file) and `updated_after` (ISO timestamp asserting the file was recently modified).
- `artifact_matches_golden` uses a ROUGE-style similarity threshold via `rouge_threshold` (default: 0.7).
- `state_file` accepts both `expected_status` (checks the `status` key) and `expected_fields` (checks arbitrary key-value pairs).
- Trace assertions return `skip` (not `fail`) when the observability backend is unavailable or no trace is found. This prevents CI failures caused by observability outages.
- `delegation_path` returns `warn` when no sub-agent spans are found and no fallback routing data is configured.
- `trace_cost` returns `warn` when no cost data is available. Configure `model_pricing` in `clawspec.yaml` for estimation.
