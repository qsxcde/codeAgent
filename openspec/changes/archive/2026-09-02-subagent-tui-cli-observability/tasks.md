## 1. 展示契约与事件输入

- [x] 1.1 为 Subagent 父级事件补充有界的 profile、单行 task label 和必要的展示元数据，并保持现有父子关联字段、普通工具事件和无 runner 行为兼容
- [x] 1.2 增加事件投影边界测试，覆盖缺少归属、错误 parent run、child 身份不覆盖父级、长标签/诊断截断和不携带完整 prompt/context

## 2. TUI 委派块

- [x] 2.1 先编写 `SubagentBlock` 生命周期、状态标签、样式标签、折叠/展开和有限详情的离线测试
- [x] 2.2 实现独立的 TUI 委派块与生命周期投影，按固定字符/行数上限保存 task label、阶段、摘要、reason code、清理状态和结果统计
- [x] 2.3 为委派块接入 transcript 的触摸监听、点击展开和局部布局缓存失效，不复制子 Agent transcript 或无界工具输出

## 3. TUI 状态与父子隔离

- [x] 3.1 先补充 TuiModel 事件回归测试，覆盖 queued/started/progress/finished、多个 delegation_id、乱序、重复终态、迟到事件、父级取消和 child run/session 不改变父 runtime
- [x] 3.2 实现有界的委派投影集合和序列/终态幂等规则；专用事件只接受匹配当前 parent run 的事件，并更新对应委派块而不进入普通 assistant/tool/error 正文
- [x] 3.3 将委派状态聚合接入 StatusBar，覆盖固定槽位、窄终端截断、运行/等待确认/失败计数和无活动委派回收

## 4. TUI 事件桥接与性能

- [x] 4.1 为 TUI 应用事件桥接补充专用事件刷新、活动计时器、点击和父级取消的回归测试
- [x] 4.2 接入模型与应用层事件桥接，保证 Subagent 事件不会被普通 runtime reducer 丢弃，也不会停止仍在等待父级工具结果的活动提示
- [x] 4.3 增加长会话/高频进度性能 fixture，验证只更新一个委派投影、缓存和诊断保持有界，帧调度、输入、滚动、resize 和取消不发生完整历史重渲染

## 5. Headless 状态输出

- [x] 5.1 先编写 headless 一次性与交互循环的输出测试，覆盖稳定前缀、状态变化去重、终态 reason code、父回复顺序、多个委派隔离和敏感/无界 payload 过滤
- [x] 5.2 实现无终端依赖的 Subagent 状态行投影与有界格式化，并接入 `_headless_once`、`_headless_loop` 的事件消费路径
- [x] 5.3 验证普通单 Agent headless 输出、用量行、任务验证输出和错误退出码不发生无关变化

## 6. 文档、规格与质量门禁

- [x] 6.1 更新 TUI/CLI 使用或架构文档及 `docs/iteration/v0.5.md`，记录 V5-07 完成范围、展示限制和非目标
- [x] 6.2 运行相关 unit/contract/integration/e2e/TUI 性能测试、Ruff、规模扫描、`git diff --check`、OpenSpec strict validation 和 `uv build`
- [x] 6.3 检查差异、敏感文件和兼容性；完成后同步主规格并准备归档摘要
