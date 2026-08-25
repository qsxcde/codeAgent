## Context

See `proposal.md` for the motivation and user-visible scope. 当前 `TuiApp._run_conversation()` 和 CLI 响应路径直接调用 `AgentSession.run()`；`src/codeagent/core/loop.py` 只负责通用 ReAct 循环，工具事件已经可以被订阅，但 bash 的退出码主要存在于格式化文本中。代码任务监督、工作区变更判定和验证命令选择不应下沉到 core，也不能依赖解析输出文本。

## Goals / Non-Goals

**Goals:**

- 让模式成为可测试的权限边界，并兼容现有单轮对话入口。
- 以工作区实际变更作为验证硬门槛，覆盖 Agent 工具和命令脚本造成的变更。
- 为验证和修复提供结构化事件、取消传播、有限重试和可靠终态。
- 让 CLI 与 TUI 使用同一任务结果和阶段事件。

**Non-Goals:**

- 不重写 `core/loop.py` 的 ReAct 或模型传输协议。
- 不在本变更中实现完整意图分类器；`auto` 只做权限安全和变更检测，不根据模型猜测强制进入测试。
- 不持久化完整验证日志、修复轨迹或跨会话任务状态。
- 不引入新的测试框架或要求联网探测项目依赖。

## Decisions

### 1. 在应用层增加 TaskSupervisor

新增应用层任务监督器，接收模式、用户输入、`AgentSession` 和工作区配置，输出 `TaskEvent` 流及 `TaskResult`。其生命周期为：

```text
resolve mode → baseline → agent run
                              ├─ no diff → no_changes / ordinary response
                              └─ diff → verify → (repair → verify)* → terminal result
```

监督器维护 `TaskPhase`（planning、editing、verifying、repairing）和 `TaskStatus`（verified、unverified、failed、cancelled、no_changes），并订阅 `TURN_END`、`ERROR`、`RUN_CANCELLED` 等现有事件。`AgentSession.run()` 返回本身不被当作任务成功信号。

备选方案是把状态机塞入 core loop；该方案会让通用编排层依赖工作区、测试命令和 UI 策略，违反当前依赖方向，因此不采用。

### 2. 模式采用显式命令 + 安全的 auto

`ModeResolver` 解析 `/ask`、`/plan`、`/code`、`/mode`。每个会话保存当前粘性模式，单次前缀只覆盖当前消息。`ask` 与 `plan` 使用只读工具配置；`code` 复用现有确认策略；`auto` 默认允许只读探索，并在检测到变更后把后续阶段交给监督器。

意图提示只用于 UI 和提示词，不作为执行权限依据。真正的写入拒绝在工具调用边界执行，避免模型把“看起来像修改请求”的普通问题误判为代码任务。

### 3. 工作区变更采用双重证据

`WorkspaceInspector` 在任务开始记录：Git porcelain、未跟踪文件、已修改文件和必要的 diff 摘要；任务结束再次采集并计算集合差异。若当前目录不是 Git 仓库，则使用受控目录快照（路径、大小、mtime 和哈希）作为后备。写入/编辑工具事件只作为快速提示，不能覆盖最终快照结论。

基线和最终采集都必须排除会话存储、临时验证产物和明确配置的忽略路径，避免验证自身产生的文件触发下一轮验证。

### 4. 验证命令分层选择并隔离执行

`VerificationCommandResolver` 按以下优先级返回命令和来源：

1. 本次请求显式命令；
2. 项目配置中的验证命令；
3. 本地文件探测（Python/Node/Rust/Go/.NET/Java/Make 的常见测试入口）。

命令通过现有 bash 安全策略执行，不执行联网安装或隐式修改依赖。`VerificationRunner` 将工具结果转换为 `VerificationResult`，携带命令、来源、退出码、状态、耗时、截断标记和有界输出尾部；超时与取消复用 bash 的进程树清理路径。

### 5. 结构化 bash 结果向上游传播

扩展 `BashInvocationResult` 和通用 `ToolResult` 的 metadata，使 `exit_code`、`execution_status`、`duration_ms`、`output_truncated` 和 `cleanup_uncertain` 可被事件消费者读取。正常非零退出码返回失败状态；grep 无匹配等已定义豁免必须以结构化字段标注。格式化文本仅用于展示，监督器不解析中文或其它人类可读内容。

### 6. 修复回合使用有界诊断和重复指纹

验证失败时构造只读诊断对象（命令、退出码、变更路径、diff 统计、错误尾部），作为修复回合的上下文数据。每次修复后重新采集差异，再执行验证。默认允许一次修复，配置上限不得超过三次；以命令、退出码、规范化错误尾部和差异摘要计算失败指纹，重复指纹立即终止，防止无限循环。

### 7. CLI/TUI 共享事件，分别渲染

CLI 将任务事件映射为简洁阶段行和最终摘要；TUI 将其放入已有状态栏和可展开任务详情。任务进行验证/修复时设置独立的 `task_active` 锁，避免仅依赖单轮 `running` 标志；Esc 调用监督器取消令牌，向 Agent、工具和验证子进程传播。技能正文、原始命令大输出和完整 diff 默认不进入聊天区。

## Risks / Trade-offs

- [风险] 外部进程可能在基线采集之外修改文件，导致变更归因不精确 → 显示变更集合和来源为“工作区快照”，并允许配置忽略路径；不把归因当作安全边界。
- [风险] 自动探测命令不适合所有项目 → 支持显式命令和项目配置；探测不到时返回 `unverified`，绝不虚报成功。
- [风险] 验证命令输出过大或泄露敏感内容 → 沿用 bash 的字节/行上限和脱敏策略，只把尾部摘要传给修复回合。
- [风险] 兼容旧事件消费者时 metadata 缺失 → 保留现有文本内容和状态字段，新增 metadata 为可选字段；监督器对缺失退出码返回 `unverified`。
- [取舍] 只在真实 diff 后验证会放过“修改后又完全还原”的回合 → 该结果等价于最终工作区无变更，避免无意义测试；如未来需要过程审计，再增加独立任务日志能力。

## Migration Plan

1. 先增加结构化工具 metadata、模式模型和监督器的单元测试，再接入 CLI。
2. 接入 TUI 的模式命令、任务锁和状态栏；默认保持 `auto`，现有普通问答界面不改变。
3. 逐步启用项目命令探测，并在文档中说明显式验证命令和修复上限配置。
4. 回滚时移除 CLI/TUI 对监督器的调用即可恢复直接 `AgentSession.run()`；新增 metadata 字段向后兼容，不要求数据迁移。

## Open Questions

无。验证命令配置格式、默认超时和修复次数属于实现时可调整的默认值，不改变本变更的行为契约。
