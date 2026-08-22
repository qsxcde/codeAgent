## Why

信任赤字的核心诉求之一(需求分析 F-22「成本透明」):用户无法感知每次对话消耗了多少 token。当前 `usage` 事件链路已完整(SSE 解析 → 归一 → `EventType.USAGE` 事件),但**原始数据在归一化时丢弃了缓存命中 token,且用量既不落库也无展示**——用户对 token 消耗零可见性。本变更落地 F-22 的最小闭环:token 用量统计(input / output / 缓存命中)落库 + 可见展示,不估算费用。

## What Changes

- **usage 归一形状扩展**:`container._usage_of()` 新增 `cached_tokens` 字段,兼容 OpenAI 口径(`prompt_tokens_details.cached_tokens`)与供应商口径(`prompt_cache_hit_tokens`)双拼写;`reasoning_tokens` 保留原始字段(数据完整性),展示时并入 output。
- **usage 落库**:`SessionStore` 端口新增 `append_usage` / `load_usage`(读侧聚合);每次 `USAGE` 事件以独立 `usage` entry 追加(仿 `model_change` 追加先例,append-only 承诺不破);`JsonFileStore` / `MemoryStore` 两后端一致;失败/取消轮次不落盘(与"未完成轮次永不落盘"承诺一致)。
- **会话级聚合与展示**:
  - TUI `/status` 新增「用量」区块:`输入 X · 输出 Y · 缓存命中 Z% (N/M)`;
  - CLI headless 尾部新增一行用量统计;
  - 事件流零改动(usage 事件已含原始值)。
- **缓存命中率估算**:命中率 ≈ `cached / input`,展示为「约 X%」并钳制 0~100%,无计费换算(不估算费用)。

## Capabilities

### New Capabilities
- `cost-transparency`: token 用量统计与展示能力——usage 归一(含缓存命中)、会话级用量落库与聚合、`/status` 与 CLI 用量展示。

### Modified Capabilities
- `sessions`: JSONL 会话文件 entry 类型新增 `usage`(用量记录),`load_usage` 聚合语义进入会话存储契约。
- `tui`: `/status` 命令输出新增「用量」区块(用量可见)。

## Impact

- `src/codeagent/app/container.py`:`_usage_of()` 归一扩展(兼容双拼写,补 `cached_tokens`)。
- `src/codeagent/session/store.py`:`SessionStore` 协议 + `JsonFileStore` / `MemoryStore` 两后端新增 `append_usage` / `load_usage`。
- `src/codeagent/session/session.py`:`_on_internal_event` 累计 usage,`run()` 成功路径落库。
- `src/codeagent/app/tui/view.py`:`/status` 区块扩展(用量行)。
- `src/codeagent/app/main.py`:headless 尾部用量行。
- 测试:usage 归一兼容、两后端落库/聚合、缓存命中率边界、展示断言(全部离线,mock/fake 注入)。
