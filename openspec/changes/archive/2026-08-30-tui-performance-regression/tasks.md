## 1. 指标契约与回归测试

- [x] 1.1 为 benchmark 结果定义版本化的必需指标、场景适用指标和 `passed`/`regression`/`incomparable`/`incomplete` 状态测试。
- [x] 1.2 增加可注入 monotonic clock 与事件边界测试，覆盖提交准备态首帧、首个可见 token、重复/缺失事件和无用户内容序列化。
- [x] 1.3 增加丢帧、超帧和控制事件延迟快照测试，确认未发生与未采集不混为零。

## 2. 确定性 TUI 性能夹具

- [x] 2.1 扩展 benchmark fixture，覆盖 submit、first-token、stream、history、tool-output、restore 和 scroll-resize，并保持固定输入与事件顺序。
- [x] 2.2 将 `TuiRenderCoordinator` 的帧、generation、丢帧和超帧计数接入只读 benchmark 快照，不改变生产交互行为。
- [x] 2.3 统一报告中的 p50/p95、样本数、峰值 Python 分配、控制延迟和长会话计数，兼容既有 CLI 参数和旧报告读取。

## 3. 基线比较与 CI

- [x] 3.1 扩展 `compare_benchmark.py` 的兼容性检查、缺失字段诊断、时间阈值比较及丢帧/超帧计数输出。
- [x] 3.2 更新 CI 性能 job，生成标准与长会话报告，执行可配置回归告警并始终上传原始/比较 JSON。
- [x] 3.3 固化新 schema 的 Linux/Python 3.12 基线更新流程，避免跨平台或参数不同的报告被误用作基线。

## 4. 验收与文档

- [x] 4.1 增加离线单元/契约测试和 Textual 交互回归，验证指标采集不改变输入、取消、滚动和确认行为。
- [x] 4.2 更新性能报告、测试指南、架构说明和 v0.4 V4-22 状态，记录实际运行环境与不可比较边界。
- [x] 4.3 运行相关测试、分层测试、全量测试、Ruff、规模扫描、差异检查、OpenSpec 校验和构建检查。
