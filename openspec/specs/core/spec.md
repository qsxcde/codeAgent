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



### Requirement: 系统提示词注入

模型端口收到的消息列表 SHALL 以 system 消息起始;system 内容 SHALL 由基础提示词与分层上下文文件(AGENTS.md 等)合并而成;上下文文件 SHALL 按 全局 → 项目 → 子目录 分层加载,越接近工作目录的层级优先级越高(合并顺序越靠后);每个上下文文件的内容 SHALL 携带其来源路径标注,使模型与订阅方可追溯指令出处;加载结果 SHALL 可查询(来源文件列表),供展示与断言。

#### Scenario: 首条 system 消息

- **WHEN** 模型端口生成请求
- **THEN** 消息列表首条为 system 消息,内容包含基础提示词与合并后的分层上下文

#### Scenario: 分层合并与优先级

- **WHEN** 全局 / 项目 / 子目录均存在上下文文件
- **THEN** 全部按 全局 → 根 → … → 工作目录 的顺序合并;每个文件内容以来源路径标注;越近工作目录的文件在合并结果中越靠后(优先级越高)

#### Scenario: 候选文件名与去重

- **WHEN** 同一目录存在多个候选文件(如 AGENTS.md 与 CLAUDE.md)
- **THEN** 按候选优先级取第一个(AGENTS.override.md > AGENTS.md > CLAUDE.md);同一文件不重复注入

#### Scenario: 加载结果可见

- **WHEN** 订阅方/用户查询上下文加载结果
- **THEN** 返回本次加载的上下文文件来源列表(绝对路径),可展示可断言

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
