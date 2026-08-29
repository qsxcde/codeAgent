## 1. Retry Policy

- [x] 1.1 新增纯传输重试策略模块，校验最大重试次数并提供有上限的指数/`Retry-After` 退避计算
- [x] 1.2 将非流式和流式 OpenAI 兼容请求接入统一策略，保持首事件后不自动重放

## 2. Runtime Semantics

- [x] 2.1 在 session runtime 中兼容识别结构化 Provider 错误，映射稳定错误代码并遵守副作用安全闸门
- [x] 2.2 核对 core 工具执行边界，确保传输重试不包裹工具执行且无接口回退

## 3. Regression Tests

- [x] 3.1 增加重试次数校验、退避上限、`Retry-After` 和部分流失败不重放的单元测试
- [x] 3.2 增加真实 OpenAI 兼容 MockTransport 到 Agent 工具调用链路的“模型可重试、工具只执行一次”集成回归
- [x] 3.3 增加 session Provider 错误分类和副作用状态的回归测试

## 4. Documentation and Verification

- [x] 4.1 更新 v0.4 迭代状态、架构和测试基线文档
- [x] 4.2 运行窄测试、分层测试、完整测试、Ruff、差异检查、构建和 OpenSpec 验证，完成后标记变更
