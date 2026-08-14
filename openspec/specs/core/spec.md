# core Specification

## Purpose

定义 Agent 编排执行能力:自研 ReAct 循环驱动"模型→工具→继续/结束",以事件流对外暴露执行过程,消息归约与控制流由自研代码保证,不依赖外部编排框架。

## Requirements

### Requirement: ReAct 循环执行

一轮对话 SHALL 以循环方式执行:先调用模型,若模型请求工具则执行工具并把结果并入消息历史后再次调用模型,直到模型产出无工具调用的最终回复;循环 SHALL 有最大轮数上限。

#### Scenario: 直接回复结束循环

- **WHEN** 模型首轮产出无工具调用的回复
- **THEN** 该回复作为最终回复,循环结束

#### Scenario: 工具调用后继续循环

- **WHEN** 模型产出带工具调用的回复
- **THEN** 工具被执行、结果并入消息历史,循环继续调用模型

#### Scenario: 循环上限

- **WHEN** 模型连续调用工具达到循环上限
- **THEN** 本轮中止并以友好提示结束,不进入死循环

### Requirement: 消息归约

消息历史 SHALL 维护为有序消息列表:工具结果 SHALL 归属到对应工具调用之后;消息 SHALL 具备全局唯一、时间有序的 id;运行失败或被取消时 SHALL 能把本轮新增消息从历史中移除(回滚)。

#### Scenario: 工具结果按调用归属

- **WHEN** 一个模型回复携带多个工具调用(含并行执行),结果以任意顺序返回
- **THEN** 每个工具结果按 tool_call_id 归属到对应调用之后,成功与失败结果互不污染

#### Scenario: 失败回滚

- **WHEN** 本轮执行失败或被用户取消
- **THEN** 本轮新增的消息从历史中移除,历史上下文保持完整,会话可继续

#### Scenario: 消息 id 稳定有序

- **WHEN** 消息被写入历史
- **THEN** 每条消息带有全局唯一且随时间有序的 id,供后续按 id 引用(删除/归属/恢复)

### Requirement: 事件契约

执行过程 SHALL 以事件流对外暴露,事件类型与既有契约一致(10 类):`session_started / text_delta / thinking_delta / agent_message / tool_call / tool_result / turn_end / error / run_cancelled / usage`;执行失败时 SHALL 先回滚再发 `error`;被取消时 SHALL 发 `run_cancelled`。

#### Scenario: 执行进度可订阅

- **WHEN** 一轮对话执行中
- **THEN** 订阅方按既有事件类型感知进度(文本增量、思考增量、工具调用与结果、用量),无需等待最终返回值

#### Scenario: 失败与取消语义

- **WHEN** 执行失败
- **THEN** 本轮消息已回滚,且订阅方收到 `error` 事件
- **WHEN** 执行被取消
- **THEN** 本轮消息已回滚,且订阅方收到 `run_cancelled` 事件

### Requirement: 运行干预

运行中 SHALL 可中断当前执行;执行结束后 SHALL 可发起追问轮;运行中 SHALL 可注入待处理消息(下一轮循环前消费)。

#### Scenario: 中断

- **WHEN** 用户请求中断当前执行
- **THEN** 执行中止,事件契约按取消语义收尾,会话可继续

#### Scenario: 追问与注入

- **WHEN** 用户请求追问一轮
- **THEN** 在既有消息历史后追加一轮新对话
- **WHEN** 用户运行中注入消息
- **THEN** 注入消息在下一轮循环开始时被消费
