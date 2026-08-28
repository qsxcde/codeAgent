# Organize App Package Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `src/codeagent/app/` 的实现按职责归并为规范子包，删除迁移期兼容入口，让规范路径成为唯一真实入口并保持运行时行为不变。

**Architecture:** 根层只保留 CLI 入口、组合根和全局配置。技能/任务/错误处理各自形成应用子包；`composition/` 按装配对象分包；`tui/` 按端口、适配器、状态、展示和工作流分包。新包承载真实实现，旧迁移入口最终删除。

**Tech Stack:** Python 3.12、pytest、Ruff、uv、OpenSpec、AST 架构检查。

**Spec:** `openspec/changes/organize-app-package-layout/design.md`

## Global Constraints

- 不改变 CLI/TUI 行为、命令集合、会话 JSONL 格式、运行时事件语义和公共符号签名。
- `app/main.py`、`app/container.py`、`app/config.py` 保留为稳定根入口。
- 具体 Textual 类型只能出现在 `app/tui/adapters/textual/`。
- 已迁移旧路径全部删除；`__init__.py` 不做全量 eager import。
- 生产文件不超过 300 行，函数不超过 80 行；不增加第三方依赖。

## File Map

- Create: `src/codeagent/app/context/`, `errors/`, `skills/`, `tasks/`, `composition/{model,runtime,session,tools,tui}/`, `tui/{ports,adapters,textual,state,presentation,commands,session,rendering,benchmark}/`
- Modify: delete old flat compatibility modules; update `container.py`, `main.py`, TUI imports, architecture tests, scale scanner, docs.
- Test: add package-layout import contract; update `tests/contracts/test_app_architecture.py`, TUI and app tests as needed.

## Task 1: Add package skeleton and failing import contract

**Files:**
- Create: target package directories and minimal `__init__.py` files
- Create: `tests/contracts/test_app_package_layout.py`
- Modify: `tests/contracts/test_app_architecture.py`, `scripts/scale_scan.py`

**Interfaces:**
- The contract imports canonical paths such as `codeagent.app.skills.discovery`, `codeagent.app.tasks.verification.runner`, `codeagent.app.composition.model.factory`, and `codeagent.app.tui.ports.backend`.
- The contract rejects `textual` imports outside `app/tui/adapters/textual/`.

- [x] Write the import and boundary assertions first.
- [x] Run `uv run pytest tests/contracts/test_app_package_layout.py -q`; expected failure is missing canonical modules before migration.
- [x] Add only package skeletons and explicit architecture rules needed for the test.
- [x] Re-run the contract and retain any expected failure until the first migration batch supplies the implementation.

## Task 2: Migrate context, errors, skills, and tasks

**Files:**
- Create: `app/context/agents.py`, `app/errors/reporting.py`, `app/skills/*`, `app/tasks/*`
- Modify: old root modules as thin re-exports; internal imports and related tests

**Interfaces:**
- Preserve all current public names from `agents`, `skills`, `skill_packages`, `task_supervisor`, and verification modules.
- Canonical modules must not import concrete AI, tools, session, or Textual implementations.

- [x] Move the implementation and add compatibility re-exports.
- [x] Run focused app/skills/tasks tests and the package-layout contract.
- [x] Fix only import/path regressions; do not change behavior.

## Task 3: Migrate composition factories

**Files:**
- Create: `app/composition/model/*`, `runtime/factory.py`, `session/factory.py`, `tools/*`, `tui/*`
- Modify: `app/container.py`, old composition modules, composition tests

**Interfaces:**
- Preserve `create_agent_config`, `create_agent_runtime`, `create_agent_session`, `create_session_manager`, `create_tools`, `create_tui_app`, and runtime close helpers.
- `container.py` remains the only public cross-layer composition facade.

- [x] Add/import canonical factory paths before changing callers.
- [x] Migrate implementation and keep old composition modules as re-exports.
- [x] Run composition and lifecycle tests plus AST boundary checks.

## Task 4: Migrate TUI ports, state, presentation, and workflows

**Files:**
- Create: `app/tui/ports/backend.py`, `adapters/textual/*`, `state/*`, `presentation/*`, `commands/*`, `session/*`, `rendering/*`, `benchmark/*`
- Modify: old TUI modules as shims; `tui/main.py`, TUI tests and architecture rules

**Interfaces:**
- Preserve `TuiBackend`, `TuiModel`, `RuntimeReducer`, `Transcript`, command coordinators, session coordinators, and `TuiApp` public behavior.
- Concrete Textual classes remain behind the backend port.

- [x] Move port and adapter modules, then run backend and Textual tests.
- [x] Move state and presentation modules, then run model/transcript/render tests.
- [x] Move commands/session/rendering/benchmark modules, then run all TUI tests.
- [x] Verify compatibility imports and no non-adapter Textual import.

## Task 5: Documentation and final verification

**Files:**
- Modify: `docs/design/architecture.md`, `docs/testing.md`, OpenSpec task checkboxes, architecture/scale tests

- [x] Update canonical package tree and compatibility policy.
- [x] Search production imports for old paths and remove accidental internal use.
- [x] Run `uv run pytest tests/contracts/test_app_package_layout.py tests/contracts/test_app_architecture.py -q`.
- [x] Run `uv run pytest -m "unit or contract" -q --strict-markers`.
- [x] Run `uv run pytest -q`, `uv run ruff check src tests scripts`, `uv run python scripts/scale_scan.py`, `git diff --check`, `openspec validate --specs`, and `uv build`.

## Task 6: Delete migration compatibility entrances

**Files:**
- Delete: migrated flat modules under `app/`, `app/composition/`, and `app/tui/`
- Modify: package `__init__.py` files, production/tests/docs imports, layout and architecture contracts

**Interfaces:**
- Canonical package paths are the only supported repository imports.
- `main.py`, `container.py`, `config.py`, `tui/main.py`, and real package initializers remain as entry points.

- [x] Delete compatibility re-exports and legacy flat modules.
- [x] Migrate every in-repository import and remove legacy exports from package initializers.
- [x] Assert legacy modules are absent and canonical paths are importable.
- [x] Run the full verification set and update the final documentation.
