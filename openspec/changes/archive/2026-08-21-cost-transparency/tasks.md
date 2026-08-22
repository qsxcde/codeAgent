## 1. usage 归一扩展

- [x] 1.1 `container._usage_of()` 扩展:新增 `cached_tokens`,兼容 `prompt_tokens_details.cached_tokens` 与 `prompt_cache_hit_tokens` 双拼写;保留 `reasoning_tokens` 原始字段
- [x] 1.2 补归一测试:OpenAI 口径、供应商口径、双字段缺失兜底 0

## 2. 会话存储落库

- [x] 2.1 `SessionStore` 协议新增 `append_usage(session_id, usage)` / `load_usage(session_id)`(聚合返回 `UsageStats`)
- [x] 2.2 `JsonFileStore`:`usage` entry 追加 + 读侧单遍累加聚合;缺失字段容错(旧文件向后兼容)
- [x] 2.3 `MemoryStore`:内存累加聚合,与文件后端一致
- [x] 2.4 补两后端测试:追加、聚合累计、空会话空态、旧文件无 usage 兼容

## 3. session 落库接入

- [x] 3.1 `session._on_internal_event` 扩展:累计本轮 input/output/reasoning/cached(而非仅 input_tokens)
- [x] 3.2 `run()` 成功路径追加本轮聚合 usage;失败/取消不落盘(与消息持久化同承诺)
- [x] 3.3 补测试:成功轮落库、失败/取消不落库、一轮多步 ReAct 聚合

## 4. 展示

- [x] 4.1 TUI `/status` 新增「用量」区块:输入 / 输出(含推理)/ 缓存命中率(约 X%,含原始计数);空态「用量: (无)」;命中率钳制 0~100%
- [x] 4.2 CLI headless:`_respond` 顺带聚合 usage,`_headless_once/loop` 回复尾部输出一行用量统计
- [x] 4.3 补展示测试:`/status` 用量行断言(含空态、命中率边界)、CLI 尾部行断言

## 5. 收尾

- [x] 5.1 全量 `uv run pytest` 全绿(零网络零密钥);`openspec validate` 通过
