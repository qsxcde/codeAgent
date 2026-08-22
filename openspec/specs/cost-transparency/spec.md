# cost-transparency Specification

## Purpose

定义 token 用量统计与展示能力:把模型返回的 usage 元数据(input / output / 缓存命中)归一、落库并聚合,在 TUI `/status` 与 CLI headless 尾部可见,让用户感知每次对话的 token 消耗(不估算费用)。

## Requirements

### Requirement: usage 归一含缓存命中

系统 SHALL 把模型返回的 usage 元数据归一为统一形状,包含输入 token、输出 token、推理 token 与缓存命中 token;缓存命中 SHALL 兼容 OpenAI 口径(`prompt_tokens_details.cached_tokens`)与供应商口径(`prompt_cache_hit_tokens`)两种字段形态。

#### Scenario: 归一化缓存命中(OpenAI 口径)

- **WHEN** 模型返回的 usage 含 `prompt_tokens_details.cached_tokens`
- **THEN** 归一结果中的缓存命中 token 取该字段值

#### Scenario: 归一化缓存命中(供应商口径)

- **WHEN** 模型返回的 usage 含 `prompt_cache_hit_tokens`(OpenAI 口径字段缺失)
- **THEN** 归一结果中的缓存命中 token 取该字段值

### Requirement: usage 会话级落库与聚合

系统 SHALL 把每轮对话产生的 usage 以独立记录追加到会话存储(append-only,不重写历史);读侧 SHALL 按会话聚合出输入 / 输出 / 缓存命中的累计总量;未完成(失败 / 取消)的轮次 SHALL 不产生用量记录。

#### Scenario: 追加用量记录

- **WHEN** 一轮对话成功完成且模型返回了 usage
- **THEN** 该轮用量作为独立记录追加到会话存储,历史记录不被修改

#### Scenario: 会话用量聚合

- **WHEN** 读取一个会话的累计用量
- **THEN** 返回输入、输出、缓存命中的累计总量(所有成功轮次之和)

#### Scenario: 未完成轮次不落盘

- **WHEN** 一轮对话失败或取消
- **THEN** 该轮产生的用量不被写入会话存储

### Requirement: 用量可见展示

系统 SHALL 在至少一处用户可见位置展示会话累计用量,含输入、输出与缓存命中率;缓存命中率 SHALL 按「约 cached/input」估算并钳制在 0~100%,且不换算为费用。

#### Scenario: TUI 状态展示用量

- **WHEN** 用户在 TUI 中查看会话状态(`/status`)
- **THEN** 输出包含用量行:输入 token、输出 token(含推理 token)、缓存命中率(约 X% 与原始计数)

#### Scenario: CLI headless 展示用量

- **WHEN** 用户在 headless 模式完成一轮对话
- **THEN** 回复尾部输出一行用量统计(输入 / 输出 / 缓存命中)

#### Scenario: 缓存命中率边界

- **WHEN** 缓存命中 token 大于输入 token(供应商口径异常)或输入为 0
- **THEN** 命中率显示为 100%(有命中)或 0%(无命中),且原始计数仍如实展示
