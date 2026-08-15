## Why

T-42 定义改写(2026-08-15 探索定案):原「回滚 /undo」(就地截断 + 文件变更回滚)改为对标 Pi(earendil-works/pi)的 **`/fork` 分叉语义**——JSONL 树形 append-only 格式下,分叉比截断更契合格式哲学:原会话永不修改、会话树自然形成(header `parentSession` 与消息 `parentId` 链已在格式 v1 预留);文件回滚不做(文件保持当前状态,用户自行 git 处理),行业对标 F-23「分支会话 fork」提前落地。

## What Changes

- **store.fork(session_id, target_message_id, new_session_id)**:基于既有会话分叉新会话——新文件 = header(`parentSession` = 原会话 id)+ 分叉点之前(含)全部消息副本(消息 id / parentId 链保持,回放语义不变);原会话文件零修改(append-only 承诺不破)。
- **SessionManager.fork(session_id, message_id)**:创建分叉会话并切换当前会话(订阅跟随既有实现,订阅方无感);校验分叉点必须是 user 消息(对齐 Pi `position=before` 语义:分叉点 = 该消息之前)。
- **`/fork` 命令接线**:`app/tui/commands.py` 用 `/fork` 替换 `/undo` 槽位(命令表保持干净);`view.py` 分派并反馈「已分叉会话 <id>:从消息 <id> 之前重新开始(原会话保留,文件保持当前状态)」。
- **会话来源标记**:新会话首轮 `SESSION_STARTED` 事件 metadata 携带 `previous_session_id`(对齐 Pi `session_start(reason=fork, previousSessionFile)`);订阅方(TUI 反馈/测试断言)可感知分叉来源。
- 无 **BREAKING**:格式 v1 字段全部复用,事件契约 11 类不变(仅 metadata 增补)。

## Capabilities

### New Capabilities

无(均为既有能力的扩展)。

### Modified Capabilities

- `sessions`:新增「会话分叉」requirement(store 级分叉、原会话保留、分叉后可继续且上下文一致、来源标记)。
- `tui`:「斜杠命令体系」requirement 扩展(`/fork` 命令,`/undo` 槽位移除)。

## Impact

- `session/store.py`:新增 `fork()`(SessionStore 协议 + JsonFileStore / MemoryStore 两后端实现);
- `session/manager.py`:新增 `fork(session_id, message_id)`(内部复用 create(parent_session)+ switch,订阅跟随既有);
- `session/session.py`:首轮 SESSION_STARTED 事件 metadata 增补 `previous_session_id`(会话构造时注入,来源=分叉父会话);
- `app/tui/commands.py`:`/undo` 槽位替换为 `/fork`(参数:消息 id,缺省最近一条 user 消息);
- `app/tui/view.py`:`/fork` 命令分派 + 反馈文案;
- `tests/`:`test_store`(两后端 fork 断言:消息副本 / parentSession / 原文件不动)、`test_session_manager`(fork 切换与订阅跟随)、`test_view`(/fork 分派)、`test_cli`(可选 `--fork` 入口,MVP 不做)。

无 **BREAKING** 变更。
