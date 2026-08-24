## Context

现有 TUI 由 TuiApp、TuiModel、Transcript 和 TextualBackend 组成，AgentSession 通过同步 EventBus 分发模型、工具和会话事件。TuiModel 目前用 running/activity_visible 和工具块状态驱动显示；Transcript 每次渲染都会重新计算所有块；工具层已经按字节/行数限制结果，但 TUI 没有结果元数据和分页模型。现有端口和离线组件测试需要继续保留，不能让组件依赖 Textual 或模型实现。

## Goals / Non-Goals

**Goals:**

- 用结构化运行快照表达阶段、耗时、当前操作、错误和可重试性。
- 在不改变模型消息和工具安全语义的前提下，让状态栏和 /status 提供可靠的运行诊断。
- 将流式渲染改为可节流、可缓存、可视区优先，并保持滚动跟随语义。
- 为工具输出提供受限预览、分页、截断元数据和可选导出。
- 大型会话恢复、压缩和退出文档不再因单次全量构造而冻结界面。

**Non-Goals:**

- 首版不保证所有工具都能实时推送 stdout；没有进度协议的同步工具只显示阶段和耗时。
- 不引入新的终端渲染引擎，不把 TuiModel 与 Textual API 耦合。
- 不改变会话 JSONL 消息格式、工具权限策略或已有斜杠命令的含义。
- 不自动重试已经可能产生副作用的工具调用。

## Decisions

### 1. 采用结构化生命周期事件和 TUI 运行快照

在 core.events 中增加模型请求开始、工具开始/进度、压缩开始/结束和重试开始等可选事件；现有事件继续保留。AgentSession 为每轮事件附带 session_id 和 run_id，工具事件附带 tool_call_id、operation_id、阶段和耗时。TuiModel 将这些事件归约为 RuntimeSnapshot：

    phase, phase_started_at, run_id, session_id
    current_operation, elapsed_ms
    tool_counts, pending_confirmation
    retryable, error_code, cleanup_uncertain
    context_tokens, context_window, context_stale

选择结构化事件而不是在 TUI 中解析人类可读文本，原因是错误、超时和清理不确定性必须可测试且不能受文案变化影响。缺少新事件的旧会话仍按现有事件推断阶段，保持兼容。

### 2. 将状态栏视为运行快照的摘要视图

StatusBar 接收 RuntimeSnapshot，左侧按优先级显示阶段图标、阶段名称、耗时和当前操作，右侧保留上下文占用；模型、思考强度和工作目录按 cell 宽度截断。上下文 token 没有 provider usage 时显示未知/估算标记，切换模型时由组合根同步新的 context_window。

详细信息只在 /status 展示，包括事件时间、工具计数、最近错误、重试条件、渲染统计和输出统计，避免单行 footer 变成多行日志。

### 3. 使用帧调度器和块级渲染缓存

TuiApp 保留事件驱动模型，但将 _schedule_render 改为两级调度：首次状态变化立即安排一次渲染；短时间内连续增量合并到下一帧，目标间隔约 16～33ms。活动动画和状态耗时刷新使用低频定时器，不触发模型或工具请求。

每个 Component 维护内容 revision，Transcript 按 width/revision 缓存 RichLine 和行高。布局索引只更新发生变化的块，视口渲染通过行高索引定位可见块并附带有限 overscan。终端宽度变化只使缓存失效一次，连续 resize 事件经 debounce 合并。

选择缓存和可视区索引而不是直接换用 Textual RichLog，是为了保留当前纯组件渲染、点击工具块和离线断言能力。TextualBackend 仍可整体更新当前视口，但不再接收完整历史文本。

### 4. 将工具结果与显示预览分离

ToolResult/工具事件增加非持久化输出元数据：total_bytes、total_lines、shown_lines、truncated_by 和可选 artifact_path。TuiModel 将结果包装为 OutputBuffer，默认保存摘要、首部和尾部预览；分页只改变当前显示窗口，不修改 Message.content。

如果工具在进入 core 前已经丢弃了超出上限的原始内容，TUI 必须明确显示无法恢复；需要完整结果时由工具或组合根在截断前写入临时附件，并由生命周期清理器负责删除。该设计避免把敏感命令输出无限期留在内存或会话 JSONL 中。

工具块的 PageUp/PageDown 只在输出预览获得焦点时切换页，否则仍滚动 transcript；导出操作通过后端端口返回文件路径，不触发模型调用。

### 5. 恢复、压缩和重试使用显式忙碌阶段

会话切换先发布 restoring，再加载快照和构建显示块；磁盘读取可放到 asyncio.to_thread，组件状态更新回到事件循环。恢复期间禁止普通提交，完成后一次性替换 transcript 并同步上下文状态。压缩任务发布 compacting，成功/失败都发布终态。

失败状态保存 retryable、side_effect_state 和原始错误分类。/retry 只允许模型请求或工具尚未执行的失败；工具已执行或 cleanup_uncertain 时，界面要求确认或引导用户继续输入，不自动复制上一轮调用。

### 6. 退出文档使用迭代输出

TuiBackend.exit_document 接受 Iterable[str] 或等价的分块生产器。TuiApp 仍按逻辑顺序生成完整 transcript，TextualBackend 在退出 alt 屏后逐块写入主屏。这样保留完整文档契约，同时避免先创建一个包含全部行的巨大 list。

## Risks / Trade-offs

- [新事件和 RuntimeSnapshot 增加跨层接口] → 新事件字段全部可选，旧事件仍可推断阶段；为每种阶段补充离线归约测试。
- [变量宽度与 Markdown 换行使行高缓存失效复杂] → 缓存键包含宽度和 revision；resize 统一失效，不尝试复用旧宽度行。
- [输出附件可能包含密钥或隐私数据] → 默认不落附件；只有用户显式导出或工具声明可保存时才创建，并使用临时目录和生命周期清理。
- [工具没有实时进度] → 首版显示 queued/running 和耗时；实时 stdout 作为可选 ToolProgress 能力，不伪造百分比。
- [重试可能重复副作用] → 事件携带 side_effect_state 和 cleanup_uncertain；只有安全类别允许直接重试，其余必须确认。
- [后台恢复线程与会话切换竞态] → run_id/session_id 校验旧事件；切换时取消旧任务并丢弃过期快照。

## Migration Plan

1. 先增加事件字段、RuntimeSnapshot 和状态归约，旧 UI 行为作为缺省回退。
2. 更新 StatusBar、/status 和模型切换时的 context_window 同步。
3. 加入帧调度、组件 revision、布局索引、可视区渲染和 resize debounce。
4. 接入 OutputBuffer、工具结果元数据、预览分页和导出端口。
5. 接入 restoring/compacting 阶段、安全重试与退出分块输出。
6. 运行全量测试、离线性能基准和人工验收；若缓存实现出现问题，可先关闭可视区优化而保留状态和分页能力。
