# Baselines and Regression Detection

ClawSpec baselines capture the historical performance profile of a scenario — how long it typically runs, how many tokens it uses, what it costs — and compare future runs against that profile to detect regressions before they reach production.

## What Baselines Are

A baseline is a set of percentile statistics computed from multiple runs of a scenario. For each metric, ClawSpec stores p50 (median), p95 (tail), min, max, and standard deviation. When the scenario runs again, the current values are compared against the baseline and any drift beyond configured thresholds is reported as a regression.

Baselines cover eight metrics:

| Metric | What it measures |
|---|---|
| `duration_ms` | Wall-clock execution time |
| `total_tokens` | Sum of input + output tokens across all spans |
| `input_tokens` | Input tokens only |
| `output_tokens` | Output tokens only |
| `cost_usd` | Total cost in USD |
| `llm_call_count` | Number of LLM span invocations |
| `tool_invocation_count` | Number of tool span invocations |
| `subagent_delegation_count` | Number of sub-agent delegations |

Baselines require observability to be enabled — metric values are extracted from trace spans.

## The Lifecycle

Every scenario starts with no baseline. The lifecycle moves through three states:

**NO_BASELINE** — No baseline file exists for this scenario. Regression checks are skipped. The drift config in the scenario contract is present but dormant.

**PROVISIONAL** — A baseline has been captured from fewer than 20 runs. The p95 estimate may be statistically unreliable. ClawSpec emits a warning when capturing with fewer than 10 runs, and a note in reports when comparing against a provisional baseline. Drift thresholds are still enforced.

**STABLE** — A baseline captured from 20 or more runs. Percentile estimates are reliable. This is the recommended state for production CI.

There is no automatic state machine — the lifecycle is a description of data quality rather than a tracked field. Stability is determined by inspecting the `runs` field in the stored baseline.

## Auto-Capture

When a scenario runs for the first time with no existing baseline and the run count exceeds `MIN_RUNS` (5), ClawSpec can automatically capture a provisional baseline from those runs. This is the "first run" behavior:

- Run 1–4: No baseline captured, no regression check.
- Run 5+: If `--runs 5` (or higher) is passed to `baseline capture`, a baseline is computed from all collected run metrics.

Auto-promotion from provisional to stable happens when you explicitly re-capture with `--runs 20` or higher. There is no silent auto-upgrade — you must re-run `clawspec baseline capture` with a larger sample.

## CLI Commands

### Capture a baseline

```bash
clawspec baseline capture skills/my-skill --runs 20
```

This runs the scenario 20 times and computes percentile statistics from all runs. The minimum is 5 runs. Using fewer than 10 runs triggers a warning that p95 estimates may be unreliable. The `--runs 20` default (recommended) produces stable percentiles.

The baseline is stored at `<report_dir>/baselines.yaml` relative to your `clawspec.yaml`.

```bash
# Capture with minimum runs (provisional baseline)
clawspec baseline capture skills/my-skill --runs 5

# Capture stable baseline
clawspec baseline capture skills/my-skill --runs 20

# Output as JSON
clawspec baseline capture skills/my-skill --runs 10 --json
```

### Show current baselines

```bash
clawspec baseline show skills/my-skill
```

Displays the stored baseline for all scenarios under the target, including capture date, run count, and percentile values for all metrics.

```bash
# As JSON for tooling
clawspec baseline show skills/my-skill --json
```

Example output (abbreviated):

```
scenario: my-skill/smoke
  captured_at: 2026-03-20T14:23:00Z
  runs: 20
  metrics:
    duration_ms:   p50=1823.4  p95=3201.7  min=1204.1  max=4102.3
    total_tokens:  p50=4218    p95=6841    min=3102     max=7934
    cost_usd:      p50=0.0312  p95=0.0498  min=0.0221   max=0.0612
```

### Reset baselines

```bash
# Reset all scenarios under the target
clawspec baseline reset skills/my-skill

# Reset one specific scenario
clawspec baseline reset skills/my-skill --scenario my-skill/smoke
```

Reset removes baseline data, returning the scenario to NO_BASELINE state. Subsequent runs will not check regression until a new baseline is captured.

## The `regression:` Block in Scenario Contracts

Add a `regression:` block to any scenario in `tests/scenarios.yaml` to enable drift detection when observability is active and a baseline exists:

