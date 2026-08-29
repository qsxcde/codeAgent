## Why

V4-24 让用户能够找到会话，但会话数量增长后仍缺少整理和释放本地数据的安全入口。需要把可逆的归档与不可逆的删除明确区分，并在当前运行、路径安全和批量失败场景下给出可操作反馈。

## What Changes

- 为会话增加可持久化的归档状态；归档不改写或删除 JSONL 历史，默认会话列表隐藏已归档会话，并支持恢复。
- 为 `SessionStore` 和 `SessionManager` 增加归档、恢复、单个删除和批量删除能力；删除同时清理会话 JSONL 与派生索引。
- 删除操作要求显式确认，批量删除先校验全部目标；当前会话、运行中的会话、非法会话 ID 和越界文件路径不得删除。
- TUI 增加 `/sessions archive <id...>`、`/sessions unarchive <id...>`、`/sessions archived` 和 `/sessions delete <id...> confirm`，失败、部分成功和空态均就地反馈，不触发模型请求。
- 补充双存储后端、重启、权限/路径保护、批量失败和 TUI 确认回归，并更新规格、架构、测试和使用文档。

## Capabilities

### New Capabilities

### Modified Capabilities

- `sessions`: 增加会话归档、恢复、删除和批量安全操作的持久化与生命周期要求。
- `tui`: 增加会话整理命令、显式删除确认和操作反馈要求。

## Impact

- 影响 `session/persistence` 的 `SessionRef`、查询、JSONL 索引和两个存储后端，以及 `SessionManager` 的生命周期保护。
- 影响 TUI 会话命令解析和帮助文案；现有列表、搜索、恢复最近会话和 id 切换保持兼容，但默认列表不再展示已归档会话。
- 不新增第三方依赖；JSONL 使用已有 `meta` entry 扩展归档状态，删除只操作目标会话文件和对应索引。
