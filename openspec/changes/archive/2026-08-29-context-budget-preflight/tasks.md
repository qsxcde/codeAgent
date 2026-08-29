## 1. Core 预算前置判定模型

- [x] 1.1 在 `src/codeagent/core/` 增加 provider 无关的预算前置判定结果，固定 `safe`、`near_limit`、`over_limit`、`uncertain` 状态，并携带 `allowed`、原因、阈值和预算快照字段。
- [x] 1.2 实现纯判定函数：可确认预算按 `headroom` 判断超限和临界；不确定预算按 `uncertain_budget_policy` 判断是否允许发送；保证判定不修改消息、工具定义或预算快照。
- [x] 1.3 增加 token/比例互斥的警戒阈值配置与校验，提供稳定默认值，拒绝负数、非有限比例、同时配置或其它非法值。
- [x] 1.4 增加超预算和不确定阻断的结构化 core 错误，保留判定状态、输入估算、输入预算、余量和窗口来源。

## 2. ReAct 请求边界接入

- [x] 2.1 在每次模型请求的最终临时上下文准备完成后、调用 provider 前执行预算前置判定；工具结果、steer 和多轮 ReAct 请求不得复用旧判定。
- [x] 2.2 发布结构化 `context_preflight` 事件，明确安全、临界、超限和不确定状态，并保持现有 `context_budget` 估算事件语义。
- [x] 2.3 对 `over_limit` 和 `uncertain + fail` 在 provider stream/generate 之前阻断，确保不触发模型请求、工具执行、网络副作用或自动重试。
- [x] 2.4 将预算阻断接入现有 Agent 错误事件和唯一终态，不新增独立生命周期；保留可诊断的错误码、阶段和预算字段。
- [x] 2.5 确认 `uncertain + allow` 继续执行但显式保留不确定状态，`uncertain + fail` 在扩展和模型调用前结束，并兼容旧模型适配器。

## 3. Session 与组合根接入

- [x] 3.1 在 session 运行期状态中保存最近一次 `ContextPreflightResult`，每轮开始时重置，向上层提供读取接口但不写入 JSONL。
- [x] 3.2 校验预算阻断沿用失败轮次回滚、usage 不累计、消息不落盘和运行可再次启动的既有收尾边界。
- [x] 3.3 在 `app/composition` 透传默认阈值与 `uncertain_budget_policy`，确保 CLI、TUI、模型切换和会话恢复使用同一预算门禁语义。
- [x] 3.4 验证模型窗口切换后下一次请求重新进行前置判定，既有历史、压缩记录、父级链和 committed usage 不被改写。

## 4. 回归与契约测试

- [x] 4.1 增加纯函数测试，覆盖四种判定状态、token/比例阈值、边界相等值、负 headroom 和非法配置。
- [x] 4.2 增加 provider 调用边界测试，验证超预算时模型不被调用、工具无副作用、错误字段完整且终态唯一。
- [x] 4.3 增加多轮 ReAct 测试，验证工具结果或 steer 使后续请求重新计算预算，并分别产生对应的前置判定事件。
- [x] 4.4 增加 uncertain allow/fail 测试，覆盖预算扩展是否执行、模型是否执行、错误是否可重试以及旧适配器兼容性。
- [x] 4.5 增加 session 行为测试，验证预算阻断不改变 history、JSONL、最近一次 committed usage，调整模型/上下文后可以再次运行。
- [x] 4.6 增加 core 导入边界、组合根装配和现有事件序列回归测试，确保新增预算门禁不引入 provider/session/tools 反向依赖。

## 5. 文档与交付验证

- [x] 5.1 更新 `docs/iteration/v0.4.md`，将 V4-12 标记为实现范围并记录预算状态、阻断语义及未包含的自动压缩/工具结果治理。
- [x] 5.2 更新实现注释与相关 OpenSpec 交叉说明，确保 `context-budget-contract` 与本变更的边界清晰可追溯。
- [x] 5.3 运行预算、core、session、app 相关窄测试、`openspec validate --changes`、`openspec status --change "context-budget-preflight"` 和 `git diff --check`。
- [x] 5.4 在窄测通过后由交付方运行项目全量测试与跨平台 CI；确认结果后再归档本变更。
