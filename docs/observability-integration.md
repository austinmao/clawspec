# Observability Integration

ClawSpec's observability integration connects scenario runs to live trace data from your AI observability platform. When a scenario run completes, ClawSpec correlates it to the corresponding gateway trace, pulls span-level data, runs trace assertions against it, and embeds a direct dashboard URL in the report. The net result is one-click debugging: a failing assertion links you to the exact trace that failed.

## What Observability Integration Does

Without observability, ClawSpec assertions can only inspect file artifacts, gateway logs, and HTTP responses. Trace assertions extend this to the actual LLM execution:

- **LLM call counts** — detect unexpectedly chatty agents
- **Tool sequences** — verify tools were called in the right order
- **Model enforcement** — assert a specific model was (or was not) used
- **Per-span token budgets** — catch expensive individual calls
- **Trace-level cost and duration** — enforce performance SLAs
- **Error detection** — surface hidden span errors not visible in artifacts
- **Delegation paths** — verify multi-agent routing matches expectations

Every report block that uses trace assertions also includes a `trace_url` field pointing to the exact run in your observability dashboard.

## Prerequisites

Before enabling observability:

1. An **Opik Cloud account** at [comet.com/opik](https://www.comet.com/opik) — the free tier is sufficient for development use.
2. The **opik-openclaw gateway plugin** installed on your OpenClaw gateway. This plugin injects the ClawSpec `run_id` into trace metadata and is required for trace correlation. See the plugin README at `comet-ml/opik-openclaw` for installation instructions.
3. The `OPIK_API_KEY` environment variable set to your Opik API key.

## Installation

The Opik adapter is an optional extra. Install it with:

```bash
pip install clawspec[opik]
# or with uv
uv pip install -e ".[opik]"
```

This installs the `opik` SDK as a dependency. The base `clawspec` package has no observability dependency and works without it.

## Configuration

Add an `observability:` block to your `clawspec.yaml`:

```yaml
observability:
  backend: opik                   # Required. "opik" or "none" (default: "none")
  trace_poll_delay_ms: 3000       # Milliseconds to wait after run before polling (default: 3000)
  time_window_padding_ms: 10000   # Extra time window on each side when searching (default: 10000)

  opik:
    project_name: my-project      # Opik project name to search within (default: "")
    workspace: my-workspace       # Opik workspace name (default: "")
    # api_key is NEVER read from this file — load from OPIK_API_KEY env var

  model_pricing:
    claude-sonnet-4-6:
      input_per_1k: 0.003
      output_per_1k: 0.015
    claude-haiku-4-5:
      input_per_1k: 0.00025
      output_per_1k: 0.00125
```

### Field Reference

| Field | Type | Default | Description |
|---|---|---|---|
| `backend` | string | `"none"` | Observability adapter. Use `"opik"` to enable. |
| `trace_poll_delay_ms` | int | `3000` | Delay after scenario completion before polling for the trace. Increase if traces arrive late. |
| `time_window_padding_ms` | int | `10000` | Extra window (ms) added to both sides of the scenario time window during trace search. |
| `opik.project_name` | string | `""` | Opik project to scope the trace search. Omit to search all projects. |
| `opik.workspace` | string | `""` | Opik workspace. Required if your account has multiple workspaces. |
| `model_pricing` | dict | `{}` | Per-model pricing table used for cost estimation when Opik does not report native cost data. Keys are model name substrings; matching is by suffix. |

### Environment Variable Override

The `observability_backend` field can also be set without touching the config file:

```bash
CLAWSPEC_OBSERVABILITY_BACKEND=opik clawspec run skills/my-skill
```

The `OPIK_API_KEY` must always come from the environment. Never put it in `clawspec.yaml`.

## How Trace Correlation Works

ClawSpec uses a three-tier matching strategy to find the trace for a scenario run:

**Tier 1: Run ID injection (preferred)**

When the `opik-openclaw` gateway plugin is active, it injects the ClawSpec run ID (format: `clawspec-YYYYMMDD-HHMMSS-random6`) into trace metadata before the trace is created. ClawSpec then queries Opik for traces matching that exact run ID. This is exact and unambiguous.

**Tier 2: Time-window + agent ID**

If no run ID match is found, ClawSpec searches for traces from the correct agent within the scenario's time window (start time minus `time_window_padding_ms`, end time plus `time_window_padding_ms`). When a single trace matches, it is used. When multiple traces match, the closest one by start time is selected.

**Tier 3: Skip**

If no trace is found after polling (one attempt, after `trace_poll_delay_ms`), all trace assertions in the scenario are marked `skip` rather than `fail`. This preserves CI green status when observability is temporarily unavailable.

## Trace Enrichment

After correlation, ClawSpec writes back to the trace:

- **Metadata** — scenario name, run ID, assertion counts, pass/fail status
- **Feedback scores** — numeric scores for key metrics (assertion pass rate, cost, duration)

Enrichment is non-atomic: metadata and scores are applied in separate API calls. A partial enrichment failure does not block report generation.

The `EnrichResult` returned by the backend reports which operations succeeded:

```python
@dataclass
class EnrichResult:
    metadata_applied: bool
    scores_applied: bool
    errors: list[str]
```

## Report Output

When observability is active and a trace is found, the JSON report for each scenario includes a `trace` block:

```json
{
  "name": "my-scenario",
  "status": "pass",
  "trace": {
    "id": "trace-abc123",
    "url": "https://app.comet.com/opik/my-workspace/my-project/traces/trace-abc123",
    "spans_summary": {
      "total": 8,
      "llm": 3,
      "tool": 4,
      "subagent": 1
    },
    "cost": {
      "total_tokens": 4821,
      "total_cost_usd": 0.0423,
      "cost_is_estimated": false
    }
  }
}
```

The `cost_is_estimated` flag is `true` when Opik did not report native cost data and ClawSpec computed the estimate from `model_pricing` config.

## Writing a Custom Backend

The `ObservabilityBackend` protocol in `clawspec/observability/__init__.py` defines the interface. All methods must be implemented:

```python
from clawspec.observability import (
    CostData,
    EnrichResult,
    ObservabilityConfig,
    ObservabilityBackend,
    SpanData,
    TraceHandle,
)

class MyBackend:
    def __init__(self, config: ObservabilityConfig) -> None:
        self._config = config

    def is_available(self) -> bool:
        """Lightweight connectivity check. Called once per session and cached."""
        ...

    def find_trace(
        self,
        agent_id: str,
        start_time: str,
        end_time: str,
        run_id: str,
        time_window_padding_ms: int = 10000,
    ) -> TraceHandle | None:
        """Find the gateway trace for a scenario run. Return None if not found."""
        ...

    def get_spans(
        self,
        trace: TraceHandle,
        span_type: str | None = None,
    ) -> list[SpanData] | None:
        """Return spans for a trace. Return None on query failure."""
        ...

    def enrich_trace(
        self,
        trace: TraceHandle,
        metadata: dict,
        scores: dict[str, float],
    ) -> EnrichResult:
        """Write metadata and scores back to the trace."""
        ...

    def get_trace_url(self, trace: TraceHandle) -> str | None:
        """Return a browser-accessible URL for this trace."""
        ...

    def get_cost(self, trace: TraceHandle) -> CostData | None:
        """Return aggregate token usage and cost for the trace."""
        ...
```

The protocol is `@runtime_checkable`, so you can verify your implementation with `isinstance(my_backend, ObservabilityBackend)`.

**Data class reference:**

| Class | Purpose | Key fields |
|---|---|---|
| `TraceHandle` | Lightweight reference to a discovered trace | `id`, `name`, `start_time`, `end_time`, `backend_ref` |
| `SpanData` | One execution step within a trace | `id`, `type` (llm/tool/subagent), `name`, `duration_ms`, `tokens`, `error` |
| `TokenUsage` | Token consumption for a span | `input_tokens`, `output_tokens`, `total_tokens`, `cost_usd` |
| `CostData` | Aggregate cost for an entire trace | `total_tokens`, `total_cost_usd`, `cost_is_estimated`, `per_span` |
| `EnrichResult` | Outcome of enrichment | `metadata_applied`, `scores_applied`, `errors` |

To activate your backend, register it in the ClawSpec session initialization and pass an instance where `ObservabilityBackend` is expected. Custom backend registration via config string is not yet supported; you must use the Python API directly.

## Troubleshooting

**Trace not found — all trace assertions skipped**

The most common cause is the `opik-openclaw` gateway plugin not being installed or active. Without it, trace correlation falls back to time-window matching, which requires the run time window to be narrow enough to uniquely identify the trace. Verify the plugin is running:

```bash
openclaw gateway status
```

Also check that `opik.project_name` and `opik.workspace` match the project the gateway plugin is reporting to.

If the gateway takes more than 3 seconds to flush traces to Opik, increase `trace_poll_delay_ms`:

```yaml
observability:
  trace_poll_delay_ms: 8000
```

**Opik unavailable — all trace assertions skipped**

`is_available()` returns `False` when the Opik SDK cannot reach the API. Check that `OPIK_API_KEY` is set and valid:

```bash
echo $OPIK_API_KEY
python -c "import opik; c = opik.Opik(); print('ok')"
```

Non-trace assertions are unaffected when observability is unavailable.

**Cost shows `warn` status — no cost data available**

Opik may not report cost data for all model providers. Add a `model_pricing` block to `clawspec.yaml` to enable client-side cost estimation. The `cost_is_estimated: true` flag will appear in the report and assertion detail.

**`ImportError: No module named 'opik'`**

Install the optional extra: `pip install clawspec[opik]`. The base package does not include the Opik SDK.
