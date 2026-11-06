# Live model resolution implementation plan

**Goal:** Resolve aliases and versions against a fresh Copilot catalog on each invocation.
**Architecture:** One SDK discovery helper and a deterministic resolver in the existing converter.
**Tech stack:** Python 3.12, PyYAML, official GitHub Copilot Python SDK, unittest.
**Spec:** ../specs/2026-11-06-live-model-resolution.md

## Constraints and review focus

Preserve input/body guards and native VS Code behavior. No inference or active agent
files. No CI. Fail closed on auth/timeouts, unknown policy, empty/malformed catalogs,
ambiguous versions, unavailable variants and absent families. Numeric ordering must
handle 5.10 versus 5.9. Every substitution is visible. Tests never contact services.

## Tasks

- [x] Catalog helper: test lifecycle, filtering, freshness, timeout, malformed data,
  missing dependency and cleanup failures before implementing discover_models(path).
  Own scripts/copilot_catalog.py and tests/test_copilot_catalog.py.
- [x] Converter: test alias/latest, exact spelling equivalence, closest version and
  newer ties, missing families/variants, changing catalogs and stderr notices. Remove
  CLI_MODELS; integrate lazy discovery and --copilot-path. Adapt existing subprocess
  harness at the discovery boundary; retain source/guard coverage and original fixtures.
- [x] Document provisioned runtime/SDK, metadata network access, exact/nearest policy,
  failure behavior and commands in both READMEs and SKILL. Make inventory synthetic
  test data rather than production policy. Add new files to builder/test allowlists.
- [x] Verify both suites, secret scan, ZIP/manifest/source equality, no fixture changes;
  obtain independent review, fix findings, commit/push one PR. Do not merge.

Execution: user authorized implementation with 'Do it'; execute without another
planning approval round. Work in feat/live-model-resolution, isolated sibling worktree.

## Verification record

- Python 3.12.16 / PyYAML 6.0.1 / github-copilot-sdk 1.0.28: 6 builder
  and 59 skill tests passed, no skips. Discovery boundary is synthetic in tests.
- Live metadata-only preview via installed Copilot CLI 1.0.71-0 succeeded:
  sonnet selected claude-sonnet-5.5. No agent session or inference prompt sent.
- Independent review found a reserved-selector/catalog-family collision; added
  an explicit guard and regression test (observed failing before fix, then passing).
- Gitleaks: zero findings. ZIP and all 19 payload files match their manifests;
  original eight fixtures unchanged. Native Windows and live inference untested.

- Copilot PR review found explicit numeric IDs bypassing ambiguity checks and raw
  SDK startup logging. Both reproduced with failing tests and fixed. Scoped SDK
  logging suppression restores caller logging configuration. A real SDK startup
  failure against a synthetic executable emitted only a sanitized rejection.
