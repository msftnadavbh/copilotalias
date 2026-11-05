---
name: smc-scanner
description: Sanitized original-shaped scanner; unsupported semantics must be rejected.
model: claude-opus-5-5
effort: medium
maxTurns: 150
disallowedTools:
  - Edit
skills:
  - synthetic-rubric
  - synthetic-discovery
tools:
  - Read
  - Write
  - Glob
  - Grep
  - Bash
  - mcp__fixture__catalog
  - mcp__fixture__inspect
---
# Sanitized scanner shape

Synthetic content only: no repository, service, credentials, or real task.
Do not execute. This fixture must fail preparation rather than lose semantics.
