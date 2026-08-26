## Why

当前 TUI 已具备功能测试，但没有可重复的性能基线，无法量化长会话、长流式回复和连续 resize 下的渲染成本，也无法证明后续优化确实改善体验。现在需要先建立离线、可比较的观测和基准体系。

## What Changes

- 为 TUI 纯渲染路径增加统一的耗时、事件、缓存与内存观测边界。
- 提供使用 FakeClient、临时会话数据和纯组件的离线 benchmark fixture，覆盖长历史、长流式正文、大工具输出和连续 resize。
- 定义机器可读的 benchmark 结果格式与运行命令，记录运行环境和参数以支持前后比较。
- 增加性能回归测试，保护事件顺序、滚动、点击映射和 Markdown 渲染语义。
- 更新 v0.4 迭代记录，使已完成的观测与待优化项保持一致。

## Capabilities

### New Capabilities

无。该变更只增加开发期观测、基准和测试，不改变用户可见的 TUI 行为。

### Modified Capabilities

无。

## Impact

- `src/codeagent/app/tui/` 的渲染统计与测试注入点。
- `tests/tui/` 的离线 fixture、基准和回归断言。
- `docs/iteration/v0.4.md` 与项目开发命令文档。
- 不引入联网依赖、常驻服务或生产期遥测。
