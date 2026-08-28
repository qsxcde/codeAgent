# Project Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复当前项目审查中已确认的安全、持久化、运行时和核心职责边界问题，并用离线回归测试固化行为。

**Architecture:** 保持 `core` 只依赖自身协议，`session` 只负责运行态与持久化边界，`app/composition` 负责跨层装配。安全判断、持久化锁和模型传输分别在各自边界内收敛；高职责核心文件按模型请求、工具执行、运行编排和会话收尾拆分。

**Tech Stack:** Python 3.12+, pytest, asyncio, httpx, JSONL persistence, Textual adapters.

**Spec:** `AGENTS.md`, `docs/code-review-2026-08-28.md`, `openspec/specs/core/spec.md`, `openspec/specs/sessions/spec.md`

## Global Constraints

- `core/` 不得导入 `config`、`ai`、`tools` 或 `session`；`session/` 不得导入 `ai`、`tools` 或 `config`。
- 生产代码文件原则上不超过 300 行；拆分按单一职责，不用兼容层掩盖新的职责耦合。
- 测试保持离线、平台无关，使用 `tmp_path`、`monkeypatch` 和 FakeClient。
- 不删除用户已有的未提交变更，不修改真实凭据、用户会话或生成缓存。

---

### Task 1: 安全命令与敏感路径判定

**Files:**
- Modify: `src/codeagent/tools/security/bash_rules.py`
- Modify: `src/codeagent/tools/security/classifier.py`
- Modify: `src/codeagent/tools/security/filesystem.py`
- Test: `tests/tools/security/`

**Interfaces:**
- 保持 `SecurityDecision` 和现有分类入口不变。
- 新增解释器内联执行、编码管道、系统路径写入和凭据路径的结构化判定规则。

- [x] **Step 1: Write the failing tests** for the seven command bypasses and SSH/AWS/Git credential reads.
- [x] **Step 2: Run the focused security tests** and confirm each failure is a missing deny/ask decision.
- [x] **Step 3: Implement conservative rules** with one shared shell tokenization path and resolved filesystem paths.
- [x] **Step 4: Run the focused security suite** and verify normal workspace reads/commands retain their existing decisions.

### Task 2: JSONL durability and concurrency

**Files:**
- Modify: `src/codeagent/session/persistence/locking.py`
- Modify: `src/codeagent/session/persistence/jsonl_store.py`
- Modify: `src/codeagent/session/persistence/index.py`
- Test: `tests/session/persistence/`

**Interfaces:**
- Preserve `SessionStore` and JSONL record formats.
- Add cross-process lock acquisition, append durability, create atomicity, and size-based rollback without rewriting a whole file.

- [x] **Step 1: Write failing tests** for concurrent create, durable append, and commit rollback preserving the original prefix.
- [x] **Step 2: Run focused persistence tests** and confirm the current race/durability behavior.
- [x] **Step 3: Implement the lock/append/rollback fixes** using platform-specific OS locking and bounded timeout behavior.
- [x] **Step 4: Run persistence and session contract tests**.

### Task 3: Compaction and model transport safety

**Files:**
- Modify: `src/codeagent/session/compaction/policy.py`
- Modify: `src/codeagent/session/session.py`
- Modify: `src/codeagent/ai/transport/openai_compat.py`
- Modify: `src/codeagent/ai/catalog/store.py`
- Modify: `src/codeagent/app/config.py`
- Test: `tests/session/behavior/`, `tests/ai/`, `tests/app/`

- [x] **Step 1: Write failing tests** for empty compaction cuts, single oversized turns, finite non-streaming read timeouts, URL/effort/catalog validation, and newline-safe env values.
- [x] **Step 2: Run focused tests** and confirm the failures.
- [x] **Step 3: Implement bounded compaction, separate transport timeouts, and local configuration validation.**
- [x] **Step 4: Run the focused session/AI/config suites.**

### Task 4: TUI and async lifecycle error boundaries

**Files:**
- Modify: `src/codeagent/app/tui/conversation_coordinator.py`
- Modify: `src/codeagent/app/tui/interaction.py`
- Modify: `src/codeagent/app/tui/session_coordinator.py`
- Modify: `src/codeagent/app/tui/render_coordinator.py`
- Modify: `src/codeagent/app/skill_packages.py`
- Modify: `src/codeagent/app/composition/runtime_factory.py`
- Modify: `src/codeagent/core/agent.py`
- Test: `tests/tui/`, `tests/app/`, `tests/core/`

- [x] **Step 1: Write failing tests** for visible conversation errors, async command errors, git clone off the event loop, cancellation propagation, supervisor identity, and listener task cleanup.
- [x] **Step 2: Run focused tests** and confirm the current failures.
- [x] **Step 3: Implement tracked task ownership, error presentation, cancellation re-raise, and bounded async subprocess execution.**
- [x] **Step 4: Run TUI/runtime lifecycle tests.**

### Task 5: Core and session responsibility split

**Files:**
- Create: `src/codeagent/core/model_request.py`
- Create: `src/codeagent/core/tool_invocation.py`
- Modify: `src/codeagent/core/loop.py`
- Create: `src/codeagent/session/turn_runner.py`
- Create: `src/codeagent/session/compaction/service.py`
- Modify: `src/codeagent/session/session.py`
- Test: `tests/core/`, `tests/session/`

- [ ] **Step 1: Add import/size guard tests** that define the intended module boundaries without changing runtime behavior.
- [x] **Step 2: Extract model request preparation and tool invocation** while keeping existing private behavior and event order unchanged.
- [ ] **Step 3: Extract session turn commit/rollback and compaction coordination** behind explicit collaborators.
- [ ] **Step 4: Run core/session behavior tests and verify production modules stay below the repository size guideline where practical.**

### Task 6: Delivery verification

**Files:**
- Modify: `docs/code-review-2026-08-28.md`
- Modify: `docs/iteration/v0.4.md`
- Test: focused suites and OpenSpec validation

- [x] Run all focused tests for the changed areas (`805 passed` across the affected package suites).
- [x] Run `openspec validate --changes`, `openspec validate --specs`, and `git diff --check`.
- [x] Leave full test suite and cross-platform CI to the delivery owner, then update the audit report with verified results.
