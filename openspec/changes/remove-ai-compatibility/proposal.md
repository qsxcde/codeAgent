## Why

上一轮 AI 层重构已经把模型契约、传输实现和 provider/model 选择迁移到规范路径，但旧兼容 façade 仍保留在 `ai/` 中。它们继续暴露应用装配和旧协议路径，容易让新代码误用，也使 `ai/` 的职责边界不够清晰；当前仓库内部调用方已经完成迁移，适合移除这段短期兼容期。

## What Changes

- **BREAKING** 删除 `src/codeagent/ai/factory.py`，模型客户端创建、provider 列表和模型选择统一从 `codeagent.app.composition.model_selection` 使用。
- **BREAKING** 删除 `src/codeagent/ai/model_pattern.py`，`model:effort` 解析统一使用组合根中的 `split_model_pattern`。
- **BREAKING** 删除 `src/codeagent/ai/protocol/` 下的旧协议与 SSE re-export；模型类型和协议从 `codeagent.ai.model` 导入，SSE 解析器从 `codeagent.ai.transport.sse` 导入。
- 更新测试、README、架构说明和维护指南中的旧路径，移除兼容 façade 专用测试与描述。
- 增加静态引用检查和 canonical import 回归测试，确保源码不再依赖被删除的入口，同时确认 AI 层仍不反向依赖应用组合根。
- 保留 `ai/model/`、`ai/providers/`、`ai/transport/` 和 `ai/catalog/` 的现有行为；不改变 provider、SSE、工具调用、usage 或模型目录语义。

## Capabilities

### New Capabilities

- `ai-import-boundaries`: 定义 AI 层模型契约、传输解析器和应用级模型装配的规范导入路径，以及旧兼容入口删除后的失败边界。

### Modified Capabilities

无。当前 OpenSpec 没有既有 AI 导入边界规格，本变更新增该能力契约。

## Impact

- 受影响代码：`src/codeagent/ai/factory.py`、`src/codeagent/ai/model_pattern.py`、`src/codeagent/ai/protocol/` 及其测试和文档引用。
- 受影响 API：直接导入旧模块的外部调用方需要迁移；旧路径不再提供运行时兼容保证。
- 不影响运行时分层：应用组合根继续负责读取配置、解析模型和构造客户端；AI 层继续只提供模型、provider、transport 和 catalog。
- 验证范围：本变更提供窄范围测试与静态检查；完整测试由用户在应用变更后执行并反馈结果。
