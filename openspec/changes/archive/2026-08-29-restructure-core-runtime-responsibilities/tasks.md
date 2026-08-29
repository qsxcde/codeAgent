## 1. 建立契约与迁移护栏

- [x] 1.1 扫描源码、测试和组合根中所有 `Args`、`args_schema`、`invoke`、`ainvoke`、`invoke_async` 的工具调用点，形成迁移清单并确认没有遗漏的直接调用方。
- [x] 1.2 为严格 `AgentTool.execute(...)`、统一 `ToolResult` 和清理状态补充 core 契约测试，覆盖成功、参数错误、异常、超时、取消、清理失败和清理不支持。
- [x] 1.3 扩展架构/静态检查，确保 `src/codeagent/core` 不再访问旧工具属性，且继续禁止导入 `config`、`ai`、`tools`、`session`。
- [x] 1.4 固定当前 core 的事件顺序、并发回填顺序、steer、follow-up、失败回滚和上下文预算行为基线。

## 2. 建立工具适配边界

- [x] 2.1 在 `src/codeagent/tools/` 或 `src/codeagent/app/composition/` 新增显式 AgentTool 适配模块，定义名称、描述、provider-neutral 参数和统一执行结果的转换规则。
- [x] 2.2 为 AtomicTool 适配器实现参数校验、异步执行、异常转换、进度回调和清理状态转换；同步底层调用必须在线程中执行并报告不可抢占状态。
- [x] 2.3 为 MCP 工具实现同一 AgentTool 适配契约，保留 `mcp__<server>__<tool>` 名称和原有参数/结果语义，不让 MCP 类型进入 core。
- [x] 2.4 修改组合根工厂，使传给 `AgentLoopConfig` 的工具全部是适配后的 AgentTool，并增加内建工具和 MCP 工具装配契约测试。

## 3. 收紧 core 端口与模型请求

- [x] 3.1 修改 `src/codeagent/core/ports.py` 的类型契约，使 `AgentTool`、`ToolExecutionRuntimePort`、`ModelPort` 和 `AgentLoopConfig` 使用明确的 core 类型，并补充统一清理契约。
- [x] 3.2 修改 `src/codeagent/core/model_request.py`，只从 AgentTool 读取 `name`、`description` 和 `parameters`，删除 `args_schema.model_json_schema()` fallback。
- [x] 3.3 修改工具调用流程，使 before/after hook 只处理 AgentTool 和 ToolResult，不再构造或探测旧式 `Args/invoke` 工具。
- [x] 3.4 保留 `TransformContext`、context budget 和 context preflight 的现有兼容及事件语义，补充预算变更不受工具协议迁移影响的回归测试。

## 4. 拆分受控执行 runtime

- [x] 4.1 将 `ToolOperation`、`OperationRegistry` 和运行期状态迁移到独立的 `execution_state.py`，保持 operation id 和 active operation 行为不变。
- [x] 4.2 将取消、超时、清理 hook、清理诊断和不可抢占同步工具处理迁移到 `execution_cleanup.py`，保持 confirmed/failed/uncertain/unsupported 语义不变。
- [x] 4.3 将工具返回值和执行状态归一化迁移到 `execution_result.py`，确保 operation id、状态、错误和清理字段不丢失。
- [x] 4.4 重写 `execution.py` 为短 runtime façade，只保留并发槽管理、AgentTool 调用和模块协作；删除所有旧工具协议 fallback，并使文件小于 300 行、公共函数小于 80 行。
- [x] 4.5 运行执行 runtime 窄测试，覆盖并发上限、串行模式、超时、取消、同步线程和清理失败场景。

## 5. 拆分 ReAct loop 与工具批次

- [x] 5.1 将单轮模型请求、steer 注入和 stop-after-turn 判定迁移到 `turn.py`，保持模型请求前上下文准备和 preflight 调用顺序。
- [x] 5.2 将并行/串行工具批次、完成顺序事件、原始调用顺序回填和取消收尾迁移到 `tool_batch.py`。
- [x] 5.3 将单个工具调用的前置决策、runtime 调用、after hook 和结果构造迁移到窄职责模块，并删除无外部依赖的 `tool_invocation.py` 或将其缩减为非兼容内部实现。
- [x] 5.4 简化 `loop.py` 为公共运行入口和生命周期协调，使 `_run_agent_loop` 小于 80 行且不直接解析具体工具实现。
- [x] 5.5 保持 `core/__init__.py` 的规范 re-export，迁移全部内部 import，确认没有循环依赖或模块级可变服务状态。

## 6. 测试分层与兼容移除验证

- [x] 6.1 将 `tests/core` 中依赖真实 Bash、文件系统或 MCP 边界的测试迁移到 contract/integration 分类，core 单元测试改用 fake ModelPort 和 fake AgentTool。
- [x] 6.2 增加未适配旧工具传入 core 时的明确失败测试，确认系统不会隐式调用 `Args`、`invoke`、`ainvoke` 或 `invoke_async`。
- [x] 6.3 增加内建工具和 MCP 适配器的离线回归测试，验证名称、参数 schema、结果内容、取消和清理诊断保持原语义。
- [x] 6.4 运行 core、tools、composition 和 contracts 的窄测试，修复行为或事件顺序回归。

## 7. 最终验证与交付

- [x] 7.1 运行 `uv run ruff check src tests`、规模检查和 `git diff --check`，确认 core 生产文件均不超过 300 行、函数均符合规模要求。
- [x] 7.2 运行 `uv run pytest -m "unit or contract" -q --strict-markers` 及完整离线测试，确认无旧工具入口调用。
- [x] 7.3 运行 `openspec validate --changes` 并检查 `restructure-core-runtime-responsibilities` 状态，确认实现、测试和规格一致。
- [x] 7.4 更新架构文档和迁移说明，记录 AgentTool 是唯一 core 工具协议以及旧工具调用方的迁移方式。
