## Context

模型目录已经保存 `reasoning`、`context_window` 和 `max_tokens`，预算端口也能提供窗口来源；但工具调用能力没有稳定数据模型，缓存能力只以本轮 usage 的偶发命中存在。TUI `/status` 目前只能展示上下文使用量和工具环境能力，不能回答“当前模型是否支持这些能力”。

## Goals / Non-Goals

**Goals:**

- 建立模型级、不可变、可比较的能力快照，并把能力声明、窗口来源和运行期缓存观测分开。
- 复用现有 `ModelSpec` 与预算解析，不要求 provider 网络探测；旧模型目录继续可用。
- 由组合根统一装配，`ChatModelPort`、AgentLoopConfig 和 TUI 共享同一份当前选择事实。
- `/status` 在初始装配和热切换后都能显示完整且诚实的能力诊断。

**Non-Goals:**

- 不新增 `/models` 请求、模型试调用或 provider 能力探测。
- 不在 core 中引入 AI catalog、TUI 或 session 依赖。
- 不修改 Provider 请求协议、工具执行语义、上下文压缩算法或 JSONL 格式。
- 不把“传输了工具定义”当成模型一定支持工具调用；没有目录/适配器确认时保持未知。

## Decisions

1. **能力事实扩展 `ModelSpec`，诊断视图放在 app composition。** 目录字段是模型元数据的来源，使用 `tool_calling: bool | None` 和 `prompt_cache: bool | None` 保持用户覆盖兼容；组合根将其投影成用于 UI 的 `ModelCapabilities`。
2. **能力状态使用三态并集中格式化。** 内部保留 `True/False/None`，TUI 统一渲染为“支持/不支持/未知”，避免各层自行把 `None` 当作 false。
3. **上下文窗口复用预算来源。** 快照引用 `ModelBudgetMetadata.context_window/window_source`，因此 catalog 与 fallback 的来源含义与 `/context` 一致，不复制另一套窗口解析规则。
4. **工具调用默认保持未知。** OpenAI-compatible transport 能传输工具定义，但这不能证明每个具体模型的模型侧能力；只有目录显式声明或未来适配器提供事实时才显示支持/不支持。
5. **缓存能力与缓存观测分栏。** `prompt_cache` 是静态能力声明；`cached_tokens_observed` 来自已有会话 usage，初始为 `None`，收到 usage 后由 TUI/状态模型更新，不改写 `ModelSpec`。
6. **热切换使用组合根解析回调。** `TuiAssembler` 注入一个基于 provider/model/effort 的快照解析器，TUI 不持有 registry，也不访问 config；现有二元 rebuild 回调返回值保持兼容。

## Data Flow

```text
ModelRegistry / ModelSpec + budget metadata
                  │
                  ▼
     resolve_model_capabilities(...)
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
 ChatModelPort / config   FooterInfo / TuiModel
        │                   │
        └──── usage observed┘
                  ▼
              /status
```

## Risks / Trade-offs

- **内置目录字段不完整**：默认会显示未知而不是给出过度自信的支持结论；后续可增补静态目录或适配器事实，不需要改 UI 契约。
- **TUI 与运行时状态短暂不同步**：初始状态来自同一次组合根解析，热切换完成后通过同一 resolver 更新；没有 resolver 的测试/嵌入调用方保留空能力兼容行为。
- **缓存 usage 只在会话中可见**：能力声明不会随着一次 usage 误变成支持，`/status` 同时展示“声明”和“观测”来避免误解。

## Migration Plan

先扩展目录模型和解析测试，再新增能力解析器、运行时注入和 TUI 展示测试；最后更新迭代/架构/测试文档并运行全量质量门禁。没有持久化迁移；回滚只需移除新增字段和展示接线，旧 `models.json` 无需修改。
