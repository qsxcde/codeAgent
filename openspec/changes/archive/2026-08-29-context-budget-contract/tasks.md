## 1. Core 预算模型与估算

- [x] 1.1 在 `src/codeagent/core/` 新增 provider 无关的预算值对象,覆盖模型窗口、输出预留、保留余量、输入组成、估算来源/不确定性以及预算快照,并为非法负值和窗口边界提供明确校验。
- [x] 1.2 实现纯预算估算函数,统一计算 system prompt、工具定义、普通对话历史和工具结果,保证组成互斥、总量可复算、空工具列表为零,且不修改输入消息。
- [x] 1.3 在 `src/codeagent/core/ports.py` 增加可选的预算感知上下文准备契约,定义中立请求视图及返回的临时上下文语义,保留现有 `TransformContext` 类型和兼容适配路径。
- [x] 1.4 修改 `src/codeagent/core/loop.py` 的模型请求准备流程,在每次请求使用同一份临时上下文和预算视图,确保预算/转换失败按结构化错误结束,且不会污染本轮持久化消息。

## 2. 模型目录与组合根装配

- [x] 2.1 修正 `src/codeagent/ai/catalog/store.py` 对 `contextWindow`/`context_window` 的解析和正整数校验,在合法用户覆盖中保留上下文窗口元数据,对冲突或非法字段给出明确诊断。
- [x] 2.2 扩展模型选择/组合根的模型元数据解析,同时提供上下文窗口、输出限制、来源和 fallback/uncertain 标记,避免将缺失窗口伪装成精确能力。
- [x] 2.3 为 `ChatModelPort` 增加真实请求组成的中立描述能力,覆盖实际生效的 system prompt、工具定义和消息序列化边界,不得把 provider 类型泄漏到 `core`。
- [x] 2.4 增加模型目录和适配器回归测试:自定义窗口字段、camelCase/snake_case、非法值、空工具定义以及 system prompt/工具 schema 纳入预算。

## 3. Session 预算生命周期

- [x] 3.1 在 `src/codeagent/session/` 增加运行期预算状态,分别保存最近一次 estimate、最近一次 provider actual usage 和已提交 committed usage,并保持现有 `last_context_tokens` 与 JSONL 读取语义兼容。
- [x] 3.2 将 session/runtime 的请求开始、usage 事件和成功提交边界接入预算状态,验证失败、取消、清理不确定和提交失败轮次不会改变累计 usage。
- [x] 3.3 接入模型配置切换后的预算重算,确保下一请求使用当前模型窗口/输出限制,且不改写历史消息、父级链、压缩记录和既有 usage。
- [x] 3.4 增加 session 行为测试:请求前估算与响应后实际值并存、失败轮次隔离、大小窗口切换、进程恢复和历史持久化不变。

## 4. 契约与边界验证

- [x] 4.1 增加 core 预算纯函数、重复计算一致性、消息不变性和旧 `transform_context` 兼容性测试。
- [x] 4.2 增加跨层装配测试,验证完整请求组成的预算快照能从模型目录/组合根传到 runtime/session,并验证 `core` 不依赖 `ai`、`session`、`tools` 或配置模块。
- [x] 4.3 增加 provider 返回实际 usage 与 session 提交/累计 usage 的回归测试,覆盖缓存 token、输出 token 缺省以及部分 usage 场景。
- [x] 4.4 更新与上下文预算契约相关的实现注释和 v0.4 迭代记录,明确本变更完成后自动压缩、工具结果治理和 TUI 展示仍由后续变更负责。

## 5. 验证与交付

- [x] 5.1 运行预算、模型目录、core loop、session 相关窄测试并修复回归。
- [x] 5.2 运行 `openspec validate --changes` 与 `openspec status --change "context-budget-contract"`,确认所有规划产物完整且变更可进入 apply 阶段。
- [x] 5.3 在实现完成后运行项目要求的完整测试与导入边界检查,记录结果后再归档本变更。
