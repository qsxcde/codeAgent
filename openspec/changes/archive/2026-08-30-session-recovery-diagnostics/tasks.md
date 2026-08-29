## 1. 恢复报告与存储边界

- [x] 1.1 新增 `RecoveryDiagnostic`、`SessionRecoveryReport`、状态值域和携带报告的恢复异常，保持字段可序列化且文案与稳定 code 分离。
- [x] 1.2 扩展 `SessionStore` 恢复报告端口；MemoryStore 返回健康报告并覆盖不存在目标的统一诊断。
- [x] 1.3 为 JsonFileStore 增加流式恢复检查：识别坏 JSON 行、无效消息、header/版本、压缩切点和索引缺失/损坏/过期，并输出有效记录数、跳过范围与建议动作。
- [x] 1.4 调整 JSONL 上下文/消息读取，在安全边界内跳过不可解码记录或回退完整有效消息，不伪造丢失数据且不改变既有正常恢复语义。

## 2. Session 恢复集成

- [x] 2.1 让 SessionPersistence 保存恢复报告；degraded 会话局部加载并可继续，unavailable 会话以 typed error 拒绝激活且不创建/覆盖空会话。
- [x] 2.2 让 SessionManager 暴露按 id 查询报告，并确保切换失败不替换当前驻留会话；补充有效会话、损坏会话和不兼容会话的双后端回归测试。

## 3. CLI/TUI 可见性

- [x] 3.1 增加统一恢复报告格式化，TUI 支持 `/sessions recovery <id>`，恢复成功后显示 degraded 诊断并保持输入可用。
- [x] 3.2 让 TUI 不可恢复切换和 headless `--session`/`--continue` 输出会话 id、状态、稳定 code、影响和下一步，返回非零或保持当前会话不变；补充无模型调用回归测试。

## 4. 文档与验收

- [x] 4.1 更新 sessions/TUI 主规格、README、测试指南、架构说明和 v0.4 进度，记录兼容文件和用户恢复动作。
- [x] 4.2 运行恢复窄测、unit/contract、全量测试、Ruff、规模扫描、OpenSpec 校验、差异检查和构建检查。
