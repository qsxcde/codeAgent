# model-retries Specification

## Purpose
为模型请求提供有限、可诊断且不会重放工具副作用的自动重试能力，降低短暂网络或服务故障对用户会话的影响。
## Requirements
### Requirement: Automatic retries are bounded and classified

模型传输 SHALL 只对 Provider 错误分类明确标记为可重试的模型请求失败执行自动重试；最大重试次数 SHALL 是有限且经过校验的非负整数，并 SHALL 受系统上限约束。认证失败、无效请求、不支持的参数、未知错误和上下文预算失败 SHALL 不触发自动重试。

#### Scenario: Retryable model failure is retried within the limit

- **WHEN** 完整模型响应前发生网络、超时、限流或服务端失败，且仍有剩余重试次数
- **THEN** 传输层按有限次数重新发起模型请求，最终成功则返回成功响应

#### Scenario: Retry limit is rejected when invalid

- **WHEN** 配置的最大重试次数为负数、超过系统上限或不是严格整数
- **THEN** 客户端在构造阶段拒绝配置并给出可诊断的参数错误

#### Scenario: Non-retryable model failure is returned immediately

- **WHEN** 模型请求失败被分类为认证、无效请求、不支持的参数、未知错误或上下文预算错误
- **THEN** 传输层不再次发起该模型请求，并保留结构化错误分类供上层展示

### Requirement: Backoff is finite and honors safe retry hints

自动重试 SHALL 使用逐步增加但有上限的等待时间；Provider 提供的可解析 `Retry-After` SHALL 在非负且不超过系统上限时优先使用，超出上限的值 SHALL 被限制在系统上限内。重试等待 SHALL 不无限阻塞取消和会话恢复。

#### Scenario: Retry-After controls a bounded delay

- **WHEN** 可重试响应带有合法的 `Retry-After` 延迟
- **THEN** 下一次请求使用该延迟作为退避，并且等待时间不超过系统上限

#### Scenario: Exponential fallback is capped

- **WHEN** 可重试失败没有可用的 `Retry-After`
- **THEN** 客户端使用指数退避，并将等待时间限制在系统上限内

### Requirement: Partial streams are never replayed automatically

流式模型请求 SHALL 仅在尚未向上层产出任何事件时自动重试；一旦产出文本、推理、工具调用、用量或其它流事件，后续传输失败 SHALL 结束当前请求并返回分类错误，不得重新播放已产出的前缀。

#### Scenario: Stream failure before the first event can retry

- **WHEN** 流式请求在收到首个事件前发生可重试失败且仍有剩余次数
- **THEN** 客户端重新建立流并继续等待首个事件

#### Scenario: Stream failure after an event is not replayed

- **WHEN** 流式请求已经产出至少一个事件后发生可重试失败
- **THEN** 客户端不发起重试，调用方收到分类错误并保留已有事件

### Requirement: Tool execution stays outside the retry boundary

模型请求自动重试 SHALL 不包含工具执行；只有完整模型响应被成功接收后，编排层才可执行其中的工具调用。同一个模型响应产生的工具调用 SHALL 不因传输重试而重复执行。

#### Scenario: Model retry followed by a tool call executes once

- **WHEN** 第一次模型请求临时失败，后续请求返回工具调用并完成该轮模型交互
- **THEN** 模型请求可重试，但对应工具只执行一次，随后继续正常处理工具结果

#### Scenario: Tool-side failure is not hidden by model retry

- **WHEN** 工具已经开始执行后本轮失败
- **THEN** 该失败交由会话副作用状态和安全重试策略处理，不由模型传输层自动重放工具调用
