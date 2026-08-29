## ADDED Requirements

### Requirement: 恢复诊断可见且可操作

TUI SHALL 在会话切换、`/sessions recent` 或指定会话恢复出现降级/不可恢复状态时显示结构化恢复诊断。降级恢复 SHALL 保留有效 transcript 并恢复输入；不可恢复目标 SHALL 保持当前会话和 transcript 不变。诊断文本 SHALL 包含原因、影响范围和可操作的下一步，不得只显示通用异常。

#### Scenario: 切换后显示局部降级

- **WHEN** 用户切换到包含坏记录但仍可识别 header 的会话
- **THEN** TUI 恢复有效历史并显示 `degraded` 及被跳过/回退内容和建议，用户仍可继续输入，且不触发额外模型请求

#### Scenario: 不可恢复切换被保护

- **WHEN** 用户切换到 header 缺失或版本不兼容的会话
- **THEN** TUI 显示 `unavailable`、稳定错误 code 和备份/升级/新建建议，当前会话 transcript、输入状态和运行状态保持不变

#### Scenario: 主动查看恢复诊断

- **WHEN** 用户提交 `/sessions recovery <id>`
- **THEN** TUI 展示该会话的完整恢复状态、诊断原因、影响范围和建议动作；该命令不切换会话、不写入 JSONL、不调用模型

#### Scenario: 正常会话无噪声

- **WHEN** 用户恢复健康会话或查询健康会话诊断
- **THEN** TUI 保持既有恢复反馈，并明确显示无恢复问题，不显示误导性的警告或错误

### Requirement: Headless 恢复失败引导

headless 使用 `--session` 或 `--continue` 恢复失败时 SHALL 以非零状态退出，并在标准错误中输出会话 id、恢复状态、稳定错误 code 和可操作建议；不得静默创建同 id 空会话或发起模型请求。

#### Scenario: 指定会话版本不兼容

- **WHEN** 用户通过 `--session <id>` 选择版本不兼容的会话
- **THEN** CLI 输出不兼容诊断和升级/迁移建议，并返回非零退出码，原会话文件保持不变

#### Scenario: 指定会话局部降级

- **WHEN** 用户通过 `--session <id>` 恢复可局部降级的会话
- **THEN** CLI 在首次对话输出前提示降级原因和建议，然后仅使用有效恢复内容继续运行
