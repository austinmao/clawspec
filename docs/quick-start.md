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

## Next steps

- Read [contract-first-methodology.md](contract-first-methodology.md)
- Study [assertion-reference.md](assertion-reference.md)
- Browse [../examples/multi-agent/](../examples/multi-agent/)

