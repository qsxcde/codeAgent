## 1. 预算契约与入口边界

- [x] 1.1 为 `SubagentResult.cleanup_uncertain`、有限数值校验和预算入口补充 core/app 契约测试，覆盖旧请求兼容、非有限 timeout、未知字段、类型错误和超过硬上限。
- [x] 1.2 新增应用层 Subagent budget policy，固定默认值、硬上限、父运行 4 个子任务配额，并提供请求预算解析/有效预算解析函数。
- [x] 1.3 扩展 `DelegateTool` 的 schema 和参数映射，绑定执行副本级父运行配额；超额或非法 budget 在创建子 Session 前返回结构化错误。

## 2. 运行器生命周期与预算执行

- [x] 2.1 先补充串行 runner 的预算回归测试：有效 max_turns 传入子工厂、`TURN_START`/`TOOL_QUEUED` 计数越界、预算耗尽原因码和后续父运行不受影响。
- [x] 2.2 先补充队列等待、活动子运行、确认等待和父级取消/超时的异步回归测试，确认只定位目标 delegation、不会遗留确认请求或挂起 child task。
- [x] 2.3 先补充不可合作 `cancel_and_wait`、事件观察任务和 `close` 失败/超时测试，确认有限等待后返回并设置 `cleanup_uncertain`。
- [x] 2.4 修改 `SerialSubagentRunner`：建立有效预算、单 runner 墙钟截止时间、活动取消原因和事件计数，区分 `parent_cancelled`、`timeout`、`budget_exceeded` 与普通执行失败。
- [x] 2.5 修改 runner 清理辅助：对 Session 取消、child task、事件任务和 close 采用共享的有限清理窗口，延后结果构造并回填清理诊断，避免无界等待和错误确认。

## 3. 子 Session 装配与结果映射

- [x] 3.1 修改子 Session 工厂，将有效 max_turns 映射到子 Agent 的 recursion limit，并保持 profile 工具白名单、独立上下文和无持久化边界。
- [x] 3.2 修改结果辅助和 `DelegateTool` ToolResult 映射，按有效 max_output_chars 截断摘要，传递 cleanup_uncertain/cleanup_status，且不把不确定清理标记为已确认。
- [x] 3.3 增加 FakeClient 组合回归，覆盖模型循环、工具调用上限、确认等待超时、父 Agent 继续回答、子 Session 关闭和父历史隔离。

## 4. 文档与质量门禁

- [x] 4.1 更新 `docs/iteration/v0.5.md`，记录 V5-04 的预算默认值、终止语义、清理不确定性和实现验证结果。
- [x] 4.2 运行相关 unit/contract/integration 测试、Ruff、`git diff --check` 和 OpenSpec strict validation，修复本变更引入的问题。
- [x] 4.3 运行完整离线测试与 `uv build`，检查差异、敏感文件和包内容，确认所有任务完成后再归档变更。
