## ADDED Requirements

### Requirement: usage 用量记录 entry

会话 JSONL 文件 SHALL 支持独立的 `usage` 用量记录 entry,记录单轮对话的输入、输出、推理与缓存命中 token 计数;写入 SHALL 为追加式(append-only,不重写历史);读侧 SHALL 能按会话聚合所有用量记录为累计总量。

#### Scenario: 追加用量记录 entry

- **WHEN** 一轮对话成功完成且模型返回 usage
- **THEN** 该轮用量作为 `usage` entry 追加到会话文件末尾,历史 entry 不被修改

#### Scenario: 聚合用量

- **WHEN** 读取会话的用量聚合
- **THEN** 返回所有 `usage` entry 的输入、输出、缓存命中累计值

#### Scenario: 未完成轮次不写用量

- **WHEN** 一轮对话失败或取消
- **THEN** 不追加该轮的 `usage` entry(与消息持久化同承诺:未完成轮次永不落盘)
