## 1. 建立新 Core 契约

- [x] 1.1 全仓盘点 `AgentPorts`、`run_turn`、`ModelPort`、`StreamEvent`、`AgentEvent`、`ToolExecutionRuntimePort` 和旧确认队列的生产代码、测试与文档引用，形成迁移清单
- [x] 1.2 在 `core` 中定义 `AgentContext`、`AgentLoopConfig`、`AgentTool`、模型流事件、扩展 hook 和新的错误类型，明确 core 不依赖 `ai`、`session`、`tools`、`config`
- [x] 1.3 增加新契约的最小单元测试，覆盖上下文复制、工具列表、hook 类型和非法继续条件

## 2. 收敛消息与模型适配边界

- [x] 2.1 将 `core.messages` 收敛为 Agent Runtime 消息、ToolCall、ToolResult 和通用 details，移除 provider 原始参数解析及工具专用输出字段
- [x] 2.2 将持久化 `parent_id`、压缩虚拟消息、分支关系和 JSONL 相关字段迁移到 `session` 侧适配，不改变 session 恢复语义
- [x] 2.3 更新 `app/composition/model_factory.py`，把 `ai.model` 的 ChatMessage、StreamEvent 和工具参数转换为新的 core 模型端口形状
- [x] 2.4 增加模型适配回归测试，覆盖文本、thinking、usage、tool-call delta、参数错误和 system prompt 注入

## 3. 统一工具执行协议

- [x] 3.1 定义 `AgentTool` 的名称、描述、参数 schema、异步执行、取消信号和进度回调协议，并为 Atomic Tool、MCP Tool 和 Fake Tool 提供适配
- [x] 3.2 修正 `ToolExecutionRuntimePort` 与实际调用签名，统一 operation id、超时、取消、清理确认和结构化结果字段
- [x] 3.3 由组合根创建并注入共享工具执行器，移除 loop 中每次调用新建执行器的死路径，确保 `cancel_all` 有明确生命周期调用方
- [x] 3.4 实现 parallel/sequential 工具执行模式，保证完成事件按真实完成顺序发布、tool result 按原始调用顺序回填
- [x] 3.5 增加并发上限、单工具失败隔离、超时、同步工具清理不确定和取消回归测试

## 4. 实现纯内存 Agent Loop

- [x] 4.1 将 `run_turn` 拆分为低层 `run_agent_loop` 与 `run_agent_loop_continue`，返回本轮新增消息，不返回完整历史
- [x] 4.2 实现内存 `Agent` 外壳，提供 prompt、continue、abort、steer、follow-up 和订阅能力，不引入持久化或压缩依赖
- [x] 4.3 将模型请求前上下文转换、工具前置拦截、工具结果后处理和 turn 停止判断接入主循环
- [x] 4.4 将确认队列、`_call_summary` 和具体 `ApprovalPolicy` 逻辑移出 loop，改由 app/session hook 适配器提供 allow/block 决策
- [x] 4.5 实现明确的 Agent、turn、message、模型流和工具生命周期事件，统一错误、取消和循环超限收尾
- [x] 4.6 明确 steer 与 follow-up 的队列边界，确保 steer 不残留到下一次独立 run，continue 不重复追加 user 消息

## 5. 重构 Session 外壳

- [x] 5.1 将 `AgentSession` 改为持有或包装 core `Agent`，由 session 负责 session id、历史加载和运行提交
- [x] 5.2 保留成功轮次持久化、失败/取消回滚、分支父子关系、usage 统计和上下文压缩行为，移除对旧 `run_turn` 返回完整历史的依赖
- [x] 5.3 在 session 层将 Agent 事件适配为 `session_started`、restore、compaction、confirmation 和既有 TUI/CLI 用户体验事件
- [x] 5.4 修正 SessionRuntime 的取消、steer、确认响应和共享执行器生命周期，增加无悬挂任务与资源释放断言

## 6. 接入上层扩展

- [x] 6.1 将安全分类器和 headless/TUI 确认流程适配为 `before_tool_call`，保持 deny/ask/allow 与拒绝结果语义
- [x] 6.2 将 Memory 接入 `transform_context`，确保扩展只修改本次模型可见上下文，不改写 session 原始历史
- [x] 6.3 将 MCP 工具通过 `AgentTool` 接入，保持命名、权限、预算、超时、取消和显式关闭语义
- [x] 6.4 保持 Skill 和分层上下文继续由 app/composition 构建 system prompt 或工具描述，core 不读取 Skill 文件
- [x] 6.5 更新组合根、CLI、TUI 和 runtime close 流程，确保模型、工具、hook 和 Session 资源按依赖方向装配

## 7. 清理旧边界与验证

- [x] 7.1 删除旧 `AgentPorts`/`run_turn` 专用实现、无调用方辅助函数和 core 内的应用级事件/字段，完成仓库内部引用迁移
- [x] 7.2 增加旧 core 入口失败或不再导出的边界测试，并强化依赖方向检查，禁止 core 反向导入 ai、session、tools、config
- [x] 7.3 更新 `core`、`session`、`ai`、`tools`、`app/composition` 的架构文档、README 和 API 迁移说明
- [x] 7.4 运行 core 单测及编译检查，再运行 session/composition/tools/TUI 相关窄范围测试，修复契约或事件顺序问题
- [x] 7.5 运行 `openspec validate "refine-core-agent-runtime" --type change`、`openspec validate --specs` 和全量测试，记录破坏性迁移结果
