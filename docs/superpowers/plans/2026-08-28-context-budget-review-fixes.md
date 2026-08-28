# Context Budget Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `context-budget-contract` 代码审查发现的预算边界、错误诊断、扩展隔离、模型恢复和交付验证问题。

**Architecture:** 保持 `core` provider/session 无关；预算值对象和请求扩展契约继续留在 `core`，中立工具摘要由组合根装配。Session 只维护运行期 estimate/actual 与持久化 committed 边界，模型选择和窗口元数据仍由组合根负责。

**Tech Stack:** Python 3.12+, pytest/pytest-asyncio, OpenSpec, uv。

**Spec:** `openspec/changes/context-budget-contract/specs/context-budget/spec.md`, `openspec/changes/context-budget-contract/specs/core/spec.md`, `openspec/changes/context-budget-contract/specs/sessions/spec.md`

## Global Constraints

- `core/` 不得导入 `config`、`ai`、`tools` 或 `session`。
- `session/` 不得导入 `ai`、`tools` 或 `config`。
- 测试必须离线，优先使用 `FakeClient`、`MemoryStore` 和 `tmp_path`。
- 不改变 JSONL 历史格式、父级链和已有 committed usage 语义。
- 本轮不执行项目全量测试；由用户执行并反馈结果。

---

### Task 1: 预算保留量和模型请求契约

**Files:**
- Modify: `src/codeagent/app/composition/model_factory.py`
- Modify: `src/codeagent/app/composition/runtime_factory.py`
- Modify: `src/codeagent/core/loop.py`
- Test: `tests/ai/test_model_types.py`
- Test: `tests/app/container/test_assembly.py`
- Test: `tests/core/test_context_budget.py`

**Interfaces:**
- `ChatModelPort.describe_context_budget()` 必须对任何正整数窗口生成合法的 `ContextBudgetSnapshot`。
- 当预算描述缺失或窗口不确定时，runtime 必须使用明确的 uncertain/controlled 语义，不得静默伪装为精确预算。

- [ ] **Step 1: Write failing tests**

```python
def test_catalog_model_with_small_context_window_keeps_budget_valid():
    registry = ModelRegistry()
    registry._catalogs.setdefault("fake", {})["tiny"] = ModelSpec(
        id="tiny", context_window=8_000
    )
    config = create_agent_config(provider="fake", model="tiny", registry=registry)
    snapshot = config.model.describe_context_budget([], [])
    assert snapshot.input_budget >= 0
    assert snapshot.output_reserve + snapshot.reserve_tokens <= 8_000
```

```python
@pytest.mark.asyncio
async def test_budget_preparation_failure_keeps_initial_estimate_for_diagnostics():
    # descriptor succeeds, preparer fails; the session must retain the estimate
    ...
```

- [ ] **Step 2: Run the focused tests and confirm the current failure**

Run: `uv run pytest tests/app/container/test_assembly.py tests/core/test_context_budget.py -q`

Expected: the tiny-window test fails with the reserve invariant error; the diagnostic test fails because no budget event is emitted before preparation.

- [ ] **Step 3: Implement the smallest budget normalization and event-order fix**

Normalize output/reserve values at composition time so their sum never exceeds the effective window. Emit the valid initial estimate before calling the budget-aware preparer, then emit the final estimate after preparation.

- [ ] **Step 4: Run the focused tests again**

Run: `uv run pytest tests/app/container/test_assembly.py tests/core/test_context_budget.py -q`

Expected: all selected tests pass.

### Task 2: 错误分类和不确定预算策略

**Files:**
- Modify: `src/codeagent/session/runtime/error_policy.py`
- Modify: `src/codeagent/core/loop.py`
- Modify: `src/codeagent/core/errors.py` only if a new controlled error is required
- Test: `tests/session/behavior/test_context_budget.py`
- Test: `tests/core/test_context_budget.py`

**Interfaces:**
- `ContextPreparationError` 的 `code`、`phase`、`cause_type` 必须在 Session 的最终错误事件中保留。
- 缺少预算描述器或无法确认窗口时，必须产生显式 uncertain 结果或受控错误，并保持旧模型端口兼容策略有文档说明。

- [ ] **Step 1: Write failing session-level regression tests**

```python
async def test_session_preserves_context_preparation_error_classification():
    # run a model whose budget descriptor raises; assert error_code is
    # context_preparation_failed and retryable is False.
    ...
```

```python
@pytest.mark.asyncio
async def test_model_without_budget_descriptor_has_explicit_uncertain_result():
    # assert the chosen controlled fallback behavior instead of silent None.
    ...
```

- [ ] **Step 2: Run the new tests and verify they fail for the current reasons**

Run: `uv run pytest tests/session/behavior/test_context_budget.py tests/core/test_context_budget.py -q`

Expected: the session reports `model_error` and a model without a descriptor has no budget snapshot.

- [ ] **Step 3: Preserve structured error metadata and implement the explicit uncertain policy**

