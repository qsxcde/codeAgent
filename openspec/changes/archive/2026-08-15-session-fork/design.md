## Context

- 现状:JSONL 格式 v1 已预留 `header.parentSession` 与消息 `parentId` 链;`SessionManager.create(parent_session=...)` 已支持(分叉基础 80% 就位);`/undo` 槽位已注册(`available=False`);订阅跟随(switch 重建壳 + 订阅转移)已实现,订阅方对切换无感;`append_message` 只追加不重写(append-only 承诺)。
- 约束:append-only 不破(分叉 = 复制,不是截断);工具层不涉及(无文件回滚);离线可测(store 注入内存/临时目录);事件契约 11 类不变(仅 metadata 增补)。
- 动机与语义对齐见 proposal.md(对照 Pi `createBranchedSession`,2026-08-15 源码实查);行为契约见 specs(sessions / tui delta)。

## Goals / Non-Goals

**Goals:**
- `/fork` 从指定 user 消息分叉新会话,原会话保留、可继续对话、上下文一致。
- 分叉来源对订阅方可感知;TUI 命令反馈清晰。

**Non-Goals:**
- 文件变更回滚(文件保持当前状态,用户自行 git 处理——T-42 定义改写定案)。
- 会话树 UI / 分支导航(v0.3 F-23 剩余)。
- CLI `--fork` 入口(MVP 仅 TUI 命令;headless 会话入口可后续补)。

## Decisions

1. **分叉点语义(照搬 Pi `position=before`)**:`/fork <message-id>` 的分叉点 = 该 user 消息的**前一条消息**(即"从这条用户消息之前重新开始");校验 target 必须是 user 消息,否则拒绝(对齐 Pi:非 user 消息抛 "Invalid entry ID for forking")。缺省参数 = 最近一条 user 消息(`/fork` 无参等价 `/fork <最近 user 消息 id>`)。
2. **store.fork 实现**:新会话文件 = header(`id` = 新 id,`parentSession` = 原 id,`timestamp`/`cwd`/`model`/`effort` 从原 header 复制)+ 分叉点之前(含)全部 `message` entry 原样复制(消息 id 与 parentId 链保持——回放语义、后续 undo/compaction 引用不受影响)。写侧走既有 `_lock_for` 串行化。MemoryStore 同语义(新 dict + 消息切片)。
   - 文件级分叉(复制)而非符号链接/引用:进程内 store 是权威,复制最直接;会话文件独立演进。
3. **SessionManager.fork(session_id, message_id)**:`create(parent_session=session_id)`(复用既有)+ `store.fork` 填入历史 + `switch` 到新会话(订阅跟随既有实现,订阅方无感)——**切换语义与 Pi 的 teardownCurrent + session_start 一致**。
4. **来源标记**:`AgentSession` 构造新增可选 `previous_session_id`;首轮 `SESSION_STARTED` 事件 metadata 增补 `previous_session_id`(仅分叉会话携带;payload 保持既有文本语义——事件契约类型不变,纯 metadata 增补,既有订阅方无感)。
5. **`/fork` 命令**:`commands.py` `/undo` 槽位替换为 `/fork`(`CommandSpec("fork", "从指定消息分叉会话", args=["message-id 缺省最近 user 消息"])`);view 分派 → `manager.fork(current.session_id, msg_id)` → 反馈文案;消息 id 从哪来:会话内 user 消息 id 经 `manager.current.history` 查询(最近一条 user 消息);错误(非 user/不存在)→ 就地提示。
6. **不落盘额外 entry**:分叉本身就是记录(新会话文件 + parentSession);不需要 `undo`/`rollback` entry(就地回滚方案已弃置)。

## Risks / Trade-offs

- [分叉点之后的文件变更"残留"] → 非目标明示:文件保持当前状态,TUI 反馈文案提示;用户可自行 git 处理。
- [分叉历史复制膨胀] → 复制仅分叉点前消息(通常为完整上下文);原会话文件不增长;多个分叉共享同一历史文本,文件级复制是取舍(对称 Pi)。
- [分叉后继续对话的 parentId 链] → 新消息 parent 链到分叉点前最后一条消息(id 不变,链自然延续);回归测试锁定。
- [命令表 /undo → /fork 替换] → 历史记录(commands.py docstring / E10 记录)保留;命令表保持单命令(不做 /undo 槽位)。

## Migration Plan

纯增量,无部署;格式 v1 字段全部复用,旧会话文件无需迁移。实现顺序:store.fork(两后端)→ manager.fork → 来源标记 → TUI 命令接线 → 测试收尾。

## Open Questions

无(方向/粒度/边界均已定案:T-42 定义改写已在 v0.2.md 同步;文件回滚与会话树 UI 明确移出)。
