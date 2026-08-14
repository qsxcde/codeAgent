## Why

当前 TUI 的消息、工具调用和思维链以原始文本为主：用户消息缺少稳定的块级层次，工具调用只提供通用摘要，推理原文会在等待期间占据聊天区。参照 Codex 的终端交互样式，需要让对话历史更易扫描，并在模型或工具仍在工作时提供克制、持续的活动反馈。

## What Changes

- 将用户消息改为全宽深灰背景块，使用低对比 `›` 提示符，并为连续顶层消息块提供稳定间距。
- 将助手正文改为以 `•` 起始的消息格式；默认不显示模型推理原文。
- 新增低频动画的“思考中”活动提示，在等待模型或工具后的后续回复时可见，并在正文、错误、取消或回合结束时停止。
- 将工具调用改为 Codex 风格的人类可读摘要；对 edit/write 之类的变更工具提供可展开的红绿差异视图。
- 为工具结果保留并传播 tool call ID，按 ID 归属并发工具结果，替代现有 FIFO 匹配。
- 更新 TUI 规格、设计文档和测试，以反映新的消息格式、活动反馈和工具详情行为。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `tui`: 修改用户/助手消息格式、默认思维展示、工具调用摘要与详情、活动反馈以及消息区样式契约。

## Impact

- `src/codeagent/app/tui/components.py`: 消息、活动和工具差异组件，以及 transcript 间距与行映射。
- `src/codeagent/app/tui/theme.py`: 新增消息背景、差异和活动提示的受控样式标签。
- `src/codeagent/app/tui/view.py` 与 `src/codeagent/app/tui/backend.py`: 活动动画的事件驱动调度接口。
- `src/codeagent/app/tui/textual_backend.py`: 在 Textual 生命周期内刷新活动提示。
- `src/codeagent/session/session.py` 与 `src/codeagent/core/events.py`: 工具结果携带 tool call ID 元数据。
- `tests/tui/`、`tests/session/` 与 `openspec/specs/tui/spec.md`: 覆盖并发归属、差异渲染、活动提示和更新后的视觉契约。
