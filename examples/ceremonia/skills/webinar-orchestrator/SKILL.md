---
name: webinar-orchestrator
description: "Use when coordinating a multi-stage webinar production workflow."
version: "1.0.0"
permissions:
  filesystem: write
  network: true
triggers:
  - command: /run-webinar
metadata:
  openclaw:
    requires:
      bins:
        - bash
        - python3
      env: []
---

# Webinar Orchestrator

## Overview

Coordinates outlining, copy, review, and artifact production across multiple stages.

