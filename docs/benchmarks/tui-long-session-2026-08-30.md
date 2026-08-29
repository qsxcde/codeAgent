# TUI 长会话扩展观测

本报告用于验证 `tui-long-session-rendering` 的规模趋势，不替代正式 Linux/Python 3.12
基线。运行环境为 macOS 26.6.2 arm64、Python 3.12.13，视口 80×24，mixed-shape
fixture，1 次迭代；`p95` 因样本数为 1 仅用于记录本次观测。

| history blocks | model render p50/p95 (ms) | blocks inspected | blocks materialized | index updates | cache entries/rows | peak memory (bytes) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 1.416 / 1.416 | 23 | 13 | 13 | 13 / 21 | 1,984,786 |
| 5,000 | 3.858 / 3.858 | 23 | 13 | 13 | 13 / 21 | 9,666,863 |
| 10,000 | 7.143 / 7.143 | 23 | 13 | 13 | 13 / 20 | 19,265,475 |

运行命令：

```bash
for blocks in 1000 5000 10000; do
  uv run python scripts/benchmark_tui.py \
    --scenario history --blocks "$blocks" --iterations 1 \
    --width 80 --height 24 \
    --output "artifacts/tui-history-${blocks}.json"
done
```

本轮可见区扫描和物化数量保持在固定窗口规模；峰值内存仍随 transcript 本身增长，
这是完整历史对象和索引元数据的预期成本。跨平台结论需要 CI 继续采集同样参数的报告。
