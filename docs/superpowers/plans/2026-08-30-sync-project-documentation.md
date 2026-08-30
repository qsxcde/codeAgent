# Synchronize Project Documentation Implementation Plan

> **For agentic workers:** Keep the current code tree and test output as the source of truth while executing this plan.

**Goal:** Synchronize current-facing project documentation with the code, tests, CI, OpenSpec, and release-check state as of 2026-08-30, without changing runtime behavior or package version metadata.

**Architecture:** Treat `docs/iteration/v0.4.md` as the current implementation-status source. Mirror its verified facts into `README.md`, `CHANGELOG.md`, the testing guides, and current sections of the design documents. Preserve explicitly historical v0.1–v0.3 snapshots and the committed TUI schema-v1 benchmark; describe the schema-v2 Linux baseline as a CI-generated candidate until a reviewed baseline is committed.

**Tech Stack:** Markdown documentation, OpenSpec artifacts, pytest/Ruff/uv verification, and existing JSON benchmark metadata.

**Spec:** `AGENTS.md`, `docs/iteration/v0.4.md`, `docs/testing.md`, `docs/design/architecture.md`, and the archived OpenSpec change set. This is a documentation-only synchronization; no behavioral spec delta is required.

## Global Constraints

- Do not change Python source, tests, package version metadata, lock files, or benchmark data as part of this documentation sync.
- The package version remains `0.3.0`; describe v0.4 as the completed implementation scope pending release metadata/tagging.
- Use the verified local baseline: `1532 passed`; fast quality gate: `1391 passed, 141 deselected`, coverage `83.61%`.
- State that `openspec validate --specs` is `20/20` and the latest pre-documentation main CI run was successful, without implying that uncommitted documentation changes have already run in CI.
- Keep historical iteration records and historical benchmark reports intact unless a current-status sentence is demonstrably misleading.

## Tasks

### 1. Establish the authoritative current status

- Update `docs/iteration/v0.4.md` to distinguish completed v0.4 functionality from the still-unreleased `0.3.0` package metadata.
- Correct the TUI performance wording so schema-v1 remains the committed historical baseline and schema-v2 is generated/reviewed through CI.
- Replace the stale “next stage enters stage 6” wording with the current post-v0.4 maintenance/release-readiness state.

### 2. Synchronize user-facing documentation

- Update `README.md` with the v0.4 implementation scope, current validation counts, session/runtime/tooling capabilities, and the unreleased package-version caveat.
- Replace the stale `CHANGELOG.md` Unreleased planning note with a concise v0.4 implementation summary, engineering updates, and current verification facts; preserve the historical v0.3.0 entry.

### 3. Synchronize engineering and design documentation

- Update `docs/testing.md` and `docs/test-structure.md` to use the current test and coverage facts.
- Update current sections of `docs/design/architecture.md` and `docs/design/self-built-orchestration-blueprint.md` to reference v0.4 and current runtime/test state.
- Add a superseding current-status section to `docs/design/requirements-analysis.md` and correct current-facing stale metrics while retaining dated historical appendices.

### 4. Verify consistency and scope

- Search current-facing docs for stale claims such as `1466 passed`, `1000 passed`, `v0.3.0 已完成验收`, old coverage values, and “stage 6 not yet started”.
- Run `git diff --check`, `openspec validate --specs`, Ruff, and the full offline test suite; inspect the final diff and working-tree status.
- Confirm no source, test, lock, version, or benchmark JSON files were modified.
