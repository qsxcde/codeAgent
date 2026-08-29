## 1. 查询契约与存储后端

- [x] 1.1 增加 SessionQuery/SessionRef.status 的值对象、字段校验、匹配和旧调用兼容测试。
- [x] 1.2 让 JsonFileStore/MemoryStore 支持标题、模型、时间和状态查询，覆盖排序、空结果、索引命中、索引重建和损坏文件隔离。

## 2. SessionManager 运行态

- [x] 2.1 增加 AgentSession.is_running 与 SessionManager.list(query) 的状态叠加，覆盖 running、completed、failed、cancelled 和重启 idle 语义。
- [x] 2.2 确认查询为只读操作，不改变当前会话、最近活动时间、消息、压缩状态或 JSONL 文件。

## 3. TUI 搜索与筛选入口

- [x] 3.1 实现 `/sessions search <text>` 和 `/sessions filter key=value...`，复用会话查询契约并展示数量、标题、模型、时间、状态和 id。
- [x] 3.2 覆盖组合筛选、引号值、非法条件、空结果、模型请求不触发以及既有 sessions/list/recent/id 入口兼容。

## 4. 验收与文档

- [x] 4.1 更新 sessions/TUI 主规格、v0.4 状态、测试指南、架构文档和 README 使用说明。
- [x] 4.2 运行相关窄测、unit/contract、全量测试、Ruff、规模扫描、OpenSpec 校验、差异检查和构建检查。
