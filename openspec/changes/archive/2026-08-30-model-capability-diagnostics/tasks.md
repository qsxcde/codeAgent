## 1. 能力模型与解析

- [x] 1.1 扩展 `ModelSpec` 与 `models.json` 严格解析，支持可选的工具调用和 prompt cache 三态字段，保留旧记录兼容。
- [x] 1.2 新增组合根 `ModelCapabilities` 及 resolver，复用模型目录/预算窗口来源，提供稳定的状态值和只读快照。
- [x] 1.3 为目录解析、能力 resolver、未知状态和模型切换补充离线单元/契约测试。

## 2. 运行时与 TUI 接入

- [x] 2.1 将能力快照注入 `ChatModelPort`、运行时配置和初始 `FooterInfo`，不改变 core 依赖边界。
- [x] 2.2 在 TUI `/status` 展示上下文窗口、思考、工具调用、缓存声明及缓存观测，并在热切换后刷新。
- [x] 2.3 补充 TUI 状态输出、热切换和无副作用回归测试，保持已有 `/model` picker 与 rebuild 回调兼容。

## 3. 文档与验收

- [x] 3.1 更新模型目录/架构、测试说明和 v0.4 迭代记录，说明静态声明、未知状态和缓存观测边界。
- [x] 3.2 运行窄测试、unit/contract、全量测试、Ruff、规模/差异检查、构建和 OpenSpec 校验。
