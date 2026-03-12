# Launch Posts

## OpenClaw Community Post

ClawSpec is now public.

It extracts the contract-first QA stack from `openclaw-ceremonia` into a standalone package for OpenClaw skills and agents:

- `clawspec validate` for `SKILL.md` and `SOUL.md`
- `clawspec run` for live scenario contracts
- `clawspec init` for scenario scaffolding
- `clawspec coverage` for project-wide QA gaps

It ships with 19 assertion types, a Python API, an OpenClaw skill wrapper, and redacted real-world examples.

Repo: https://github.com/austinmao/clawspec

## Twitter Thread

1. Open-sourced `clawspec`: contract-first QA for OpenClaw skills and agents. https://github.com/austinmao/clawspec
2. It gives one testing surface for structure (`SKILL.md` / `SOUL.md`), scenarios, handoffs, and full pipelines.
3. Commands in v0.1: `validate`, `run`, `init`, `coverage`.
4. It includes 19 assertion types, a Python API, and an OpenClaw skill wrapper.
5. The repo also includes a redacted Ceremonia example set so the framework is grounded in real production contracts.
6. If you are building multi-agent systems, the goal is simple: move QA from ad hoc smoke tests to explicit contracts.

## Reddit Post

Title: Open-sourced ClawSpec, a contract-first QA framework for OpenClaw agents and skills

Body:

I just published ClawSpec, a standalone QA framework extracted from production OpenClaw testing workflows.

The idea is to treat agent/skill testing as explicit contracts instead of scattered ad hoc scripts:

- structural validation for `SKILL.md` and `SOUL.md`
- scenario contracts for single-target runs
- handoff contracts between stages
- pipeline contracts for orchestrators
- coverage reporting across a project

The initial release includes:

- `clawspec validate`
- `clawspec run`
- `clawspec init`
- `clawspec coverage`
- 19 shipped assertion types
- Python API
- OpenClaw skill wrapper
- example projects, including a redacted production-style showcase

Repo: https://github.com/austinmao/clawspec
