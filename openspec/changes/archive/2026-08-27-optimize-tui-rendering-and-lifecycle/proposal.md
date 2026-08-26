## Why

当前 TUI 对长会话的每次刷新仍会遍历全部历史 block，流式正文会重复解析累计 Markdown，布局缓存也会保留过期 revision 和宽度结果。退出、热切换和忙碌输入路径缺少明确的资源收尾与反馈，影响长时间运行时的响应性和可靠性。

## What Changes

- 为 Transcript 布局缓存建立有界、可失效的生命周期，避免流式 revision 和 resize 产生无限旧项。
- 在展示层合并相邻流式 delta，并仅更新变化 block 与可视范围附近布局，保持事件顺序和可见语义。
- 优化流式 Markdown 的渲染策略，复用稳定内容并在终态保证完整 Markdown 结果。
- 以历史内容成本而非单一消息数判断后台恢复，避免大内容会话切换阻塞输入。
- 为退出、任务取消、端口热切换和 runtime 关闭建立可等待、幂等的收尾流程，并释放已关闭 runtime 的注册引用。
- 对运行中提交输入提供明确且不丢失草稿的反馈。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `tui`: 强化流式渲染的有界成本、忙碌输入反馈、会话恢复与退出资源收尾契约。

## Impact

- `src/codeagent/app/tui/` 的 Transcript、消息块、渲染协调和会话恢复逻辑。
- `src/codeagent/app/composition/runtime_factory.py` 与 TUI 运行时关闭装配。
- `tests/tui/`、运行时生命周期测试和性能基准。
- 不改变会话 append-only 语义、工具确认语义、TUI 视觉语义或 Textual 作为具体引擎的边界。
