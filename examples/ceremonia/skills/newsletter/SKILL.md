---
name: newsletter
description: "Use when drafting an approval-gated newsletter artifact from approved inputs."
version: "1.0.0"
permissions:
  filesystem: write
  network: true
triggers:
  - command: /send-newsletter
metadata:
  openclaw:
    requires:
      bins:
        - bash
        - python3
      env:
        - RESEND_API_KEY
---

# Newsletter Skill

## Overview

Drafts newsletter content in `test_mode` and routes all delivery steps through approval gates.

## Guardrails

- Never send without explicit approval.
- In `test_mode`, route all outputs to QA artifacts only.

