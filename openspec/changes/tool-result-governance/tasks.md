## 1. 结果契约与 core 归一化

- [x] 1.1 在 `src/codeagent/core/contracts/` 定义向后兼容的工具输出元数据值对象或 envelope，覆盖完整性、总量、展示量、截断原因、路径/范围、退出码、耗时、stderr 摘要、变更摘要和可选引用，并补充字段边界的 unit 测试
- [x] 1.2 修改 `src/codeagent/core/execution/result.py` 的 `normalize_tool_result`，完整保留已有 `ToolResult` 和适配器结果的结构化字段；对旧字符串结果生成 legacy/unknown 元数据，不再凭缺省字段推断完整成功
- [x] 1.3 修改 `src/codeagent/app/composition/tools/adapter.py`，将 duck-typed 工具返回值映射为统一结果事实，并为字段缺失、失败和治理不确定路径补充 contract 测试
- [x] 1.4 贯通 `src/codeagent/core/orchestration/batch.py`、`src/codeagent/session/runtime/event_translation.py` 和 `src/codeagent/core/orchestration/turn.py`，使工具事件与 tool message 保留同一结果快照、tool_call_id 和模型回填顺序

## 2. 工具级硬限制与结果策略

- [x] 2.1 在 `src/codeagent/tools/shared/` 实现公共 result governor、限制配置和按工具类别选择的输出策略，统一记录原始统计、展示统计、截断原因与可恢复性
- [x] 2.2 重构 `src/codeagent/tools/execution/process.py` 及 bash 执行链路为有界输出采集，分别处理 stdout/stderr、退出码、超限后的继续消费或终止行为，并覆盖超大流式输出的内存边界测试
- [x] 2.3 接入 read、grep、find、ls、write、edit 等原子工具的策略，保留路径、范围、计数、继续参数和变更摘要；为头部/尾部/列表裁剪与空结果增加回归测试
- [x] 2.4 接入 `src/codeagent/tools/mcp/` 与 skill 结果治理，统一限制文本块并对图片、音频、二进制和未知块生成 unsupported/reference 结构化诊断，覆盖非文本 MCP 内容测试
- [x] 2.5 检查工具结果、事件和日志的脱敏边界，确保 governor、stderr 摘要、artifact_ref 和统计信息不复制凭据或无界原始输出

## 3. 下一请求上下文预算

- [x] 3.1 在 `src/codeagent/core/` 的上下文预算与请求组装路径中引入单次请求预算快照，按模型上下文、输出预留、headroom、system prompt、工具定义和历史消息计算工具结果可用空间
- [x] 3.2 实现基于工具策略的确定性二次裁剪/摘要/跳过，保留路径、退出码、错误、变更摘要、继续参数、总量和完整性，并确保不使用累计 usage 或上一模型的预算
- [x] 3.3 为模型切换、provider usage 缺失、多工具结果共享预算、精确边界和估算/不确定标记补充 context-budget unit/contract 测试

## 4. 会话元数据与恢复

- [x] 4.1 扩展 `src/codeagent/session/persistence/codec.py` 及相关消息模型，以可选 JSON 字段保存有界 tool message 元数据和不透明引用，同时保持旧 JSONL 字段与未知字段兼容
- [x] 4.2 将成功提交、失败、取消和事务回滚路径接入元数据提交规则，确保未提交结果不进入会话历史，截断且无 artifact 的结果恢复为 incomplete/unavailable
- [x] 4.3 增加 session 持久化回归测试，覆盖新旧 JSONL 读取、字段恢复、敏感原文不落盘、失败轮次不污染历史和恢复后未知完整性状态

## 5. TUI 结构化结果视图

- [x] 5.1 修改 `src/codeagent/app/tui/presentation/output.py` 的 `OutputBuffer`，保存结构化结果 snapshot 与有界预览，将 legacy marker parser 限定为缺少结构化字段时的 unknown/legacy 回退
- [x] 5.2 更新 `src/codeagent/app/tui/` 的工具结果块与摘要渲染，展示状态、路径/范围、退出码、耗时、变更摘要、总量、展示量和截断诊断，并让结构化字段优先于文本标记
- [x] 5.3 调整 TUI 展开、翻页和 `/output` 导出能力，使其只操作本地展示游标或已有安全 artifact；对不可恢复截断拒绝虚假完整导出，并覆盖恢复后的结果块测试

## 6. 集成验证与文档

- [x] 6.1 增加跨层离线集成测试，验证工具采集到 normalize、事件、tool message、下一请求预算、JSONL 恢复和 TUI 投影的完整性事实一致，包含并行工具结果身份与顺序
- [x] 6.2 更新 `docs/` 和 `docs/iteration/v0.4.md`，记录两级限制、工具策略、unknown/legacy 兼容语义、不可恢复截断和 TUI 导出边界
- [x] 6.3 运行相关 unit/contract/integration 测试、`uv run ruff check src tests scripts`、`git diff --check`、`openspec validate --specs` 和完整 `uv run pytest -q`，修复本变更引入的回归后确认所有任务验收条件
