## 1. 基线与测试夹具

- [x] 1.1 为 1,000、5,000、10,000 个 block 建立确定性的 transcript fixture，覆盖单行、多行、空 block、工具块和长助手正文。
- [x] 1.2 建立完整渲染 oracle，验证可见窗口、分隔行、瞬态行和退出文档在优化前后保持逐行一致。
- [x] 1.3 为长会话 benchmark 增加可见物化数、索引扫描数、索引更新数、缓存条目/行数、帧耗时、控制事件延迟、丢帧和峰值分配指标。

## 2. 增量布局索引

- [x] 2.1 新增独立的 transcript 布局索引模块，定义 block token、revision、估算高度、精确高度和按宽度快照模型。
- [x] 2.2 实现固定大小 chunk 与前缀查找，支持按内容行定位 block、追加、移除和高度差值更新。
- [x] 2.3 将 `Transcript.append`、`remove`、`clear` 和宽度切换接入布局索引，并保持现有 `layout_index`、`visible_range` 和 `overscan_range` 对外语义。
- [x] 2.4 为 block 注册和解除 revision 失效通知，确保 `touch()` 只标记受影响 block，不通过每帧全量扫描发现变化。
- [x] 2.5 增加索引不变量测试，覆盖空内容、重复 revision、重复移除、clear、chunk 边界和 block 顺序变化。

## 3. 可见区物化与缓存

- [x] 3.1 重构同步布局路径，使用索引定位可见区和 overscan，禁止为普通视口重建全部 entries 与范围起点列表。
- [x] 3.2 实现未物化 block 的稳定高度估算、可见区精确测量和有限次数的视口稳定过程，避免提交空洞或过期范围。
- [x] 3.3 将 RichLine 缓存改为稳定 block token、宽度和 revision 组合键，并增加累计行数或近似字节数边界。
- [x] 3.4 确保 cache eviction、revision 失效和宽度变体淘汰不会破坏当前可见内容或索引高度估算。
- [x] 3.5 增加首次渲染、重复渲染、离屏 block、revision 更新、宽度切换和缓存淘汰测试，确认只有可见区附近 block 被物化。

## 4. 滚动锚点与交互稳定性

- [x] 4.1 为非跟随状态记录 block token 与 block 内行偏移，并将滚轮、PageUp/PageDown 转换为锚点可恢复的视口位置。
- [x] 4.2 在工具展开/折叠、前方 block 高度变化、assistant 增量和 resize 后恢复阅读锚点；锚点删除时选择最近可用位置。
- [x] 4.3 保持跟随底部、新输出计数提示和回到底部清除提示的既有行为，并补充对应回归测试。
- [x] 4.4 验证基于可见区的 `block_at` 点击映射在滚动、resize、分隔行、瞬态行和工具展开后仍然正确。

## 5. 协作式渲染与过期帧

- [x] 5.1 重构 `render_progressive()`，使其以索引查询和可见 block 物化为最小工作单元，不再将全量历史遍历拆成批次。
- [x] 5.2 在索引准备、可见 block 渲染和宽度重排的批次边界检查 generation，并确保过期准备结果不会提交 backend。
- [x] 5.3 保留小会话同步快速路径，验证长会话准备期间输入、Esc、滚动和确认仍能及时进入事件循环。
- [x] 5.4 增加 stale frame、连续 resize、增量更新与渲染取消测试，确认后台任务无泄漏且最新帧最终提交。

## 6. 大工具结果分页

- [x] 6.1 为 `OutputBuffer` 实现基于 metadata 和懒惰页边界的分页访问，避免每次 `current_page`、`page_count` 或诊断渲染都拆分完整正文。
- [x] 6.2 保持 legacy、truncated、artifact、导出和不可恢复状态语义，补充大结果首屏、翻页、边界页和重复访问测试。
- [x] 6.3 验证工具展开只处理当前可见或当前分页内容，且展开、翻页不触发模型调用、工具重执行或会话写入。

## 7. 集成验证与文档

- [x] 7.1 增加 Textual 长会话 `run_test()` 回归，覆盖输入、Esc、PageUp/PageDown、确认、点击展开和滚动期间的输出完整性。
- [x] 7.2 将 benchmark 扩展到 1,000、5,000、10,000 block 及 history、scroll-resize、tool-output、restore 场景，并记录相同环境参数。
- [x] 7.3 更新 TUI 性能基线、CI 性能任务、测试文档、架构文档和 v0.4 V4-21 状态，明确性能报告与阈值策略。
- [x] 7.4 运行相关 unit/contract/integration/e2e/performance 测试、Ruff、`git diff --check`、OpenSpec 校验和构建，确认无会话格式或对外接口回归。
