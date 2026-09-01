## 1. 记录模型与 JSONL codec

- [x] 1.1 先补充 `SubagentRunRecord` 的边界、JSON-safe 结果、非终态/终态和 `abandoned/process_restarted` 恢复测试
- [x] 1.2 在 `session/persistence` 增加有界运行记录模型、entry TypedDict/codec 和按 `delegation_id` 折叠的读取逻辑
- [x] 1.3 为记录的任务标签、身份、摘要、诊断、findings/evidence/usage/artifact 设置固定上限，拒绝或截断无界 payload，且不复制 prompt/context/子 transcript

## 2. 双后端存储与兼容

- [x] 2.1 先补充 JsonFileStore 的 `subagent` entry round-trip、append-only、索引/最近活动/标题不变和损坏记录恢复测试
- [x] 2.2 扩展 `SessionStore` 端口、JsonFileStore 写入/流式读取和 MemoryStore 镜像实现；未知旧记录继续被安全忽略
- [x] 2.3 覆盖旧 JSONL 无 Subagent 字段、缺字段、重复终态和非终态记录，确认普通消息、usage、压缩和 fork 语义不回归

## 3. 父会话运行记录接入

- [x] 3.1 先补充父级事件到记录的映射、关键状态去重、终态幂等、记录写失败隔离和异步边界测试
- [x] 3.2 扩展 `SessionPersistence`/`SessionCommitter` 与恢复快照，建立唯一的父级 Subagent 事件观察点和有序 drain
- [x] 3.3 将 `SUBAGENT_QUEUED`、`SUBAGENT_STARTED`、关键进度和 `SUBAGENT_FINISHED` 接入父会话记录；确保 child session 仍不使用父 store
- [x] 3.4 在父回合提交前及取消/失败收尾时等待记录任务得到确定结果，但记录失败不覆盖父 Agent 主结果

## 4. 重启恢复与 TUI 投影

- [x] 4.1 先补充恢复后 completed/failed/abandoned 委派块、无活动计数、无动画和旧会话空记录的 TUI 回归测试
- [x] 4.2 让 `AgentSession` 暴露恢复后的有界记录，并在普通 `hydrate_history` 中创建独立折叠 `SubagentBlock`
- [x] 4.3 将大历史后台恢复快照中的 Subagent projection 一并迁移，切换会话时清空旧投影且不重放/重写记录
- [x] 4.4 验证恢复记录不进入 assistant/tool/error 普通消息、不创建子 Session、不产生幽灵运行或重复终态

## 5. 文档、规格与质量门禁

- [x] 5.1 更新 `docs/iteration/v0.5.md`、`docs/design/architecture.md`，记录 V5-08 的记录格式、abandoned 语义和非目标
- [x] 5.2 运行 session/Subagent/TUI 窄测试、unit/contract、integration/e2e/platform/compatibility、performance 和全量测试
- [x] 5.3 运行 Ruff、规模扫描、`git diff --check`、OpenSpec strict validation 和 `uv build`，检查敏感数据与差异范围
- [x] 5.4 同步 delta specs 到主规格，核对所有任务完成后准备归档和中文提交
