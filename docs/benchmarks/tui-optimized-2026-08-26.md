# TUI 历史渲染与生命周期优化对比（2026-08-26）

> 本文记录一次 macOS 优化前后对照，不是当前 GitHub CI 的门禁结果。当前 CI 观测见 [`tui-ci-2026-08-28.md`](tui-ci-2026-08-28.md)。

本次对比复用 [TUI 性能基线](tui-baseline-2026-08-26.md) 的离线纯组件场景、参数和 Python 环境。优化实现增加了 Transcript 有界缓存、可见范围索引、事件帧缓冲、活动 Markdown 稳定前缀缓存和大恢复成本阈值。

## 对比结果

| 场景 | 参数 | 基线 frame p50 / p95 (ms) | 优化后 frame p50 / p95 (ms) | 基线峰值 / 优化后 (bytes) | 优化后缓存条目 | 事件/帧 |
|---|---|---:|---:|---:|---:|---:|
| history | 1000 blocks | 1.114666 / 1.490208 | 1.684500 / 1.701875 | 745856 / 902240 | 13 | 0.000 |
| stream | 100 blocks / 10000 chars | 4.417958 / 8.229167 | 4.705459 / 8.326042 | 2061933 / 983602 | 13 | 1.025 |
| tool-output | 100 blocks / 20000 bytes | 0.285959 / 0.339083 | 0.330958 / 0.399167 | 102075 / 112861 | 12 | 2.000 |
| restore | 1000 messages | 1.102708 / 1.223459 | 1.276792 / 1.383583 | 590984 / 689646 | 13 | 0.000 |

优化后的缓存条目保持在视口物化规模，而不是随 1000 个历史块增长；流式场景峰值 Python 分配下降约 52%。frame 时间在这组低迭代微基准中没有全部下降，尤其 history/restore 仍包含完整布局估算，后续应以真实终端录制和更高迭代数继续观察。帧缓冲本身通过 TUI 事件回归测试验证，当前离线 benchmark 仍按原始逐事件模型调用，以保持与基线的可比性。

## 运行方式

```bash
uv run python scripts/benchmark_tui.py --scenario history --blocks 1000 --iterations 3
uv run python scripts/benchmark_tui.py --scenario stream --blocks 100 --stream-chars 10000 --iterations 3
uv run python scripts/benchmark_tui.py --scenario tool-output --blocks 100 --tool-output-bytes 20000 --iterations 3
uv run python scripts/benchmark_tui.py --scenario restore --blocks 1000 --iterations 3
```
