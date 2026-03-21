# Quick Start

## Install

```bash
uv tool install .
```

For local development:

```bash
uv pip install -e .
```

## 1. Validate an existing skill

```bash
clawspec validate examples/basic/skills/hello
```

Expected result: all structural checks pass.

## 2. Scaffold a contract

```bash
clawspec init examples/basic/skills/hello --force
```

This creates or overwrites `tests/scenarios.yaml` beside the target.

## 3. Run a dry-run scenario

```bash
clawspec run examples/basic/skills/hello --scenario hello-smoke --dry-run
```

Dry-run mode validates structure, expands templates, and evaluates preconditions without triggering the runtime.

## 4. Inspect coverage

```bash
clawspec coverage --ledger examples/ceremonia/coverage-ledger.yaml --json
```

## 5. Enable Opik observability

Install the optional Opik extra and set your API key:

```bash
pip install clawspec[opik]
export OPIK_API_KEY=your-opik-api-key
```

Add an `observability:` block to `clawspec.yaml`:

```yaml
observability:
  backend: opik
  opik:
    project_name: my-project
    workspace: my-workspace
```

Run any scenario. The report now includes a `trace_url` field linking directly to the run in the Opik dashboard. If the trace is not found, all trace assertions are skipped — non-trace assertions are unaffected.

## 6. Run with trace assertions

Add trace assertions to any scenario contract alongside your existing assertions:

```yaml
scenarios:
  - name: my-skill/smoke
    description: Smoke test with trace verification
    steps:
      - skill: my-skill
        input: {message: "hello"}
    assertions:
      - type: artifact_exists
        path: memory/drafts/output.md
      - type: llm_call_count
        min: 1
        max: 3
      - type: no_span_errors
      - type: trace_cost
        max_usd: 0.05
```

Run the scenario normally — ClawSpec automatically correlates the trace and evaluates trace assertions after the step completes:

```bash
clawspec run examples/basic/skills/hello --scenario my-skill/smoke
```

## 7. Capture baselines

After your scenario is stable, capture a performance baseline:

```bash
# Minimum viable baseline (provisional)
clawspec baseline capture examples/basic/skills/hello --runs 5

# Stable baseline (recommended for CI)
clawspec baseline capture examples/basic/skills/hello --runs 20
```

Inspect the captured baseline:

```bash
clawspec baseline show examples/basic/skills/hello
```

Commit the generated `reports/baselines.yaml` file. Future runs with a `regression:` block in the scenario contract will compare against these percentiles and fail if drift exceeds your thresholds.

## Next steps

- Read [contract-first-methodology.md](contract-first-methodology.md)
- Study [assertion-reference.md](assertion-reference.md) — all 29 assertion types
- Read [observability-integration.md](observability-integration.md) — full Opik setup and custom backend guide
- Read [baselines-and-regression-detection.md](baselines-and-regression-detection.md) — drift detection workflow
- Read [configuration-reference.md](configuration-reference.md) — all config fields and environment variables
- Browse [../examples/multi-agent/](../examples/multi-agent/)

