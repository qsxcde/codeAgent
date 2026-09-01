## 1. 契约边界与失败优先测试

- [x] 1.1 增加 `delegate` 对 `read_only`/`review` profile、显式 context、未知字段、空值和边界超限的参数映射测试。
- [x] 1.2 增加 profile 装配测试，验证两个 profile 的实际工具白名单、角色提示、不包含 `delegate`/写入/shell，以及 task-only 调用保持兼容。
- [x] 1.3 增加 FakeClient 子输入测试，验证只出现明确选择的 context 项，不出现父历史、父工具调用或未选择数据。

## 2. Profile 与显式上下文实现

- [x] 2.1 在 `app/composition/subagent/` 建立集中、不可变的 profile 规格，定义 `read_only`/`review` 的角色说明和只读工具白名单。
- [x] 2.2 在 `DelegateTool` 中扩展 schema 和参数解析，将合法 context 转换为 `SubagentContextItem`，执行项数、单项字符数和总字符数限制。
- [x] 2.3 新增子任务上下文渲染辅助，把 task 和 context 分段渲染为有界数据输入，并明确其不是系统指令。

## 3. 组合根与运行时接入

- [x] 3.1 让 runner 和子 Session 工厂接受 `review`，根据 profile 选择白名单和角色指令，并保持 `enable_subagents=False` 的递归隔离。
- [x] 3.2 为 Agent 配置/Session 装配增加可选角色指令入口，仅对子 Session 注入对应 profile 的系统提示，根 Agent 行为保持兼容。
- [x] 3.3 验证未知 profile、非法 context 和上下文诱导文本都不能创建越权子运行，且已有父级取消、清理和结果映射语义不变。

## 4. 文档与质量门禁

- [x] 4.1 运行新增的 unit/contract/integration 回归并修复实现，确认父 Agent 能在两种 profile 下继续完成下一轮回答。
- [x] 4.2 更新 `docs/iteration/v0.5.md` 的 V5-03 状态、实现记录和非目标边界。
- [x] 4.3 运行 Ruff、`git diff --check`、OpenSpec strict validation、分层测试、完整离线测试和构建检查。
