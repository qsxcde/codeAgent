# TUI 性能边界与回归判定

> 版本：v0.4
> 更新日期：2026-09-01
> 适用范围：离线 TUI 组件基准、Linux CI 性能报告和发布候选检查

本文定义的是 v0.4 的可感知性能上限和可复现的回归判定，不是某台机器的理论最大吞吐量。
模型网络延迟、Provider 响应时间和真实终端绘制时间不包含在离线 fixture 的测量中，不能用本
文档的数值推断完整请求的 TTFT 或端到端耗时。

## 1. 固定测量口径

正式回归基线必须同时满足以下条件：

- Ubuntu GitHub Actions runner、Python 3.12；
- benchmark schema v2；
- 视口 `80 x 24`；
- `100` 个 history blocks、`10000` 个 stream chars、`20000` 字节 tool output；
- `3` 次迭代；
- `history`、`restore`、`stream`、`tool-output` 四个场景各一份报告。

`scroll-resize` 与长会话扩展场景属于补充观测，不直接写入四场景正式基线。长会话使用
`1000`、`5000`、`10000` blocks、每组一次迭代，用于确认可见区物化和索引扫描不会随历史
规模线性膨胀。

## 2. v0.4 性能上限

### 2.1 硬上限

硬上限表示违反后即使相对历史基线没有回归，也应视为性能不合格：

| 指标 | 上限 | 适用场景 | 依据 |
|---|---:|---|---|
| `frame_total_ms.p95` | `<= 33 ms` | 全部场景 | 30 FPS 帧预算 |
| `frame_total_ms.maximum_ms` | `<= 33 ms` | 全部场景 | 为调度器 `33.33 ms` 间隔保留安全余量 |
| `control_event_latency_ms.p95` | `<= 50 ms` | `stream` | 输入、滚动、取消和确认应保持即时可感知 |
| `control_event_latency_ms.maximum_ms` | `<= 100 ms` | `stream` | 单次控制事件的绝对尾延迟 |
| `dropped_frames` | `0` | 全部场景 | 不允许过期帧或新帧被静默丢弃 |
| `over_budget_frames` | `0` | 全部场景 | 不允许帧超过调度预算 |

这里的 `frame_total_ms` 是 benchmark 中模型渲染到 backend 提交前的本地工作时间；
`control_event_latency_ms` 是事件进入到被应用的时间，不包含模型或工具执行时间。

### 2.2 相对回归上限

以下指标受 Python 版本、runner 负载和机器实现影响，不设置跨平台绝对 SLO，而是在完全
可比的报告之间使用同一条回归线：

- `model_render_ms`、`markdown_render_ms`、`restore_ms`、`submit_latency_ms`、
  `first_token_latency_ms` 和 `peak_memory_bytes` 相对正式基线最多增加 `20%`；
- `incomparable` 或 `incomplete` 不是通过，不能用来覆盖性能证据缺失；
- `normal PR` 继续只告警，发布候选必须使用 `--fail-on-regression`；
- `dropped_frames` 和 `over_budget_frames` 仍按 0 增长处理，不适用 20% 宽容区间。

因此，性能判定采用“双门槛”：硬上限保证用户可感知的响应性，相对回归线保证优化不会
在同一环境中持续退化。

## 3. 长会话支持边界

`10000` history blocks 是 v0.4 的已验证观测上界，不是 JSONL 存储或会话数量的绝对上限。
超过这个规模后，系统仍可继续工作，但必须重新运行扩展基准，不能直接沿用 v0.4 的结论。

当前 macOS/Python 3.12.13、`80 x 24` 的补充观测为：

| history blocks | frame p95 (ms) | model render p95 (ms) | 峰值 Python 分配 | blocks inspected / materialized |
|---:|---:|---:|---:|---:|
| 1,000 | 1.378 | 1.333 | 1,985,826 | 23 / 13 |
| 5,000 | 3.588 | 3.541 | 9,667,979 | 23 / 13 |
| 10,000 | 6.723 | 6.662 | 19,266,639 | 23 / 13 |

上表只用于说明当前实现的规模趋势；正式发布证据仍须来自同参数的 Linux CI artifact。
峰值 Python 分配随完整 transcript 增长是预期成本，不能把它误解为可跨机器比较的常量。

## 4. 推荐执行流程

```bash
# 在 Ubuntu/Python 3.12 上生成五个固定场景
for scenario in history stream tool-output restore scroll-resize; do
  uv run python scripts/benchmark_tui.py \
    --scenario "$scenario" \
    --blocks 100 \
    --stream-chars 10000 \
    --tool-output-bytes 20000 \
    --width 80 \
    --height 24 \
    --iterations 3 \
    --output "artifacts/tui-${scenario}.json"
done

# 四个正式场景组装 schema v2 候选基线；scroll-resize 只保留为补充报告
uv run python scripts/update_tui_baseline.py \
  --output artifacts/tui-baseline-v2-candidate.json \
  --baseline-id linux-py312-tui-v2 \
  artifacts/tui-history.json artifacts/tui-restore.json \
  artifacts/tui-stream.json artifacts/tui-tool-output.json

# 候选基线人工复核后，发布候选使用失败即返回非零
uv run python scripts/compare_benchmark.py \
  artifacts/tui-stream.json docs/benchmarks/tui-baseline.json \
  --max-regression 0.20 --fail-on-regression
```

正式基线文件仍需从 schema v2 候选报告人工复核后更新；仓库当前的
`docs/benchmarks/tui-baseline.json` 是 schema v1 历史基线，不能与 schema v2 直接比较。
最新 main CI 已成功运行性能 job，但候选 artifact 仍必须按上述流程复核后才能成为正式
基线。

## 5. 当前状态

当前 main 在 macOS 上按同一基础 fixture 的观测结果为：`history`、`restore`、
`tool-output`、`scroll-resize` 的 frame p95 分别约为 `0.984`、`0.418`、`0.502`、
`0.729 ms`；`stream` 的 frame p95 为 `8.004 ms`，控制事件 p95 为 `0.040 ms`，
提交回显 p95 为 `0.469 ms`，首个可见 token p95 为 `0.927 ms`，丢帧和超预算帧均为 `0`。
这些数值低于硬上限，但因为平台是 macOS，只能作为观测，不能替代 Linux v2 正式基线。
