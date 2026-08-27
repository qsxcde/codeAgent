## Context

测试数量已达到 923 个，但 `tests/tui/test_view.py`、`tests/session/test_store.py`、`tests/session/test_session.py`、`tests/test_container.py` 和 `tests/tools/test_tools.py` 同时包含多个行为域。当前已有 FakeClient、MockTransport、Textual run_test、MCP 子进程和 Git 临时仓库测试，但这些测试没有统一表达单元、契约、集成和端到端边界。

## Goals / Non-Goals

**Goals:**

- 让测试文件按行为职责可定位、可维护。
- 把跨实现复用的行为抽成契约测试，特别是 Store、Provider 和 Tool。
- 补齐核心用户路径、平台差异和当前已确认的行为缺口,包括会话 `last_activity_at` 的跨层产品契约。
- 维持现有测试的离线、无密钥和可重复特性。

**Non-Goals:**

- 不以“测试文件数量增加”为目标。
- 不用快照替代所有细粒度行为断言。
- 不在本变更中接入真实 Provider 或真实网络服务。
- 不自动保留已经决定删除的兼容入口；兼容测试需逐项确认其生命周期。

## Decisions

### 1. 按行为域拆分大型测试文件

优先拆分 TUI 生命周期、命令、会话、确认、状态和 Skill/MCP；Session Store 拆分 JSONL、MemoryStore、索引、分叉和压缩；工具拆分原子工具、bash、执行器和安全策略。保留 `tests/` 与 `src/` 的总体镜像关系，避免完全改成与源码无关的目录。

### 2. 以契约测试消除实现重复

为 Store 定义共享场景集合，让 JSONL Store 和 MemoryStore 使用同一组行为断言；Provider、Tool 和 Agent 端口也采用最小契约测试。实现特有的文件权限、进程和序列化细节继续放在专属测试中。

### 3. 明确测试层级

使用 `unit`、`contract`、`integration`、`e2e`、`platform`、`security` 和 `performance` marker。MCP 子进程、Git 临时仓库、真实 Textual backend 和 CLI subprocess 不进入最小单元门禁。

### 4. 先补高风险行为，再补边缘覆盖

优先覆盖会话恢复与 `last_activity_at`、失败回滚、工具确认与取消、MCP 生命周期、bash 进程清理、路径边界和 TUI 提交流程。`last_activity_at` 的模型、两种存储后端、JSONL 索引、旧格式回退和最近排序在本变更中成套交付。

### 5. 兼容测试必须有生命周期标记

像 `tests/session/test_store_modules.py` 这类兼容入口测试应标明“长期公共契约”或“迁移期临时契约”。临时兼容测试不能无期限阻止旧入口删除。

## Risks / Trade-offs

- [拆分过程中遗漏或重复测试] → 先建立测试清单和收集数量基线，迁移后逐文件核对。
- [契约测试抽象过度] → 只抽取跨实现共同语义，文件格式、平台和性能细节保留在专属测试。
- [平台测试使普通 PR 变慢] → 依赖 marker 分层，快速门禁只执行稳定、平台无关部分。
- [TUI 快照对终端差异敏感] → 优先测试渲染模型和关键文本语义，端到端终端快照只覆盖少量核心场景。

## Migration Plan

1. 依赖 `test-foundation-stability` 完成 marker、fixture 和稳定性基础。
2. 为大型测试文件建立行为清单，逐个拆分并保持断言等价。
3. 抽取 Store、Provider、Tool 和边界契约测试。
4. 增加 CLI、MCP、TUI、会话时间戳和平台差异测试。
5. 标记并清理已过期的兼容入口测试。

回滚方式是恢复测试文件路径和导入，不涉及生产代码或数据迁移。
