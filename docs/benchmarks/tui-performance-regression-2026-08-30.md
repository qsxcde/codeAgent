# TUI 性能回归 v2 观测

本报告记录 `tui-performance-regression` 的本地验收结果。数据来自纯组件、离线
fixture，不启动真实 provider、不访问网络、不读取用户会话内容；本机结果不替代
Linux/Python 3.12 正式基线。

## 运行环境

- Commit: `fded85dc07a15cd821c85de2a89c50db824e7ba6`
- Python: 3.12
- Platform: macOS，视口 80×24
- Schema: 2
- 参数：100 history blocks、10000 stream chars、20000 tool-output bytes、3 次迭代

## 结果

| 场景 | frame p50/p95 (ms) | 控制 p95 (ms) | 峰值 Python 分配 (bytes) | dropped / over-budget |
| --- | ---: | ---: | ---: | ---: |
| history | 0.419458 / 0.776042 | 不适用 | 249978 | 0 / 0 |
| restore | 0.333417 / 0.403000 | 不适用 | 206079 | 0 / 0 |
| stream | 4.299875 / 8.006459 | 0.041541 | 1096021 | 0 / 0 |
| tool-output | 0.413292 / 0.744500 | 不适用 | 251155 | 0 / 0 |
| scroll-resize | 0.608958 / 1.024584 | 不适用 | 293636 | 0 / 0 |

stream 的提交延迟为 p50/p95 `0.394542 / 0.763125 ms`，首个可见 token 延迟为
`0.770792 / 1.186042 ms`，各有 3 个样本；frame 共 123 个样本。所有报告均只含
指标、计数、fixture 参数和环境元数据。

## 判定边界

当前 macOS 报告与仓库内旧 Linux schema v1 基线比较时应为 `incomparable`，原因是
schema 不同；这不是通过或回归结论。CI 在 Linux/Python 3.12 产生同一组 schema v2
报告后，可使用 `scripts/update_tui_baseline.py` 生成候选基线，再经人工检查提交到
`docs/benchmarks/tui-baseline.json`。
