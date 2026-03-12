# Building New Pipelines

Use this flow when you are creating a new orchestrated OpenClaw workflow.

## 1. Start with the scenario contract

```yaml
version: "1.0"
target:
  type: skill
  path: skills/my-orchestrator
  trigger: /run-my-pipeline
scenarios:
  - name: happy-path
    tags: [smoke]
    when:
      invoke: /run-my-pipeline launch
      params:
        test_mode: true
    then:
      - type: artifact_exists
        path: memory/drafts/{{today}}-output.md
        timeout: 60
  - name: happy-path-negative
    tags: [negative]
    when:
      invoke: /run-my-pipeline forbidden
      params:
        test_mode: true
    then:
      - type: tool_not_called
        tool: send_message
```

## 2. Add handoff contracts

```yaml
version: "1.0"
handoff:
  from: my-orchestrator
  to: my-executor
  mechanism: sessions_spawn
caller_provides:
  required_context:
    - name: task
      description: "Work request"
callee_produces:
  required_artifacts:
    - path_pattern: memory/drafts/{{today}}-output.md
      description: "Final artifact"
  prohibited_actions:
    - tool: send_message
      reason: "Execution must remain local"
```

## 3. Add the pipeline contract

```yaml
version: "1.0"
pipeline:
  orchestrator: my-orchestrator
  skill_path: skills/my-orchestrator
  trigger: /run-my-pipeline
stages:
  - name: plan
    agent: my-planner
    produces: memory/drafts/{{today}}-plan.md
  - name: execute
    agent: my-executor
    produces: memory/drafts/{{today}}-output.md
    handoff_contract: tests/handoffs/planner-to-executor.yaml
pipeline_health:
  - description: every stage produced its artifact
    check: count(produced_artifacts) == count(stages_with_produces)
  - description: every handoff passed
    check: all handoff contracts passed
```

## 4. Run the loop

```bash
clawspec validate skills/my-orchestrator
clawspec run skills/my-orchestrator --scenario happy-path --dry-run
python -m clawspec.runner.run --target skills/my-orchestrator --pipeline --dry-run
```

Build the runtime only after the contracts describe the behavior you want.

