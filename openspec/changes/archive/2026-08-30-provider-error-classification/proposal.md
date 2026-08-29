## Why

模型请求目前把 HTTP、网络和超时失败以底层 `httpx` 异常直接抛出。不同 Provider 的错误响应格式无法稳定地被上层识别，限流等待信息、认证失败、参数不支持和可重试服务端故障也因此难以向用户和诊断层表达。

## What Changes

- 建立统一的 Provider 错误分类契约，覆盖网络、超时、限流、认证、无效请求、参数不支持、服务端和未知错误。
- 从响应头和响应体提取状态码、请求 ID、`Retry-After`、Provider、模型和受限长度的脱敏详情。
- 让 OpenAI 兼容传输的非流式与流式请求使用同一套分类结果，同时保留 HTTP 状态异常的兼容性。
- 让内置 Provider 工厂向传输层传递 Provider 标识，便于错误诊断定位来源。

## Capabilities

### New Capabilities

- `provider-errors`: 为模型调用提供稳定、可重试性明确且不泄露凭据的错误分类。

### Modified Capabilities

<!-- No existing requirement changes; this is a new AI infrastructure capability. -->

## Impact

- 影响 `src/codeagent/ai/transport/`、`src/codeagent/ai/providers/` 和 AI 顶层导出。
- 增加错误分类单元测试及流式/非流式传输回归测试，不引入新依赖。
- 上层可捕获新的 Provider 错误并读取结构化诊断字段；HTTP 错误仍保持 `httpx.HTTPStatusError` 的类型兼容。
