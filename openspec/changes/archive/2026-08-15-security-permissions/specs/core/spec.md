## ADDED Requirements

### Requirement: 工具执行确认

每个工具调用在执行前 SHALL 经安全策略判定:允许(allow)、需确认(ask)或拒绝(deny);判定为需确认时 SHALL 发出确认请求并等待用户响应,**未确认不得执行**;判定为拒绝或用户拒绝时 SHALL 以失败结果回填消息历史,原因对模型可见;被拒绝的操作 SHALL 不产生任何副作用。

#### Scenario: 允许执行

- **WHEN** 策略判定工具调用为允许(如只读白名单命令)
- **THEN** 工具直接执行,无需确认

#### Scenario: 需确认后批准

- **WHEN** 策略判定工具调用需确认且用户批准
- **THEN** 工具正常执行,结果照常回填

#### Scenario: 需确认后拒绝

- **WHEN** 策略判定工具调用需确认且用户拒绝
- **THEN** 工具不执行,该调用以失败结果回填并携带拒绝原因

#### Scenario: 策略拒绝

- **WHEN** 策略判定工具调用为拒绝(如命中危险命令黑名单)
- **THEN** 工具不执行,该调用以失败结果回填并携带命中原因

## MODIFIED Requirements

### Requirement: 事件契约

执行过程 SHALL 以事件流对外暴露,事件类型与既有契约一致并增量扩展(11 类):`session_started / text_delta / thinking_delta / agent_message / tool_call / tool_result / turn_end / error / run_cancelled / usage / confirmation_requested`;执行失败时 SHALL 先回滚再发 `error`;被取消时 SHALL 发 `run_cancelled`;工具调用需用户确认时 SHALL 发 `confirmation_requested`(携带请求标识、工具、摘要与原因),订阅方据此呈现确认交互。

#### Scenario: 执行进度可订阅

- **WHEN** 一轮对话执行中
- **THEN** 订阅方按既有事件类型感知进度(文本增量、思考增量、工具调用与结果、用量),无需等待最终返回值

#### Scenario: 失败与取消语义

- **WHEN** 执行失败
- **THEN** 本轮消息已回滚,且订阅方收到 `error` 事件
- **WHEN** 执行被取消
- **THEN** 本轮消息已回滚,且订阅方收到 `run_cancelled` 事件

#### Scenario: 确认请求可订阅

- **WHEN** 工具调用需用户确认
- **THEN** 订阅方收到 `confirmation_requested` 事件,携带请求标识、工具名、摘要与确认原因;既有事件类型语义不变(契约只增不改)
