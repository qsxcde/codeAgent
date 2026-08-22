## Context

见 proposal.md — Why。当前 usage 链路已完整:SSE 解析(`ai/protocol/sse.py`)原样保留 `usage` dict → `container._usage_of()` 归一为 `{input_tokens, output_tokens, reasoning_tokens}`(**缓存命中在此被丢弃**)→ `core/loop.py` emit `EventType.USAGE` → `session._on_internal_event` 仅捕获 `input_tokens` 供压缩阈值。存储层已有 `model_change` 追加 entry 先例与 `_scan` 单遍流式扫描(读侧聚合模式)。

## Goals / Non-Goals

**Goals:**
- 缓存命中 token 进入归一形状(兼容 OpenAI 与供应商双口径)。
- usage 会话级落库(append-only entry)+ 读侧聚合,两后端一致。
- `/status` 与 CLI headless 展示用量(input / output 含 reasoning / 缓存命中率)。

**Non-Goals:**
- 不做单价与费用估算(`estimate_cost` / `ModelSpec` 价格字段全部砍掉)。
- 不做状态栏实时 token 计数(DoD 仅要求"至少一处可见")。
- 不做"缓存命中节省多少钱"换算。

## Decisions

### D1: usage 归一扩展,保留原始字段形状

`_usage_of()` 从 `{input, output, reasoning}` 扩为 `{input_tokens, output_tokens, reasoning_tokens, cached_tokens}`。

- 缓存命中兼容双拼写:`usage.prompt_tokens_details.cached_tokens`(OpenAI 口径)或 `usage.prompt_cache_hit_tokens`(供应商口径),与既有 `input_tokens or prompt_tokens` 的宽容模式一致。
- **reasoning 并入 output 发生在展示层,不在归一层**:落库保留 `reasoning_tokens` 原始字段(数据完整性、审计可查),展示时 `output = output_tokens + reasoning_tokens`。
- 备选:仅统计三值(input/output/cached),丢弃 reasoning。否决——丢弃导致审计不可还原。

### D2: usage 独立 entry 追加(仿 model_change 先例),读侧聚合

每次 `USAGE` 事件追加一条 `usage` entry,而非 `set_meta` 覆盖聚合:

```
{"type": "usage", "timestamp": ..., "input": N, "output": N, "reasoning": N, "cached": N}
```

- **理由**:usage 是"只增不减"数据,与 append-only 哲学同向;逐次可审计、可对账;`set_meta` 后写覆盖会丢失明细且破坏审计语义。
- `SessionStore` 端口新增 `append_usage(session_id, usage)` / `load_usage(session_id) -> UsageStats`;`JsonFileStore` 追加 entry + 读侧 `_scan` 类单遍累加;`MemoryStore` 内存累加。两后端一致。
- **落库时机**:`run()` 成功路径(现有 `append_message` 循环之后)追加本轮聚合;失败/取消不落盘——与"未完成轮次永不落盘"承诺严格一致。一轮 run 内多次 `USAGE`(ReAct 多步)在 `_on_internal_event` 累计,成功路径落一次本轮总和。

### D3: 展示形态与缓存命中率口径

- 展示行:`用量: 输入 30.1K · 输出 2.4K · 缓存命中 40.2% (12.1K/30.1K)`。
- **命中率分母 = input_tokens**(OpenAI 兼容口径下 `prompt_tokens` 已含 cached,即 input = 命中 + 未命中);`命中率 ≈ cached / input`。
- 钳制:命中率 clamp 到 0~100%(供应商口径异常 `cached > input` 时不误导);`input == 0` 时无命中显示 0%;标注「约」表示估算。
- CLI headless 在 `_respond` 顺带聚合 usage 事件,`_headless_once/loop` 回复尾部输出一行。

## Risks / Trade-offs

- [供应商缓存命中口径不一致(OpenAI 的 cached 可能不含部分厂商的隐性命中)] → 展示标注「约」+ 钳制边界,纯比率不涉计费,风险低。
- [JSONL 文件随 usage entry 增长] → 单条 entry 极短(几个整数),增长可忽略;append-only 承诺不变。
- [`reasoning` 并入 output 后用户看到的总输出大于模型原始 output_tokens] → 展示行用"输出(含推理)"措辞,`/status` 与 CLI 一致,避免误解。

## Migration Plan

无数据迁移:新 `usage` entry 类型对旧会话文件向后兼容(`_scan`/`load_usage` 对缺失字段容错);旧文件无 usage entry 时聚合返回空态(`/status` 显示「用量: (无)」)。无回滚需求(纯增量能力)。

## Open Questions

无(探索阶段五个决策点已全部收敛)。
