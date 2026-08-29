## Why

会话索引已经能够加速单个会话读取，但目前缺少多会话规模和失效隔离的回归契约；后续修改可能让 `/sessions` 或 `--continue` 对每个 JSONL 重复全量解析。V4-27 需要把索引命中、单目标回源和最近会话选择固定为可观测的性能行为。

## What Changes

- 为 JSONL 会话列表增加多会话索引命中回归，验证有效索引只读取元数据，不扫描任何会话正文。
- 为索引缺失、损坏和源文件变更增加失效隔离回归，验证只有对应会话回源重建，其余会话继续走索引。
- 验证 `SessionManager.continue_recent()` 复用索引提供的最近活动排序，并在选择目标后只恢复目标会话。
- 更新 sessions 主规格、v0.4 进度和测试文档，记录索引性能边界及可接受的单目标回源行为。

## Capabilities

### New Capabilities

### Modified Capabilities

- `sessions`: 会话列表和最近会话恢复 SHALL 优先使用有效元数据索引，并将索引失效的回源范围限制在受影响会话。

## Impact

影响 `session/persistence/jsonl` 的索引读取契约、`SessionManager` 的最近会话入口、sessions 规格和离线契约测试；预计不新增运行时依赖，不改变 JSONL 格式或索引字段，不改变已有直接读取和失效回退语义。
