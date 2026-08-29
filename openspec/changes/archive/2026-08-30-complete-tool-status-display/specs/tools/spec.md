## MODIFIED Requirements

### Requirement: 工具执行资源状态

工具实现 SHALL 向执行器提供不依赖人类可读输出文本的结构化状态。执行状态至少 SHALL 区分 `running`、`completed`、`failed`、`rejected`、`timed_out` 和 `cancelled`；资源清理状态 SHALL 独立使用 `not_required`、`pending`、`confirmed`、`failed`、`uncertain` 或 `unsupported` 表示。结果输出的完整性 SHALL 独立提供 `complete`、`truncated`、`incomplete` 或 `unknown` 等结构化事实，并可同时携带总量、展示量、截断原因和继续读取/导出信息。新事件和新结果 SHALL 将正常成功规范化为 `completed`；现有持久化数据或订阅方中的 `ok` 与聚合 `cleanup_uncertain` 值 SHALL 可被兼容读取，但不得阻止调用方获得原始执行状态和独立清理状态。状态、清理和输出完整性字段 SHALL 可直接用于事件 metadata、TUI 展示和测试断言。

#### Scenario: 正常完成状态

- **WHEN** bash 命令正常退出且进程树已收尾
- **THEN** 执行结果状态为 `completed`，清理状态为 `not_required` 或 `confirmed`，输出完整性单独反映结果是否完整

#### Scenario: 超时与清理已确认

- **WHEN** 命令超过超时且执行器确认受控进程资源已经停止
- **THEN** 执行状态为 `timed_out`，清理状态为 `confirmed`，调用方不会将其展示或统计为普通成功

#### Scenario: 清理不确定状态

- **WHEN** 命令超时或被取消且平台无法确认所有派生资源已经停止
- **THEN** 执行状态保留 `timed_out` 或 `cancelled`，清理状态为 `uncertain` 或 `unsupported`，调用方得到明确的清理诊断而不是普通成功结果

#### Scenario: 清理失败状态

- **WHEN** 工具提供清理接口但清理调用失败
- **THEN** 结果保留原始失败、超时或取消事实，并额外标记清理状态为 `failed` 或 `uncertain`，不能依据接口存在与否推断清理成功

#### Scenario: 同步工具不可抢占

- **WHEN** 同步工具在线程中执行且取消只能停止等待方
- **THEN** 工具结果明确保留未确认清理状态，执行器不得释放该状态对应的资源保证或允许安全自动重试

#### Scenario: 结果截断不改变执行结论

- **WHEN** 工具成功、失败、超时或取消，但返回内容超过输出限制或只能保留部分内容
- **THEN** 执行状态和清理状态保持原值，输出完整性独立标记为 `truncated` 或 `incomplete`，并提供可用的总量、预览范围和继续读取/导出诊断

#### Scenario: 状态不依赖文本

- **WHEN** 工具返回相同文本但结构化执行状态、清理状态或输出元数据不同
- **THEN** 调用方依据结构化字段区分这些结果，不通过匹配错误提示、图标或人类可读摘要推断状态

#### Scenario: 旧结果兼容读取

- **WHEN** session 恢复只包含旧版 `ok` 或 `cleanup_uncertain` 状态而缺少新字段
- **THEN** 系统将其安全映射为可展示的完成或清理不确定状态，并将缺失的清理/输出完整性标记为未知，不阻塞会话恢复
