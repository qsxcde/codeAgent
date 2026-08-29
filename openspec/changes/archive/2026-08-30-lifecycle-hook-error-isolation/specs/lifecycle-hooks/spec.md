# lifecycle-hooks Delta Specification

## ADDED Requirements

### Requirement: Hook 异常诊断与隔离

生命周期 Hook、Hook 返回的异步结果以及为 Hook 构造脱离原始事件的快照时发生的普通异常 SHALL 被隔离，并以结构化运行期诊断记录暴露。诊断至少 SHALL 包含稳定的错误代码、Hook 身份或快照阶段标识、scope/phase（可确定时）、事件类型、run/session 关联、失败阶段、异常类型和消息。Hook 失败 SHALL 不改变其它 Hook 的调用、Agent 主循环、会话提交/回滚、取消收尾或资源清理语义；Hook 诊断 SHALL 不写入用户会话历史或持久化记录。取消异常 SHALL 继续遵循既有取消传播，不得被误报为 Hook 失败。

#### Scenario: 同步 Hook 失败仍继续运行

- **WHEN** 一个同步 Hook 在生命周期事件上抛出普通异常
- **THEN** 该异常被记录为可查询的结构化诊断，后续 Hook 仍按注册顺序收到事件，Agent 运行和最终状态不受影响

#### Scenario: 异步 Hook 失败仍完成收尾

- **WHEN** 一个异步 Hook 在等待期间抛出普通异常
- **THEN** 异常在运行期 Hook 任务收尾时被记录，Agent 或 Session 仍完成既有成功/失败/取消收尾，且不存在未回收的 Hook 任务

#### Scenario: 快照构造失败不穿透主流程

- **WHEN** 生命周期事件包含无法复制的负载或元数据，导致 Hook 快照构造失败
- **THEN** 系统记录快照阶段诊断、跳过该事件的 Hook 分发，并继续发布原有运行事件和执行主流程

#### Scenario: Session 诊断覆盖两侧 Hook

- **WHEN** core Hook 或 session Hook 失败
- **THEN** AgentSession 可查询带 scope、phase、事件类型和 session/run 关联的对应诊断；诊断不会出现在会话历史或 JSONL 记录中

#### Scenario: 取消不伪造 Hook 失败

- **WHEN** 运行取消时正在等待的异步 Hook 被取消
- **THEN** 取消按既有语义传播并完成任务清理，不把 `CancelledError` 记录为普通 Hook 异常
