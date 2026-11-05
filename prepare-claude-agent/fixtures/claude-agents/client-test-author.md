---
name: client-test-author
description: Sanitized original-shaped author; hook and other semantics must be rejected.
model: claude-sonnet-5-5
effort: high
maxTurns: 450
skills:
  - synthetic-author
tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
hooks:
  PostToolUse:
    - matcher: Write
      hooks:
        - type: command
          command: SANITIZED_HOOK_DO_NOT_EXECUTE
          timeout: 30
---
# Sanitized author shape

Synthetic content only. The hook marker is inert data, not a real script.
Do not execute. This fixture must fail preparation rather than lose semantics.
