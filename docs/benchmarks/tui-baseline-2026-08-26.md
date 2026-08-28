# TUI 历史性能基线（2026-08-26）

> 本文是 2026-08-26 macOS 环境下的历史对照数据，不是当前 GitHub CI 的门禁基线。当前 CI 观测见 [`tui-ci-2026-08-28.md`](tui-ci-2026-08-28.md)；不同平台、提交和输入规模之间不得直接判定性能回归。

该结果来自纯组件、离线 benchmark，不启动 Textual、不访问网络、不读取用户会话内容。结果用于同一环境下的优化前后比较，不作为跨机器的绝对性能承诺。

## 运行环境

- Python: `3.12.13`
- Platform: `macOS-26.6.2-arm64-arm-64bit`
- Commit: `1fc6a38fa69b74c97902113a58536ecb4a96ecfb`
- Iterations: `3`
- Viewport: `80 x 24`
- Memory: 独立测量 pass，不计入渲染时延样本

## 场景结果

| 场景 | 输入规模 | Frame p50 (ms) | Frame p95 (ms) | 额外 p95 (ms) | 峰值 Python 分配 (bytes) |
|---|---:|---:|---:|---:|---:|
| history | 1000 blocks | 1.114666 | 1.490208 | model 1.483083 | 745856 |
| stream | 100 blocks / 10000 chars | 4.417958 | 8.229167 | markdown 10.118 | 2061933 |
| tool-output | 100 blocks / 20000 bytes | 0.285959 | 0.339083 | model 0.332250 | 102075 |
| restore | 1000 messages | 1.102708 | 1.223459 | restore 0.618 | 590984 |

流式场景产生 `120` 个 frame 样本和 `120` 个事件归约样本；其它场景按每轮实际渲染帧记录。缓存与可视区域计数会随 JSON 结果一并输出。

## 运行方式

```bash
uv run python scripts/benchmark_tui.py \
  --scenario stream \
  --blocks 100 \
  --stream-chars 10000 \
  --iterations 3 \
  --output /tmp/tui-baseline.json
```

可用场景：`history`、`stream`、`tool-output`、`restore`、`scroll-resize`。后续渲染优化应复用相同参数和环境，并比较 render p50/p95、Markdown 耗时、缓存规模与峰值分配。
