# Migrating Existing Agents

Use this guide when you already have agents or skills and want to retrofit ClawSpec.

## 1. Run structural validation first

```bash
clawspec validate path/to/SKILL.md
clawspec validate path/to/SOUL.md
```

Fix structural failures before writing scenario contracts.

## 2. Start from known failures

Your first contracts should come from real regressions:

- an agent called a forbidden tool
- an artifact was missing a required section
- a route or delegation decision was wrong
- a pipeline skipped a stage or failed to emit an artifact

Encode those as `negative` or `regression` scenarios first.

## 3. Add one smoke and one negative scenario per target

Minimum migration bar:

- one `smoke` scenario for the normal path
- one `negative` scenario for the refusal or boundary case

## 4. Add handoffs only where orchestration exists

Do not over-model simple agents. Add handoff and pipeline contracts only for real delegation or multi-stage workflows.

## 5. Freeze a baseline before cutover

When replacing an older QA system:

1. run the current commands
2. save exit codes and output shapes
3. swap entrypoints to ClawSpec-backed wrappers
4. compare the new outputs against the frozen baseline

## 6. Expand coverage over time

Retrofitting should be incremental:

- highest-blast-radius workflows first
- irreversible actions next
- everything else after the rails are in place

