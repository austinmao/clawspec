---
name: campaign-workflow
description: "Use when coordinating a redacted campaign build workflow across local artifacts."
version: "1.0.0"
permissions:
  filesystem: write
  network: true
triggers:
  - command: /run-campaign
metadata:
  openclaw:
    requires:
      bins:
        - bash
        - python3
      env: []
---

# Campaign Workflow

## Overview

Redacted orchestration example showing how a larger workflow is modeled for contract-first QA.

