## 1. store 分叉(两后端)

- [x] 1.1 `session/store.py`:`SessionStore` 协议增 `fork(session_id, target_message_id, new_session_id) -> SessionRef`;`JsonFileStore` 实现——新文件 = header(新 id / parentSession=原 id / timestamp/cwd/model/effort 从原 header 复制)+ 分叉点前(含)全部 message entry 原样复制;写侧走既有路径锁;原文件零修改
- [x] 1.2 `MemoryStore` 同语义实现(新 dict + 消息切片,parentSession 记入 ref)
- [x] 1.3 测试(`tests/session/test_store.py` 增量):消息副本完整性(id/parentId 链不变)、header parentSession、原文件行数不变(append-only)、分叉点校验(非 user 消息/不存在 → 明确错误)、两后端一致

## 2. SessionManager 分叉与切换

- [x] 2.1 `session/manager.py` 增 `fork(session_id, message_id) -> AgentSession`:校验分叉点 user 消息(经 store.load_messages)→ `create(parent_session=session_id)` + `store.fork` 填历史 + `switch`(订阅跟随既有,订阅方无感);缺省分叉点 = 最近一条 user 消息
- [x] 2.2 测试(`tests/session/test_session_manager.py` 增量):fork 后 current 切换、订阅跟随、原会话可切回且历史完整、分叉点非法报错

## 3. 会话来源标记

- [x] 3.1 `session/session.py`:`AgentSession` 构造增可选 `previous_session_id`;首轮 `SESSION_STARTED` 事件 metadata 增补 `previous_session_id`(仅分叉会话携带,payload 语义不变)
- [x] 3.2 测试(`tests/session/test_session.py` 增量):分叉会话首轮事件 metadata 携带父会话 id;普通会话无该字段

## 4. TUI `/fork` 命令接线

- [x] 4.1 `app/tui/commands.py`:`/undo` 槽位替换为 `/fork`(参数 message-id,缺省最近 user 消息);帮助文本同步
- [x] 4.2 `app/tui/view.py`:`/fork` 分派 → `manager.fork(current.session_id, msg_id)`;反馈文案(新会话 id / 分叉点 / 原会话保留 + 文件不动提示);非法分叉点就地提示
- [x] 4.3 测试(`tests/tui/test_commands.py` / `test_view.py` 增量):/fork 解析、分派、反馈、错误路径、/undo 不再注册

## 5. 收尾

- [x] 5.1 全量离线测试全绿;`openspec validate --change session-fork` 通过
- [x] 5.2 文档同步:v0.2.md T-42 状态与 E 记录