Special-case `ContextPreparationError` before generic phase classification. Choose one documented fallback boundary and apply it consistently for missing and uncertain budget descriptions.

- [ ] **Step 4: Run the focused tests again**

Run: `uv run pytest tests/session/behavior/test_context_budget.py tests/core/test_context_budget.py -q`

Expected: all selected tests pass and no model stream starts after a controlled preparation failure.

### Task 3: 上下文扩展组合与隔离

**Files:**
- Modify: `src/codeagent/core/ports.py`
- Modify: `src/codeagent/core/loop.py`
- Modify: `src/codeagent/core/context.py` or add a focused neutral tool-definition type under `src/codeagent/core/`
- Test: `tests/core/test_context_budget.py`
- Test: `tests/contracts/test_agent_contracts.py`

**Interfaces:**
- `ContextPreparationRequest.tools` 只能暴露 provider/runtime 无关的工具定义摘要。
- 同时配置 `transform_context` 和 `context_preparer` 时，二者顺序必须明确且都可观察。
- 扩展修改消息对象不能影响源 `AgentContext` 或 Session 持久化历史。

- [ ] **Step 1: Write failing tests**

```python
def test_budget_aware_request_exposes_neutral_tool_definitions():
    # assert the preparer sees names/schemas, not the original executable tool.
    ...
```

```python
@pytest.mark.asyncio
async def test_context_hooks_compose_without_mutating_source_messages():
    # legacy transform and budget-aware preparer both run; a mutation in either
    # hook does not change the source context.
    ...
```

- [ ] **Step 2: Run the tests and confirm the current failures**

Run: `uv run pytest tests/core/test_context_budget.py tests/contracts/test_agent_contracts.py -q`

Expected: raw tool objects are exposed, the legacy hook is skipped, or source message content is changed.

- [ ] **Step 3: Implement isolated message copies, neutral tool summaries, and explicit hook composition**

Use cloned message/value data at the extension boundary, compose the old transform with the new preparer in one documented order, and keep executable tools inside the runtime only.

- [ ] **Step 4: Run the focused tests again**

Run: `uv run pytest tests/core/test_context_budget.py tests/contracts/test_agent_contracts.py -q`

Expected: all selected tests pass and the original context remains unchanged.

### Task 4: Session 模型恢复与窗口一致性

**Files:**
- Modify: `src/codeagent/session/manager.py`
- Modify: `src/codeagent/session/session.py`
- Modify: `src/codeagent/app/composition/session_factory.py` only if model restoration belongs at the composition boundary
- Test: `tests/session/test_session_manager.py`
- Test: `tests/session/behavior/test_context_budget.py`

**Interfaces:**
- Restoring an existing session must use its persisted latest model/effort metadata when resolving the next budget.
- Directly constructed `AgentSession` instances must not use a stale default window when the injected model exposes an effective window.

- [ ] **Step 1: Write failing recovery tests**

```python
async def test_switch_after_restart_restores_persisted_model_budget():
    # persist a model change, build a fresh manager, switch the session, and
    # assert the next budget uses the persisted model window.
    ...
```

```python
async def test_session_initial_window_follows_model_metadata_when_not_explicit():
    ...
```

- [ ] **Step 2: Run the tests and confirm the current manager/default-window failures**

Run: `uv run pytest tests/session/test_session_manager.py tests/session/behavior/test_context_budget.py -q`

- [ ] **Step 3: Restore model metadata at the correct composition boundary**

Load the persisted `SessionRef` before adoption, resolve the corresponding config/window, and preserve the current global-config behavior for callers that explicitly request it. Derive the initial session window from the model only when no explicit value was supplied.

- [ ] **Step 4: Run the focused tests again**

Run: `uv run pytest tests/session/test_session_manager.py tests/session/behavior/test_context_budget.py -q`

### Task 5: 文档、变更状态和验证

**Files:**
- Modify: `openspec/changes/context-budget-contract/tasks.md`
- Modify: `openspec/changes/context-budget-contract/design.md` if the final uncertain/hook policy differs from the current text
- Modify: `docs/iteration/v0.4.md` if the completed scope changes

- [ ] **Step 1: Update the OpenSpec task notes with the implemented review fixes**

Record the final policy for reserve normalization, uncertain budgets, hook ordering, neutral tool views, and restart recovery. Do not mark full-suite task 5.3 complete before the user provides its result.

- [ ] **Step 2: Run focused verification**

Run: `uv run pytest tests/core tests/ai tests/session tests/app/container -q`

Expected: all selected tests pass.

- [ ] **Step 3: Run architectural and specification checks**

Run: `uv run pytest tests/test_decoupling.py tests/contracts/test_ai_import_boundaries.py tests/contracts/test_session_boundaries.py tests/contracts/test_agent_contracts.py -q` and `openspec validate --changes`.

Expected: all boundary tests and OpenSpec validation pass.

- [ ] **Step 4: Report that the full suite remains user-owned**

Do not claim full completion until the user runs `uv run pytest -q` and provides the result.
