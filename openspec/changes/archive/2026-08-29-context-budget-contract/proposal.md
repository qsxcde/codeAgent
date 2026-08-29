## Why

当前会话只把 `context_window` 用于请求结束后的阈值压缩，消息估算、系统提示词、工具定义、工具结果和输出预留却分散在不同层。长对话、多个大工具结果或切换到更小窗口模型时，系统可能先把超预算请求发送给 Provider，最终得到延迟高且难以解释的窗口错误。现在需要先建立统一的预算契约，为后续请求前检查、压缩、工具结果治理和诊断提供单一事实来源。

## What Changes

- 引入与 provider 无关的上下文预算模型，统一描述模型窗口、输出预留、系统提示词、工具定义、历史消息和工具结果的估算值。
- 明确区分本地请求前估算、模型返回的实际 usage 和会话累计用量，禁止将它们混作同一个 `context_tokens` 状态。
- 为 Agent Runtime 增加预算感知的上下文准备契约，使扩展可以基于完整请求组成生成模型可见上下文，同时保持 `core` 不依赖 `ai`、`session`、`tools` 或配置实现。
- 让模型目录中的上下文窗口元数据可被可靠读取，并与当前模型选择结果绑定；缺失元数据时保留显式的保守兜底状态。
- 为后续请求前预算检查、自动压缩和 TUI/CLI 诊断预留稳定的状态字段与事件语义；本变更不实现自动压缩策略或 UI 展示。

## Capabilities

### New Capabilities

- `context-budget`: 定义一次模型请求的预算组成、估算状态、保留余量和模型能力元数据来源。

### Modified Capabilities

- `core`: 扩展模型请求前的上下文准备端口，使其能够消费预算感知的临时上下文视图而不改变持久化历史。
- `sessions`: 明确会话上下文窗口、请求前估算和 provider 实际 usage 的边界，为后续压缩策略提供一致输入。

## Impact

- 影响 `src/codeagent/core/ports.py`、`src/codeagent/core/loop.py` 的上下文准备契约，以及 `src/codeagent/core/context.py` 的中立上下文类型。
- 影响 `src/codeagent/session/` 中上下文状态和压缩策略的输入，但不删除 JSONL 历史、不改变现有父级链语义。
- 影响 `src/codeagent/ai/catalog/` 与 `src/codeagent/app/composition/` 的模型窗口元数据解析和装配。
- 需要新增预算估算、模型目录解析、模型适配器请求组成和端口边界测试；不依赖真实 API key 或网络。
- 可能新增一个可选的上下文准备端口；现有简单转换器应通过明确的适配路径继续可用，避免把 provider/session 细节泄漏到 `core`。
