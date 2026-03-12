---
name: hello
description: "Use when validating a minimal ClawSpec skill fixture."
version: "1.0.0"
permissions:
  filesystem: read
  network: false
triggers:
  - command: /hello
metadata:
  openclaw:
    requires:
      bins:
        - python3
---

# Hello Skill

## Overview

Bin gate: `python3`
