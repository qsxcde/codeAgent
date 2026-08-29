## Why

v4-18 的目标是让 TUI 在模型持续输出、工具执行和长 Markdown 回复期间仍然可输入、可取消和可滚动。当前虽有帧调度、增量合并和布局缓存，但事件分发、Markdown 布局和 Textual 更新仍在同一事件循环中同步执行，缺少真实交互链路的延迟与输入完整性验证。

## What Changes

- 将流式增量缓冲改为有界、低复制成本的累积方式，保持文本完整性和结构事件顺序。
- 为活动中的助手回复增加真正的增量 Markdown/换行处理，避免每个增量重新解析完整正文。
- 将渲染工作控制在可交互预算内，保证输入、Esc 取消、滚动和确认操作不会被长帧长期阻塞。
- 保留 v4-17 的提交即时回显语义，并使准备态首帧不会触发无界的历史或 Markdown 重算。
- 增加基于真实 Textual 事件循环的流式交互回归测试，以及可重复的输入延迟、取消延迟和帧合并观测。
- 不改变 core、session、provider 和工具协议；长历史索引的完整优化仍由 V4-21 负责，统一性能报告仍由 V4-22 负责。

## Capabilities

### New Capabilities

<!-- None: this change tightens the existing TUI contract. -->

### Modified Capabilities

- `tui`: 强化流式渲染性能要求，明确高频增量、长 Markdown、工具结果和控制输入之间的非阻塞与顺序保证。

## Impact

- 主要影响 `src/codeagent/app/tui/rendering/`、`src/codeagent/app/tui/presentation/blocks/`、必要的 TUI 状态/布局代码和 Textual 适配测试。
- 扩展 `tests/tui/` 的事件循环回归覆盖及 TUI 性能夹具，可能增加开发期诊断指标，但不引入新的运行时依赖。
- 需要同步 `openspec/specs/tui/spec.md` 的 delta；不改变已有公共 core/session API 和持久化格式。
