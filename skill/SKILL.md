---
name: clawspec
description: "Use when validating, running, scaffolding, or measuring QA contracts for OpenClaw skills and agents."
version: "0.1.0"
permissions:
  filesystem: write
  network: true
triggers:
  - command: /clawspec validate
  - command: /clawspec run
  - command: /clawspec init
  - command: /clawspec coverage
metadata:
  openclaw:
    requires:
      bins:
        - python3
      env: []
---

# ClawSpec Skill

## Overview

Routes `/clawspec ...` commands to the local ClawSpec package and returns structured JSON.

## Commands

- `/clawspec validate <target>`
- `/clawspec run <target> [--scenario <name>] [--dry-run]`
- `/clawspec init <target> [--force]`
- `/clawspec coverage [--ledger <path>]`

## Notes

- `run` uses the local OpenClaw runtime for agent or skill invocation.
- `init` and `run` may write files under the workspace.
- Prefer `test_mode` scenarios when using this skill inside CI or a QA workspace.

