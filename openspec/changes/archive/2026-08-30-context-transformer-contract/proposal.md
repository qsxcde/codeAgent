## Why

当前 `transform_context` 与预算感知上下文扩展虽已接入运行时，但输入副本、输出校验、调用顺序、超时和失败语义主要依赖实现细节。缺少稳定契约会让记忆、压缩等后续扩展难以安全组合，也可能把非法上下文或长期阻塞带到 provider 请求边界。

## What Changes

- 明确 ContextTransformer 的 provider-neutral 输入、输出和每次模型请求作用域。
- 固化旧式 `transform_context` 与预算感知上下文扩展的调用顺序及隔离规则。
- 为上下文扩展增加可配置的单次调用超时，并区分超时诊断与普通准备失败。
- 校验扩展返回的消息集合；扩展失败、超时或返回非法值时阻断当前模型请求，不回退为未变换上下文。
- 保留现有消息列表形式的 `transform_context` 兼容入口，并通过协议类型暴露稳定契约。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `context-budget`: 补齐上下文扩展的输入、输出、顺序、超时、失败和回退契约。
- `core`: 补齐 Agent Runtime ContextTransformer 的稳定协议和错误语义。

## Impact

- 影响 `src/codeagent/core/context/contracts.py`、`core/model/request.py`、`core/orchestration/config.py` 及错误导出。
- 影响 AgentLoopConfig 的公开配置类型，新增可选的上下文扩展超时配置。
- 增加 core、contract 和 session 回归测试；同步 context-budget 与 core 的 OpenSpec 主规格及 v0.4 进度文档。
- 不新增第三方依赖，不改变持久化消息格式。
