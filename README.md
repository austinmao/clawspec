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
- 19 shipped assertion types
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
- [docs/compiler-integration.md](docs/compiler-integration.md)
- [docs/contract-first-methodology.md](docs/contract-first-methodology.md)
- [docs/building-new-pipelines.md](docs/building-new-pipelines.md)
- [docs/migrating-existing-agents.md](docs/migrating-existing-agents.md)
- [docs/assertion-reference.md](docs/assertion-reference.md)
- [docs/launch-posts.md](docs/launch-posts.md)

## License

MIT
