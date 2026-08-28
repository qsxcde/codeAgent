## MODIFIED Requirements

### Requirement: 工具执行资源状态

工具实现 SHALL 向执行器提供可观察的执行状态，至少包含 running、completed、failed、timed_out、cancelled 和 cleanup_uncertain。状态不得依赖解析人类可读输出文本，并 SHALL 可用于事件 metadata 和测试断言。取消或超时后的清理状态 SHALL 反映实际可证明结果：只有工具及其受控资源均已确认停止时才能标记 cleanup_confirmed；清理接口失败、不支持、超时或平台无法确认派生资源时 SHALL 标记 cleanup_uncertain 或对应失败状态。

#### Scenario: 正常完成状态

- **WHEN** bash 命令正常退出且进程树已收尾
- **THEN** 执行结果状态为 completed，清理状态为 confirmed

#### Scenario: 清理不确定状态

- **WHEN** 命令超时或取消后平台无法确认所有派生进程已结束
- **THEN** 执行结果状态为 cleanup_uncertain，调用方得到明确诊断而不是普通成功结果

#### Scenario: 清理失败状态

- **WHEN** 工具提供清理接口但清理调用失败
- **THEN** 执行结果保留原始超时或取消事实，并额外标记 cleanup_uncertain，不能依据接口存在与否推断清理成功

#### Scenario: 同步工具不可抢占

- **WHEN** 同步工具在线程中执行且取消只能停止等待方
- **THEN** 工具结果明确标记清理不确定，执行器不得释放该状态对应的资源保证或允许安全自动重试
