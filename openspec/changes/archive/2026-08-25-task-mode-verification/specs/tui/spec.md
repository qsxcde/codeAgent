## ADDED Requirements

### Requirement: 模式命令和当前模式展示

TUI SHALL 支持 `/ask`、`/plan`、`/code` 和 `/mode <ask|plan|code|auto>` 命令，并在输入区或底部状态栏显示当前模式。模式拒绝工具写入时，TUI SHALL 显示简洁原因和可执行的切换提示，不展示技能或工具的原始 Markdown。

#### Scenario: 切换模式

- **WHEN** 用户输入 `/mode plan`
- **THEN** TUI 更新当前模式标记为 `plan`，后续普通消息使用该模式

#### Scenario: 单次模式命令

- **WHEN** 用户输入 `/ask 解释这个函数`
- **THEN** TUI 以问答模式发送该消息，完成后恢复之前的粘性模式

### Requirement: 任务验证状态栏

任务进入验证或修复阶段时，TUI SHALL 在底部状态栏显示当前阶段、验证命令、尝试次数和耗时；状态栏 SHALL 显示 `verified`、`unverified`、`failed`、`cancelled` 或 `no_changes` 的简洁终态摘要。长命令 SHALL 截断显示，完整诊断可在可展开的任务详情中查看。

#### Scenario: 显示验证进度

- **WHEN** 代码修改后正在执行第 1 次验证
- **THEN** 状态栏显示类似“验证中 · 第 1/2 次 · pytest · 00:04”的信息

#### Scenario: 无变更结果

- **WHEN** Agent 只读取文件并结束回合
- **THEN** TUI 显示 `no_changes` 或普通空闲状态，不显示测试运行中的活动提示

#### Scenario: 验证失败结果

- **WHEN** 验证命令失败且修复次数已耗尽
- **THEN** TUI 显示 `failed`、失败命令和简短错误尾部，并保持输入可用

### Requirement: 任务级打断

TUI 在任务处于验证或修复阶段时 SHALL 将 Esc 绑定到整个任务取消，而不仅是取消当前 Agent 回合；取消完成后 SHALL 停止活动提示、释放输入锁定并渲染 `cancelled` 结果。

#### Scenario: 验证期间按 Esc

- **WHEN** 用户在验证命令运行期间按 Esc
- **THEN** 命令、Agent 回合和后续修复均被取消，TUI 恢复可输入
