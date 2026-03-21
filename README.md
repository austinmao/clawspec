# ClawSpec

Contract-first QA for OpenClaw skills and agents.

ClawSpec gives you one testing surface for four things:

| Contract | File | Purpose |
|---|---|---|
| Structural validation | `SKILL.md` / `SOUL.md` | Enforce required sections, permissions, gates, and safety rules |
| Scenario contract | `tests/scenarios.yaml` | Test a single skill or agent outcome |
| Handoff contract | `tests/handoffs/*.yaml` | Test what one stage passes to another |
| Pipeline contract | `tests/pipeline.yaml` | Test multi-stage orchestration health |

ClawSpec ships:

- `clawspec validate`
- `clawspec run`
- `clawspec init`
- `clawspec coverage`
- `clawspec baseline` — performance baseline capture and regression detection
- 29 shipped assertion types (19 standard + 10 trace-aware)
- Observability integration via Opik — one-click trace debugging from any failing assertion
- a Python API and an OpenClaw skill wrapper

## Install

```bash
uv tool install .
# or
uv pip install -e .
```

## Quick start

```bash
clawspec validate examples/basic/skills/hello
clawspec init examples/basic/skills/hello --force
clawspec run examples/basic/skills/hello --scenario hello-smoke --dry-run
clawspec coverage --ledger examples/ceremonia/coverage-ledger.yaml --json
```

## Opik observability integration

Connect ClawSpec to [Opik](https://www.comet.com/opik) to get trace URLs in every report and unlock 10 trace-aware assertion types.

```bash
pip install clawspec[opik]
export OPIK_API_KEY=your-key
```

Add to `clawspec.yaml`:

```yaml
observability:
  backend: opik
  opik:
    project_name: my-project
    workspace: my-workspace
```

When observability is active, each report includes a `trace_url` pointing directly to the run in the Opik dashboard. See [docs/observability-integration.md](docs/observability-integration.md) for full setup instructions.

## Baselines and regression detection

Capture performance baselines to detect regressions in cost, latency, and token usage:

```bash
clawspec baseline capture skills/my-skill --runs 20
clawspec baseline show skills/my-skill
```

Add a `regression:` block to any scenario contract to enforce drift thresholds in CI. See [docs/baselines-and-regression-detection.md](docs/baselines-and-regression-detection.md).

## Using with ClawScaffold

[ClawScaffold](https://github.com/austinmao/clawscaffold) is the spec-first target lifecycle manager for OpenClaw. When used together, ClawScaffold auto-generates ClawSpec test scenarios during agent/skill adoption and creation.

```bash
pip install clawscaffold[spec]   # installs both packages
```

When both are installed:
- `clawscaffold adopt` auto-generates `tests/scenarios.yaml` with ClawSpec assertions
- `clawscaffold audit` uses ClawSpec validation for structural checks
- `clawscaffold create` scaffolds test contracts alongside the target spec

ClawSpec works independently — you don't need ClawScaffold to write and run test contracts.

## Related Projects

- **[ClawScaffold](https://github.com/austinmao/clawscaffold)** — Spec-first target lifecycle manager (interactive interviews, adoption, auditing)
- **[OpenClaw](https://github.com/austinmao/openclaw)** — Local-first AI agent framework (LLM + chat channels + Markdown skills)

## Config

ClawSpec looks for `clawspec.yaml` from the target directory upward.

```yaml
gateway_base_url: "http://127.0.0.1:18789"
gateway_webhook_endpoint: "/webhook/mcp-skill-invoke"
report_dir: "reports"
gateway_log_pattern: "/tmp/openclaw/openclaw-{date}.log"
scenario_patterns:
  - "skills/**/tests/scenarios.yaml"
  - "agents/**/tests/scenarios.yaml"
ledger_path: "coverage-ledger.yaml"
```

Compiler-managed repos can point ClawSpec at generated QA artifacts by overriding
`scenario_patterns` and `ledger_path`. For example:

```yaml
scenario_patterns:
  - "compiler/generated/qa/**/scenarios.yaml"
ledger_path: "docs/testing/coverage-ledger.yaml"
```

## Python API

```python
from clawspec import coverage, init, run, validate

validate("examples/basic/skills/hello")
init("examples/basic/skills/hello", force=True)
run("examples/basic/skills/hello", scenario="hello-smoke", dry_run=True)
coverage("examples/ceremonia/coverage-ledger.yaml")
```

## Examples

- [examples/basic/skills/hello/SKILL.md](examples/basic/skills/hello/SKILL.md)
- [examples/multi-agent/skills/orchestrator/tests/pipeline.yaml](examples/multi-agent/skills/orchestrator/tests/pipeline.yaml)
- [examples/ceremonia/README.md](examples/ceremonia/README.md)

## Docs

- [docs/quick-start.md](docs/quick-start.md)
- [docs/configuration-reference.md](docs/configuration-reference.md)
- [docs/assertion-reference.md](docs/assertion-reference.md)
- [docs/observability-integration.md](docs/observability-integration.md)
- [docs/baselines-and-regression-detection.md](docs/baselines-and-regression-detection.md)
- [docs/compiler-integration.md](docs/compiler-integration.md)
- [docs/contract-first-methodology.md](docs/contract-first-methodology.md)
- [docs/building-new-pipelines.md](docs/building-new-pipelines.md)
- [docs/migrating-existing-agents.md](docs/migrating-existing-agents.md)
- [docs/launch-posts.md](docs/launch-posts.md)

## License

MIT
