## Why

V4-20 与 V4-21 已经建立工具状态和长会话渲染能力，但当前 TUI 性能基准仍主要覆盖纯组件渲染，无法稳定回答用户提交延迟、首个可见 token、渲染尾延迟、峰值内存和丢帧是否发生回归。现在补齐统一的离线测量和 CI 报告，才能把性能优化从一次性观测变成可持续验收。

## What Changes

- 扩展确定性的 TUI benchmark fixture，覆盖用户提交、准备态首帧、首个文本增量、持续流式渲染、长历史、工具大结果、恢复和滚动/resize 场景。
- 增加提交延迟、首 token 延迟、渲染帧 p50/p95、控制事件 p95、峰值 Python 内存、丢帧/超帧计数等无用户内容指标，并保持报告脱敏。
- 统一 benchmark JSON schema、基线兼容性判断和回归判定；无法比较时明确报告原因，关键指标缺失不得伪装为通过。
- 让 CI 生成并上传完整性能报告，在匹配平台、Python、视口和 fixture 参数时执行可配置的回归告警，同时保持性能 job 非阻塞。
- 增加离线契约测试和性能报告文档，明确固定环境、样本量、阈值、不可比较条件及跨平台解读边界。

## Capabilities

### New Capabilities

无。本变更只完善现有 TUI 性能契约和验收工具。

### Modified Capabilities

- `tui`: 补充流式渲染性能的可观测指标、丢帧语义、固定 fixture 验收和性能报告约束。

## Impact

- 影响 `src/codeagent/app/tui/benchmark/`、TUI 渲染协调器的只读性能快照，以及 `scripts/benchmark_tui.py` 与 `scripts/compare_benchmark.py`。
- 影响 `tests/tui/` 性能与 Textual 集成测试、`.github/workflows/ci.yml` 性能 job、`docs/benchmarks/` 和 `docs/testing.md`。
- 不新增运行时依赖，不改变会话 JSONL、模型请求协议或普通对话语义；性能采样只消费离线夹具和运行期计数器。
