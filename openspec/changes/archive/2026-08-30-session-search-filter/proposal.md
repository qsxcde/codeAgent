## Why

会话数量增加后，用户只能按最近活动顺序浏览列表，难以快速定位某个主题、模型或时间范围的会话。现有 JSONL 索引已经缓存了必要的展示元数据，现在补齐统一查询契约和 TUI 入口，可以在不重复扫描历史文件的情况下完成日常查找。

## What Changes

- 增加可复用的会话查询条件，支持标题文本、模型、最近活动时间范围和运行状态筛选。
- 让 JsonFileStore 与 MemoryStore 在合法索引/内存元数据上执行筛选；索引损坏或过期时沿用回源重建语义。
- 让 SessionManager 公开带查询条件的列表操作，并为驻留会话叠加实时运行状态；重启后状态回退为安全的空闲态，不伪造历史运行结论。
- 增加 TUI `/sessions search <text>` 和 `/sessions filter key=value...`，展示结果数量、标题、模型、时间、状态及可切换会话 id。
- 保持无参数 `/sessions` 选择器、`/sessions list` 树形展示、`/sessions recent` 和既有会话文件格式兼容。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `sessions`: 会话列表支持按标题、模型、最近活动时间和状态查询，查询使用索引元数据并在失效时重建。
- `tui`: `/sessions` 增加搜索和结构化筛选入口，错误输入就地反馈且不触发模型请求。

## Impact

- 影响 `src/codeagent/session/persistence/`、`src/codeagent/session/manager/`、`src/codeagent/app/tui/session/` 和命令解析/展示测试。
- 扩展 `SessionStore.list`、`SessionManager.list` 和 `SessionRef` 的只读查询语义，不新增运行时依赖，不修改 JSONL entry 格式。
- 更新 `openspec/specs/sessions`、`openspec/specs/tui`、v0.4 状态、测试指南和架构文档。
