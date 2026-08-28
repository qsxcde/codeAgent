## MODIFIED Requirements

### Requirement: SessionManager 生命周期管理

会话生命周期 SHALL 经管理器管理：可创建新会话、切换当前会话、释放会话、列出会话、继续最近会话；同一时刻 SHALL 仅一个会话可运行。创建、切换、释放、配置替换和关闭运行中的会话时，管理器 SHALL 先请求停止并等待该会话完成取消、工具清理、确认取消和运行收尾，再改变活动集合、端口配置或共享资源。切换会话后，订阅方 SHALL 无需重新订阅即可继续感知当前会话的事件。

#### Scenario: 创建新会话

- **WHEN** 用户请求创建新会话
- **THEN** 管理器先等待当前运行完成停止，再创建独立会话并使其成为当前会话

#### Scenario: 切换会话

- **WHEN** 用户切换到既有会话
- **THEN** 当前运行已经进入终态后，目标会话恢复为当前会话；订阅方自动跟随，无需重新订阅

#### Scenario: 释放会话

- **WHEN** 用户释放会话
- **THEN** 管理器等待该会话运行收尾后将其从活动集合移除，其文件与历史保留，可再次恢复

#### Scenario: 继续最近会话

- **WHEN** 用户请求继续最近会话
- **THEN** 最近有活动的会话恢复为当前会话；无会话时创建新会话

#### Scenario: 关闭等待收尾

- **WHEN** 应用关闭且存在活动运行
- **THEN** 管理器等待运行终态和共享资源关闭完成后返回，不留下可观测的后台运行任务

## ADDED Requirements

### Requirement: 会话运行终态与错误分类

会话一次运行 SHALL 暴露可观察的阶段和最终结果。阶段至少包括 `idle`、`starting`、`model_wait`、`tool_running`、`awaiting_confirmation`、`continuing`、`completed`、`failed`、`cancelled` 和 `finalizing`。失败结果 SHALL 包含稳定错误码、发生阶段、可重试性、副作用状态和清理确定性；人类可读错误文本不得作为调用方判断错误类别的唯一依据。

#### Scenario: 正常完成

- **WHEN** 模型完成最终回复且本轮收尾成功
- **THEN** 运行从执行阶段进入 `completed`，并在完成最终收尾后回到 `idle`

#### Scenario: 结构化失败

- **WHEN** 模型、工具、确认、递归限制或持久化环节失败
- **THEN** 运行进入 `failed`，错误事件包含稳定 `error_code`、`phase`、`retryable`、`side_effect_state` 和 `cleanup_uncertain`

#### Scenario: 取消终态

- **WHEN** 调用方请求取消并且运行完成取消传播与资源收尾
- **THEN** 运行进入 `cancelled`，取消事件包含该运行的关联标识和清理结果

#### Scenario: 终态前完成收尾

- **WHEN** 运行已经得到成功、失败或取消结果
- **THEN** session 在发布最终终态前完成消息提交或回滚、usage 处理和运行资源收尾
