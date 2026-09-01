## 1. 契约与测试夹具

- [x] 1.1 增加 `delegate` 工具、串行 runner 和子 Session 工厂的失败优先测试夹具，覆盖 FakeClient、父运行绑定和活动委派清理。
- [x] 1.2 增加 `subagent-runtime` 的组合边界测试，固定未启用 runner 时不注入工具、子配置不含 `delegate`、父子身份独立和父历史隔离。

## 2. Delegate 工具与运行器

- [x] 2.1 在 `app/composition/subagent/` 创建职责清晰的工具、runner 和工厂模块，使用 core Subagent contract，不让 core 反向依赖应用层。
- [x] 2.2 实现 `DelegateTool` 的 schema、参数校验、委派请求生成、父 run 绑定和 `SubagentResult` 到 `ToolResult` 的有界映射。
- [x] 2.3 实现串行 runner 的队列/活动表、子 Session 创建、成功/失败结果归一化和异常/取消收尾。
- [x] 2.4 实现按 `delegation_id` 取消活动子运行，并保证未知委派不影响其它运行。

## 3. 组合根接入

- [x] 3.1 让 root Agent 配置和 AgentSession/SessionManager 通过组合根共享可选 runner，并为子 Session 提供 `enable_subagents=False` 的隔离装配路径。
- [x] 3.2 在 Session execution 复制工具配置时绑定当前父 run_id，补充公开的活动 run 诊断所需最小接口，不改变现有 AgentTool 公共签名。
- [x] 3.3 保证临时子 Session 不写入用户 SessionStore，子运行结束时模型、MCP 和工具 runtime 都被关闭。

## 4. 验证与文档

- [x] 4.1 运行新增的 unit/contract/integration 测试并修复实现，确认父 Agent 能在 FakeClient 的 delegate tool call 后继续完成下一轮。
- [x] 4.2 更新 `docs/iteration/v0.5.md` 的 V5-02 状态和实现记录，记录非目标能力交由后续 change。
- [x] 4.3 运行 Ruff、`git diff --check`、OpenSpec strict validation 和完整离线测试，确认无单 Agent 回归。
