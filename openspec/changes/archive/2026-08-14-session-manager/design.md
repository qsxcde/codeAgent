## Context

阶段 1(self-built-orchestration,已归档)已落地:JSONL 树形 `SessionStore`(header / message / compaction entry,append-only,版本校验)、`AgentSession` 事件壳(恢复 = 构造时 `load_messages` 重放;steer / followup / abort 已随自研循环完成)。阶段 2 剩余:会话元数据与列表、生命周期管理、CLI 会话入口。详见 proposal.md - Why。

设计参照 **Pi Agent**(earendil-works/pi)官方文档(sessions / session-format / compaction,2024-12 快照):其 SessionManager 是"单会话文件操作门面",跨会话能力(列表/选择/切换)全在 CLI 层,TUI 始终单活会话。本设计的薄管理器路线与其一致。对齐点:meta 可变元数据 ↔ Pi `session_info` entry;标题派生 ↔ Pi `/name` + 首消息回退;CLI `-c` ↔ Pi `pi -c`;`firstKeptEntryId` 指针压缩 ↔ 已记录给 T-37(session-compaction change)。

## Goals / Non-Goals

**Goals:**

- 会话可列出(含标题/model/effort)、可恢复、可切换、可释放、可继续最近;
- 订阅方(TUI/CLI)对切换无感,10 类 AgentEvent 契约零改动;
- 格式演进向后兼容(旧会话文件可读,版本号保持 v1);
- 清理 `AgentPorts.store` 死字段,恢复分层纯净。

**Non-Goals:**

- 并行会话同时运行(事件转发总线)——列为未来演进;
- compaction 触发与 Summarizer(T-37,session-compaction change;details 结构已定为 Pi 式 `{readFiles, modifiedFiles}` 纯路径数组 + 跨压缩累积);
- `model_change` entry 与 per-message model 记录(T-44 做 `/model` `/provider` 时追加;本 change header 仅存初始值);
- TUI 斜杠命令(T-44 接管)、`/undo` 跨压缩点决策(T-42);
- 会话删除/归档(仅 dispose 活动引用,文件保留)。

## Decisions

### D1 薄 SessionManager:单活 + 订阅跟随 current

`session/manager.py` 持有共享 ports(模型端口/工具无状态,装配一次)+ store;`current` 为唯一活动会话。

- `create(parent_session=None)` → 新 `AgentSession`(新 id + `store.create` + header 记 model/effort)成为 current;
- `switch(session_id)` → 若 current 在运行则 abort,重建壳(`AgentSession` 构造即恢复消息),**把已注册订阅转移到新会话的 bus**;
- `dispose(session_id)` → abort + 从活动集合移除(文件保留);
- `list()` → `store.list()`(SessionRef 含派生标题);
- `continue_recent(cwd)` → `list()` 取最新(对齐 Pi `SessionManager.continueRecent`);
- `subscribe(fn)` → 注册到 current 的 bus,switch 时自动转移(订阅方无感)。

**替代方案(放弃)**:全局事件总线 + 转发时 metadata 打 `session_id`。理由:Pi 对照——单活会话下无并行事件交错问题,转发总线是 YAGNI;未来真做并行会话时再升级,且 `AgentEvent.metadata` 已预留扩展位,契约不变。DoD 4"订阅方对切换无感"由订阅转移满足。

### D2 meta entry:可变元数据(对齐 Pi `session_info`)

append-only 下可变元数据不能回写 header(它是第一个 entry)。新增 entry 类型:

```json
{"type":"meta","key":"name","value":"重构 auth 模块","timestamp":"..."}
```

- 读侧聚合:每个 key 取最近一次写入(后写覆盖先写);
- 格式 v1 兼容:现有读侧(load_messages 只挑 message、get 只挑 session)天然忽略未知 type,版本号不动;
- 对齐 Pi `session_info` entry(语义等价:后写覆盖取最新)。

**替代方案(放弃)**:title 纯派生(每次现算首条用户消息)——零格式改动但不可显式命名;Pi 的 `/name` 证明显式命名是刚需。

### D3 标题派生:显式命名优先,否则首条用户消息截断

- `SessionRef.title` 填充规则:`meta:name` 存在 → 用之;否则流式读文件至首条 `role=user` 消息,取前 20 字符(省略号结尾);
- `list()` 用流式逐行读取,遇首条 user 消息提前终止(不整读文件,列表大时可控);
- 显式命名 API(`set_meta(session_id, "name", ...)`)本 change 落地,命令层(`/name`)归 T-44。

### D4 header 扩展 model / effort

- `store.create(..., model=None, effort=None)` → header 增加可选字段;`SessionRef` 增加 `model` / `effort`;
- 组合根传入解析后的 model_id / effort(创建时即知);
- 旧文件缺字段 → 读侧 `.get` 默认空,向后兼容;
- 恢复会话用 header 记录值(简化);Pi 式 per-message model + `model_change` entry 留给 T-44(切换模型时追加,沿路径取最新)。

### D5 CLI 入口

- `-c` / `--continue`:继续最近会话(对齐 Pi `pi -c`);
- `--session <id>`:恢复指定会话;
- `--list-sessions`:纯文本表格(标识/标题/时间/模型);
- 默认(无参数)保持新建会话(headless 既有行为);
- store 目录:`~/.codeagent/sessions/`(与配置目录一致,`app/config.py` 的 `CONFIG_DIR` 派生);
- TUI 斜杠命令不在此实现(T-44)。

### D6 `AgentPorts.store` 死字段移除

core 循环从不落盘(store 只被 `AgentSession` 消费),`AgentPorts.store` 是死字段且制造"core 认识 store"的假象。移除:删除 dataclass 字段与 `create_agent_ports` 的 `store` 参数;`AgentSession` 仍经构造参数注入 store(不变)。分层规则顺带更纯净:core 的 ports 只剩 model + tools。

### D7 存储组织与版本策略

- 保持平铺 `~/.codeagent/sessions/<session_id>.jsonl`(v0.2 列表量级为个人使用);Pi 式按 cwd 分目录(`--<path>--/<ts>_<uuid>.jsonl`)留 v0.3(fork 场景);
- 新字段/新 entry 类型均为可选 → 版本号保持 v1;
- 未来破坏性演进:学 Pi 的"加载时自动迁移"(v1→v2→v3),届时 bump 版本 + 迁移逻辑。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| 单活限制:并行会话不可用 | 订阅跟随 current 已覆盖 DoD 4;并行 = 升级转发总线(metadata 打 session_id),契约不变 |
| 标题派生读文件开销(list 大时) | 流式读取 + 首条 user 消息提前终止;显式命名后免派生 |
| 旧会话文件无 model/effort | 读侧 `.get` 默认空,向后兼容(有回归测试锁定) |
| meta 与消息树无关,回放不参与上下文 | 语义定位为"文件级元数据",spec 场景已限定(显示名等) |
| 多进程同时写同一会话文件 | 进程内锁 + 单活语义;CLI 单进程场景(多进程并发留 v0.3) |
| 恢复会话时模型配置不匹配 header | 用 header 记录值(简化);T-44 model_change 后按路径最新值 |

## Migration Plan

- 旧会话文件:无需迁移——header 新字段可选,meta 是新增 type,读侧忽略未知;
- `AgentPorts` 签名变化:组合根与测试同步修改(仓库内唯一调用方);
- CLI 新增参数为纯增量,默认行为不变。

## Open Questions

无(探索期三个开放问题已拍板:title 方案 B(meta entry)、单 run 语义、compaction details 简化为 Pi 式纯路径数组——后者记入 session-compaction change 的约束)。