```yaml
scenarios:
  - name: my-skill/smoke
    description: Smoke test with regression detection
    steps:
      - skill: my-skill
        input: {message: "hello"}
    assertions:
      - type: artifact_exists
        path: memory/drafts/output.md

    regression:
      compare: p50                   # Compare against p50 or p95 (default: p50)
      max_duration_drift: 2.0        # Fail if duration exceeds 2x baseline p50
      max_cost_drift: 1.5            # Fail if cost exceeds 1.5x baseline p50
      max_token_drift: 1.5           # Fail if total tokens exceed 1.5x baseline p50
      max_step_drift: 2              # Fail if llm_call_count exceeds baseline p50 + 2 (absolute)
```

If no baseline exists for the scenario, the `regression:` block is silently skipped — it does not cause an error or a skip status.

## Drift Detection

Each drift check compares the current run's metric against a baseline statistic and evaluates whether the result exceeds the configured limit.

**Ratio-based metrics** (`max_duration_drift`, `max_cost_drift`, `max_token_drift`):

```
drift = actual / baseline_p50  (or baseline_p95 when compare: p95)
status = FAIL if drift > limit
```

A `max_cost_drift: 1.5` means the run fails if cost is more than 1.5 times the baseline median.

**Absolute difference metric** (`max_step_drift`):

```
drift = actual - baseline_p50
status = FAIL if drift > limit
```

`max_step_drift` uses absolute difference because LLM call counts are integers and ratios are less meaningful at small values. A `max_step_drift: 2` means the run fails if the LLM call count is more than 2 above the baseline median.

The `compare: p95` option compares against the 95th percentile instead of the median. Use this when your baseline has high variance and you want to suppress false positives from naturally slow runs:

```yaml
regression:
  compare: p95
  max_duration_drift: 1.2
```

### Drift check result format

Each drift check appears in the report with full context:

```json
{
  "metric": "duration_ms",
  "baseline_p50": 1823.4,
  "baseline_p95": 3201.7,
  "actual": 4100.0,
  "drift": 2.25,
  "limit": 2.0,
  "status": "fail"
}
```

## Configuration

The baseline file location follows `report_dir`. If `report_dir` is `reports`, baselines are stored at `reports/baselines.yaml`. This file is human-readable YAML and should be committed to version control along with your scenario contracts.

```yaml
# reports/baselines.yaml (auto-generated, commit this file)
version: "1.0"
baselines:
  my-skill/smoke:
    captured_at: "2026-03-20T14:23:00+00:00"
    runs: 20
    metrics:
      duration_ms:
        p50: 1823.4
        p95: 3201.7
        min: 1204.1
        max: 4102.3
        stddev: 512.8
      total_tokens:
        p50: 4218.0
        p95: 6841.0
        min: 3102.0
        max: 7934.0
        stddev: 891.2
```

**`max_history_age_days`** — there is no automatic expiry of baseline data. Baselines remain valid until explicitly reset with `clawspec baseline reset`. If you change the agent's model, system prompt, or workflow significantly, reset and re-capture.

**Ring buffer** — the baseline file stores only the final computed statistics, not raw run data. Individual run metrics are not retained between capture sessions. The `runs` field records how many runs the statistics were computed from, but the raw values are not persisted.

## Example Workflow

**Initial setup:**

```bash
# 1. Run baseline capture with 20 runs
clawspec baseline capture skills/my-skill --runs 20

# 2. Verify the baseline looks reasonable
clawspec baseline show skills/my-skill

# 3. Commit the baseline file
git add reports/baselines.yaml
git commit -m "feat: add performance baseline for my-skill"
```

**Normal CI run:**

```bash
clawspec run skills/my-skill
# If regression: block is in scenarios.yaml and baseline exists,
# drift checks run automatically and appear in the report.
```

**Investigating a regression:**

```bash
# Scenario fails with: cost $0.0821 > max $0.0498 (drift=2.63, limit=1.5)

# 1. Check the trace URL in the report for the expensive run
# 2. Look at which LLM spans consumed the most tokens

# If the regression is expected (intentional model upgrade):
clawspec baseline reset skills/my-skill --scenario my-skill/smoke
clawspec baseline capture skills/my-skill --runs 20

# 3. Update the regression thresholds if the new behavior is correct
# 4. Commit updated baseline and config
```

**Resetting after an intentional change:**

```bash
# After upgrading the agent's model to a more capable (costlier) one:
clawspec baseline reset skills/my-skill
clawspec baseline capture skills/my-skill --runs 20
git add reports/baselines.yaml
git commit -m "chore: recapture baseline after model upgrade"
```
