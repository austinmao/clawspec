---
name: orchestrator
description: "Use when coordinating a planner and executor workflow to produce a local draft artifact."
version: "1.0.0"
permissions:
  filesystem: write
  network: false
triggers:
  - command: /orchestrate
metadata:
  openclaw:
    requires:
      bins:
        - python3
      env: []
---

# Orchestrator Skill

## Overview

Coordinates a planner step, an executor step, and a final local artifact write.

## Guardrails

- Never send outbound messages.
- Always keep execution in `test_mode` for QA runs.

