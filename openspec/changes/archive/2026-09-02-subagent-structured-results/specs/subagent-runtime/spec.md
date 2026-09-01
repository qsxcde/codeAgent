## MODIFIED Requirements

### Requirement: 有界结果回传

系统 SHALL 将子 Agent 的终态转换为父 Agent 可消费的 ToolResult。成功结果 SHALL 包含不超过有效 `max_output_chars` 的文本摘要及 delegation_id、child_run_id、子状态和清理诊断，并 SHALL 暴露有界的 findings、evidence、usage 和可选 artifact 引用；失败、拒绝、超时或取消 SHALL 设置错误/非成功状态并携带稳定 reason code 和可诊断信息。父会话 SHALL 只接收该委派结果，不接收子 Agent 的完整 transcript、内部任务对象或无界工具输出；任何 `cleanup_uncertain` SHALL 通过结构化字段或诊断传递，不能被标记为已确认清理。

结构化结果中的 findings SHALL 是可选的有界结论项；当子 Agent 没有显式产生机器可读 findings 时，系统 SHALL 保留空列表，不得把任意自然语言自动猜测为结构化结论。evidence SHALL 只引用子 Agent 实际观察到的工具输出事实，usage SHALL 使用统一的 input/output/reasoning/cached token 形状，artifact SHALL 只保存可追踪的单个引用而不内嵌产物内容。结构化结果 SHALL 使用 JSON-safe 表示，并限制为最多 16 个 finding、32 条 evidence、1 个 artifact；摘要、结论、证据摘录、诊断和引用文本均 SHALL 受固定字符上限约束，token 数 SHALL 是非负整数。

#### Scenario: 子 Agent 成功返回摘要

- **WHEN** 子 Agent 完成只读任务并产生最终回答，且临时资源关闭已确认
- **THEN** `delegate` 返回非错误 ToolResult，内容为有限摘要，details 保留委派标识、子运行标识和 `completed` 状态，父 Agent 可据此继续请求模型

#### Scenario: 成功结果包含结构化字段

- **WHEN** 子 Agent 完成任务并产生结构化 findings、工具证据、token usage 或 artifact 引用
- **THEN** `SubagentResult` 和 `delegate` ToolResult.details 分别保留对应的 typed 值和 JSON-safe 字典，父 Agent 无需解析摘要文本即可读取这些字段

#### Scenario: 没有机器可读发现时保持诚实

- **WHEN** 子 Agent 只返回普通最终回答，没有显式结构化 findings
- **THEN** 结果的 findings 为空列表，系统不把自然语言句子或完整摘要伪装成自动提取的 finding

#### Scenario: 工具输出转为有限证据

- **WHEN** 子 Agent 的历史包含带工具输出元数据的工具结果
- **THEN** 系统最多返回有界的 evidence 项，保留工具来源、文件/范围或 artifact locator、完整性和有限摘录；不把完整工具输出或子 transcript 复制到父结果

#### Scenario: 用量和 artifact 引用可被读取

- **WHEN** 子运行观测到模型 token usage，或工具输出提供 artifact_ref/artifact_path
- **THEN** 结果按统一 token 字段返回非负用量，并返回最多一个有界 artifact 引用；不存在对应事实时 usage/artifact 保持空值而不是猜测

#### Scenario: 结构化结果越界被拒绝

- **WHEN** findings/evidence 数量、文本长度、artifact 引用长度或 token 数违反结果边界，或 evidence 引用不存在的 evidence id
- **THEN** 系统拒绝该无效 `SubagentResult` 并报告 `invalid_result`，不得把越界内容写入父上下文

#### Scenario: 省略结构化字段保持兼容

- **WHEN** 旧的 runner 或调用方只构造 delegation_id、status、summary、failure 和 diagnostics
- **THEN** 结果将 findings/evidence 归一为空列表、usage/artifact 归一为空值，既有摘要、失败状态、清理诊断和 ToolResult 映射保持不变

#### Scenario: 子 Agent 失败可区分

- **WHEN** 子 Agent 在启动、执行或预算治理阶段失败
- **THEN** `delegate` 返回错误 ToolResult，status 与稳定 failure reason code 可区分失败原因，父 Agent 不会把该结果当作成功摘要

#### Scenario: 终态结果不泄漏完整子历史

- **WHEN** 父 Agent 将 delegate ToolResult 写入自己的工作上下文或提交自己的会话
- **THEN** 结果只包含有界摘要、结构化结果和诊断，不包含子 Agent 的完整消息列表、内部可变上下文或无界工具输出

#### Scenario: 清理不确定不会被伪装成成功收尾

- **WHEN** 子 Agent 已结束但取消、超时或关闭阶段无法确认其模型、工具、事件或子进程资源已经停止
- **THEN** 结果保留 `cleanup_uncertain=true` 和有限诊断；ToolResult 的 cleanup_confirmed 不得为 true
