## Why

当前 TUI 已经只物化可见 block，并具备布局缓存与协作式渲染，但每次布局准备仍会遍历全部历史、重建完整的范围索引。会话达到数千条消息后，滚动、resize、工具展开和新帧准备的工作量会随历史线性增长，用户可能感到输入延迟、视图跳动或展开结果卡顿。V4-21 的目标是把现有“有限物化”收敛为真正可长期使用的长会话视口，同时保留现有视觉和事件语义。

## What Changes

- 为 transcript 引入可增量维护的布局索引，以 block 高度和前缀行数支持可见范围定位，避免每帧重建全部 `entries`、`layout_index` 和范围起点。
- 将历史内容的布局准备限制在可见区和有限 overscan；未物化 block 使用可替换的高度估计，进入视口后再精确测量并局部更新索引。
- 为 append、remove、revision 更新、工具展开/折叠和终端 resize 定义局部缓存失效与布局更新语义。
- 增加滚动锚点，使用户离开底部后，前方 block 高度变化或 resize 不会无故改变当前阅读位置；跟随底部时继续保持新内容自动可见。
- 保留并扩展现有协作式渲染和 generation 丢弃机制，使索引准备、可见 block 物化和宽度重排都能让出事件循环，并避免过期帧提交。
- 将工具结果分页的行访问改为有界或可复用的分页布局，避免展开大结果时每次重新拆分完整输出。
- 增加长会话的离线 benchmark、Textual 交互回归和布局等价性测试，覆盖滚动、resize、点击映射、工具展开、输入、取消和确认。
- 不改变 JSONL、会话消息、模型上下文、工具执行和退出完整文档语义；`all_lines`/退出路径仍须按顺序输出完整内容。

## Capabilities

### New Capabilities

<!-- No standalone user-facing capability is introduced. -->

### Modified Capabilities

- `tui`: 强化大型历史的按需渲染、视口定位、滚动稳定性和长会话下的输入/控制事件响应要求。

## Impact

- 主要影响 `src/codeagent/app/tui/state/transcript*.py`、TUI 渲染协调器、表现层工具结果分页和 TUI 性能基准。
- 需要新增或调整 TUI 单元、Textual 集成和 performance marker 测试，并更新长会话性能基线及相关文档。
- 不新增第三方依赖，不改变对外 Python API、会话持久化格式或工具结果协议；现有 `Transcript`、`Component.revision`、`TuiBackend` 和退出完整文档接口保持兼容。
