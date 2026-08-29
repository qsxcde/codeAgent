## 1. 组合根扩展对象

- [x] 1.1 在 `app/composition/runtime` 增加 `RuntimeExtensions` 及兼容参数归一化逻辑，承载所有 Runtime 扩展协议。
- [x] 1.2 让 runtime/session 工厂和公开组合根导出统一扩展对象，保留现有散装 `lifecycle_hooks` 调用方式。

## 2. 恢复与 TUI 装配链

- [x] 2.1 将 RuntimeExtensions 透传到 AgentLoopConfig、AgentSession、SessionManager 的创建和恢复路径。
- [x] 2.2 将 RuntimeExtensions 保留在 TUI assembler 的初始配置和 provider/model/effort 重建路径。

## 3. 契约测试与文档

- [x] 3.1 补充组合根注入、session 恢复、TUI 重建的扩展身份/顺序回归和 core/session 禁止具体实现导入测试。
- [x] 3.2 同步生命周期 Hook/core 主规格、架构与 v0.4 文档，完成 OpenSpec 校验。
- [x] 3.3 运行窄测试、分层测试、全量测试、Ruff、差异检查和构建，归档并记录验证结果。
