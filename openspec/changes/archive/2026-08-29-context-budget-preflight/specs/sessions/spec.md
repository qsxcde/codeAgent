## MODIFIED Requirements

### Requirement: usage 用量记录 entry

会话 JSONL 文件 SHALL 支持独立的 `usage` 用量记录 entry,记录单轮对话的输入、输出、推理与缓存命中 token 计数;写入 SHALL 为追加式(append-only,不重写历史);读侧 SHALL 能按会话聚合所有 usage 记录为累计总量。只有消息成功提交且运行进入 completed 的轮次才允许追加 usage;失败、取消、持久化提交失败、清理不确定或请求前预算阻断的未完成轮次 SHALL 不追加 usage。

#### Scenario: 追加用量记录 entry

- **WHEN** 一轮对话成功完成且模型返回 usage
- **THEN** 该轮用量作为 `usage` entry 追加到会话文件末尾,历史记录不被修改

#### Scenario: 聚合用量

- **WHEN** 读取一个会话的用量聚合
- **THEN** 返回输入、输出、缓存命中累计值(所有成功轮次之和)

#### Scenario: 未完成轮次不写用量

- **WHEN** 一轮对话失败或取消
- **THEN** 不追加该轮的 `usage` entry(与消息持久化同承诺:未完成轮次永不落盘)

#### Scenario: 提交失败不写用量

- **WHEN** 消息提交或其一致性校验失败
- **THEN** 该轮 usage 不追加,历史累计用量保持不变,并产生可诊断的 persistence_failed 结果

#### Scenario: 预算阻断不写用量

- **WHEN** 模型请求在 provider 调用前因超预算或不确定策略被阻断
- **THEN** 不追加 usage entry,不改变已提交累计 usage,并保留本次预算判定供运行期诊断

#### Scenario: 收尾后仍可继续

- **WHEN** 一轮成功提交后再次运行、恢复或分叉会话
- **THEN** 新运行只使用已提交历史和已提交 usage,不重复计算或写入上一轮数据
