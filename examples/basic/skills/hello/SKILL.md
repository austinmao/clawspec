---
name: hello
description: "Use when drafting a simple hello-world artifact without external side effects."
version: "1.0.0"
permissions:
  filesystem: write
  network: false
triggers:
  - command: /hello
metadata:
  openclaw:
    requires:
      bins:
        - python3
      env: []
---

# Hello Skill

## Overview

Creates a local draft artifact for testing and demo purposes.

## Guardrails

- Never send messages or touch remote systems.
- Use `test_mode` inputs when invoked from ClawSpec scenarios.

