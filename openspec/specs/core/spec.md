# core Specification

## Purpose

定义 Agent 编排执行能力:自研 ReAct 循环驱动“模型→工具→继续/结束”,以事件流对外暴露执行过程,消息归约与控制流由自研代码保证,不依赖外部编排框架。

## Requirements

### Requirement: ReAct 循环执行

Agent Runtime SHALL 以纯内存循环执行“模型响应→工具执行→继续或结束”:模型产出无工具调用的最终消息后结束;模型产出工具调用时,系统 SHALL 执行工具、将结果按调用顺序加入当前 Agent 上下文并继续请求模型;循环 SHALL 有最大轮数上限。模型适配器 SHALL 在进入 core 前将 provider 原始流事件和工具参数转换为 core 统一形状,core 不直接解析 provider 协议。每次模型请求 SHALL 在最终临时上下文准备完成后、调用模型前执行上下文预算前置判定；判定阻断时不得进入模型或工具副作用路径。

#### Scenario: 直接回复结束循环

- **WHEN** 模型首轮产出无工具调用的回复
- **THEN** 该回复作为最终 Agent 消息,循环结束并返回本轮新增消息

#### Scenario: 工具调用后继续循环

- **WHEN** 模型产出带有合法参数的工具调用
- **THEN** 工具被执行、结果按 tool_call_id 加入 Agent 上下文,循环继续调用模型

#### Scenario: 工具参数解析失败

- **WHEN** 模型适配器向 core 提供参数错误的工具调用
- **THEN** 真实工具不得执行,该调用产生带工具名、调用 id 和错误原因的结果并入上下文,循环允许模型重新生成调用

#### Scenario: 循环上限

- **WHEN** 模型连续调用工具达到循环上限
- **THEN** Agent Runtime 中止本轮并返回可识别的循环超限错误,不进入死循环

#### Scenario: 从已有上下文继续

- **WHEN** 调用方从最后一条 user 或 tool result 消息继续执行
- **THEN** Agent Runtime 不重复追加原始 user 消息,直接从已有上下文开始下一轮模型调用

#### Scenario: 请求前预算阻断

- **WHEN** 最终模型上下文被预算前置判定为超限或不确定策略要求阻断
- **THEN** Agent Runtime 在调用模型前发布结构化预算错误并结束本轮,不执行新的工具调用

### Requirement: 结构化工具结果传递

Agent Runtime SHALL 在工具执行归一化后保留治理结果的结构化事实,并同时提供有界模型文本、工具结果事件和会话提交所需的元数据。结果状态、截断事实和语义字段 SHALL 不依赖解析 `content`;同批工具结果 SHALL 继续按原始调用顺序回填模型。

#### Scenario: 适配器结果字段不丢失

- **WHEN** AgentTool 适配器返回带有输出统计、截断原因、退出码或变更摘要的结果
- **THEN** Runtime 归一化后仍保留这些字段,并补齐工具调用 id、工具名、执行状态和清理状态

#### Scenario: 事件传播治理事实

- **WHEN** 工具执行结束
- **THEN** `TOOL_FINISHED` 和 `TOOL_RESULT` 事件携带同一份结构化结果事实,订阅方无需读取或解析结果文本即可判断完整性、错误、退出码和输出范围

#### Scenario: 模型只接收受控文本

- **WHEN** 工具结果追加到下一次模型上下文
- **THEN** tool message 使用治理后的有界文本,展示元数据和内部运行对象不被隐式注入模型,工具结果的调用归属和回填顺序保持不变

#### Scenario: 并行结果事实与顺序一致

- **WHEN** 同一批工具并行完成且返回顺序不同
- **THEN** 每个结果的结构化事实仍按 tool_call_id 归属,事件可反映真实完成顺序,模型消息按原始调用顺序排列

#### Scenario: 治理失败不伪造成功

- **WHEN** 结果归一化或治理阶段无法确定完整性、摘要或原始输出状态
- **THEN** Runtime 返回结构化的失败/不确定结果,不得把缺失元数据或未验证的文本标记为完整成功

### Requirement: 消息归约

Agent Runtime SHALL 维护有序的内存消息列表:工具结果 SHALL 按 tool_call_id 关联到对应工具调用;消息 SHALL 具备运行期唯一 id;每次运行 SHALL 在独立的工作消息列表中归约新增消息,只有运行成功且 session 提交边界完成后才可合并到会话历史。执行失败或取消时,调用方 SHALL 能丢弃本轮全部新增消息而保留此前上下文。持久化父子关系、分支记录和压缩记录 SHALL 由 session 层负责,不成为 core 消息模型的应用依赖。

#### Scenario: 工具结果按调用归属

- **WHEN** 一个模型回复携带多个工具调用且工具并行完成
- **THEN** 每个工具结果按 tool_call_id 归属,向模型提交的结果顺序与原始调用顺序一致,成功与失败结果互不污染

#### Scenario: 失败回滚

- **WHEN** Agent Runtime 本轮执行失败或被取消
- **THEN** 本轮新增消息可从内存上下文移除,此前上下文保持完整,session 层可以据此决定是否持久化

#### Scenario: 消息 id 稳定有序

- **WHEN** Agent Runtime 创建 user、assistant 或 tool result 消息
- **THEN** 每条消息带有唯一 id,可供工具结果归属、事件关联和上层持久化引用

#### Scenario: 提交边界隔离

- **WHEN** Agent 已产生新增消息但 session 尚未完成持久化提交
- **THEN** 新增消息不会被视为已提交历史;提交失败时可以完整丢弃,不影响此前已持久化上下文

### Requirement: 工具执行确认

Agent Runtime SHALL 在每个工具调用执行前提供通用的 `before_tool_call` 决策点;决策方可以允许执行、阻止执行并提供原因,或要求上层交互完成确认后再决定。core SHALL 不读取安全配置、不实现具体审批策略,被阻止的调用 SHALL 以错误结果回填且不得产生工具副作用。

#### Scenario: 允许执行

- **WHEN** `before_tool_call` 返回允许
- **THEN** 工具正常执行,结果照常回填 Agent 上下文

#### Scenario: 扩展阻止执行

- **WHEN** `before_tool_call` 返回阻止及原因
- **THEN** 工具不得执行,该调用以失败结果回填并携带阻止原因

#### Scenario: 需确认后批准

- **WHEN** 上层确认适配器将需要确认的调用判定为允许
- **THEN** core 收到允许决策并执行工具,结果照常回填

#### Scenario: 需确认后拒绝

- **WHEN** 上层确认适配器将需要确认的调用判定为拒绝
- **THEN** core 收到阻止决策,工具不执行,调用以失败结果回填并携带拒绝原因

#### Scenario: 策略拒绝

- **WHEN** 上层安全策略在 before_tool_call 阶段直接阻止调用
- **THEN** 工具不执行,调用以失败结果回填并携带策略原因

#### Scenario: 交互确认由上层完成

- **WHEN** 扩展需要用户确认才能决定是否执行
- **THEN** session/app 层负责等待用户响应并向 hook 提供最终决策,core 不直接依赖确认队列或 TUI/headless 配置

### Requirement: 事件契约

Agent Runtime SHALL 以结构化事件暴露 Agent、turn、message、模型流和工具执行生命周期；核心事件至少包括 `agent_start`、`agent_end`、`turn_start`、`turn_end`、`message_start`、`message_update`、`message_end`、`tool_execution_queued`、`tool_execution_start`、`tool_execution_update`、`tool_execution_end`、`usage`、`context_budget`、`context_preflight`、`error` 和 `aborted`。每个属于一次运行的事件 SHALL 携带稳定的 `run_id`；工具生命周期事件 SHALL 携带 `tool_call_id`、`operation_id` 和工具名，并在 session 适配边界补充 `session_id`。事件 SHALL 能区分排队、执行中、过程更新和唯一终态，且订阅方无需解析错误文本判断工具状态、清理状态或输出完整性。Session started、restore、compaction、persistence 和 confirmation 等事件 SHALL 由 session/app 层定义或适配，不再作为 core Agent 事件的职责。

#### Scenario: Agent 生命周期可订阅

- **WHEN** 一次 Agent prompt 或 continue 开始并完成
- **THEN** 订阅方依次可感知 Agent 开始、turn、消息生命周期和 Agent 结束事件

#### Scenario: 流式输出可订阅

- **WHEN** 模型产生文本、thinking 或工具参数增量
- **THEN** 订阅方收到对应的结构化 message update，无需等待最终回复

#### Scenario: 工具生命周期可订阅

- **WHEN** 工具调用进入执行批次并等待并发槽位、确认决策或实际开始执行
- **THEN** 订阅方分别收到带同一 `tool_call_id` 和 `operation_id` 的排队、开始或等待确认相关事件；开始事件只表示实际执行已经获得许可并占用执行槽位，完成时再收到对应终态事件

#### Scenario: 工具进度与终态可订阅

- **WHEN** 工具产生进度、正常完成、失败、超时、取消或清理不确定收尾
- **THEN** 订阅方收到带稳定调用归属、机器可读状态、耗时、错误和清理诊断的更新及终态事件；每个调用最多有一个终态

#### Scenario: 执行进度可订阅

- **WHEN** Agent 执行模型请求或工具调用
- **THEN** 订阅方可通过 Agent 生命周期事件感知文本、thinking、工具调用和工具结果进度,无需等待最终返回值

#### Scenario: 预算判定可订阅

- **WHEN** Agent 准备一次模型请求并完成预算前置判定
- **THEN** 订阅方收到包含判定状态、输入估算、输入预算、余量和窗口来源的 `context_preflight` 事件

#### Scenario: 失败与取消语义

- **WHEN** Agent 执行失败或收到取消信号
- **THEN** core 发出结构化 error 或 aborted 事件，由 session 层决定回滚和持久化；已经进入执行的工具调用仍通过工具终态事件报告取消和清理事实

#### Scenario: 确认请求可订阅

- **WHEN** 上层安全适配器需要用户确认工具调用
- **THEN** session/app 层发出 `confirmation_requested` 事件并将最终 allow/block 决策回传 hook，core 不直接管理确认队列

#### Scenario: 工具状态可诊断

- **WHEN** 工具因参数错误、超时、取消、拒绝或清理未确认而结束
- **THEN** 工具事件和结果携带稳定状态、operation id、清理状态和可用的输出完整性信息，订阅方无需解析错误文本

#### Scenario: 并发事件按调用归属

- **WHEN** 同一批工具并行执行且完成事件以不同顺序到达
- **THEN** 每个事件按 `tool_call_id` 和 `operation_id` 归属到原始调用；事件到达顺序不改变模型结果按原始调用顺序回填的语义

#### Scenario: Session 事件由上层适配

- **WHEN** session 层需要广播会话创建、恢复、压缩或确认状态
- **THEN** session/app 层将 Agent 事件转换或补充为 Session 事件，core Agent Runtime 不引入持久化或 UI 生命周期

#### Scenario: 运行终态唯一

- **WHEN** 一个运行进入 completed、failed 或 cancelled 任一终态
- **THEN** 该运行只发布一次终态，终态之后不再发布属于该运行的普通过程事件；已经发布的工具终态不得因重复结果事件被改写

### Requirement: 受控工具执行

工具调用 SHALL 只能经统一的 `AgentTool.execute(...)` 协议运行,执行器不得根据 `Args`、`invoke`、`ainvoke`、`invoke_async` 或 `args_schema` 等具体工具实现属性选择兼容路径。执行器 SHALL 支持可配置的并行或串行模式、运行期并发上限、超时、取消和进度更新。系统 SHALL 保持同一批工具结果向模型回填时的调用顺序;达到并发上限的调用 SHALL 等待;取消或超时 SHALL 触发工具清理,并明确报告清理已确认、清理失败或清理不确定的状态。对于无法抢占的同步工具,执行器 SHALL 不得把停止等待误报为工具已经终止。具体工具的旧输入 schema 和同步/异步执行方式 SHALL 在进入 core 前由 tools 或组合根适配为 `AgentTool`。

#### Scenario: 并发上限

- **WHEN** 一批模型响应包含超过执行器并发上限的工具调用
- **THEN** 同时运行的工具数量不超过上限,其余调用排队,结果仍按原调用顺序回填

#### Scenario: 工具执行模式

- **WHEN** Agent 配置为 parallel 或 sequential,或单个工具声明覆盖模式
- **THEN** 执行器按有效模式运行,并在事件中保持真实完成顺序与回填顺序的语义可区分

#### Scenario: 严格 AgentTool 调用

- **WHEN** core 收到一个实现 `AgentTool` 的工具
- **THEN** 执行器只调用其 `execute(...)` 入口,并将返回结果按统一工具结果契约归一化,不读取具体工具类的旧 schema 或 invoke 方法

#### Scenario: 未适配的旧工具被拒绝

- **WHEN** 调用方把只提供 `Args`/`invoke` 或 `ainvoke` 而未实现 `AgentTool.execute(...)` 的工具传给 core
- **THEN** core 返回可诊断的工具契约错误或在装配边界拒绝该工具,不得隐式选择旧兼容路径执行

#### Scenario: 工具超时

- **WHEN** 工具执行超过配置的超时时间
- **THEN** 工具被标记为 timed_out,执行器触发清理并向模型回填错误结果;若无法强制终止,结果 SHALL 标记清理未确认

#### Scenario: 运行中止

- **WHEN** Agent 收到取消信号且工具正在执行
- **THEN** 工具收到取消信号并进入清理流程,未完成调用不得继续占用执行器槽位

#### Scenario: 单工具失败不影响同批调用

- **WHEN** 同一批工具中一个调用参数错误、超时或执行失败
- **THEN** 该调用回填独立错误结果,其它调用按执行策略继续或完成,错误不得污染其它 tool_call_id

#### Scenario: 清理结果可验证

- **WHEN** 工具清理接口执行成功、失败或不受支持
- **THEN** 工具结果和执行事件分别标记对应清理状态,调用方能够区分 confirmed、failed、uncertain 和 unsupported

### Requirement: 运行干预

Agent Runtime SHALL 支持 prompt、continue、abort、steer 和 follow-up 五类运行控制。steer 消息 SHALL 在当前工具批次结束后、下一次模型请求前注入;follow-up 消息 SHALL 仅在当前 Agent 判断本轮完成后启动新的 turn;continue SHALL 从已有 user 或 tool result 上下文恢复,不得重复添加 prompt。abort SHALL 先发出取消请求,再等待模型、工具和确认等待点完成取消传播与清理;只有收尾完成后,运行才可报告为 cancelled。

#### Scenario: 中断

- **WHEN** 调用方请求 abort
- **THEN** 当前模型或工具操作收到取消信号,Agent 发出 aborted/error 收尾事件,调用方可继续使用该上下文

#### Scenario: steer 注入

- **WHEN** Agent 运行期间收到 steer 消息
- **THEN** 当前工具批次完成后消息被追加到内存上下文,下一次模型请求优先处理该消息

#### Scenario: follow-up 排队

- **WHEN** Agent 已完成当前工具链且存在 follow-up 消息
- **THEN** follow-up 被作为新的 user 消息启动后续 turn,不会与当前工具链交错

#### Scenario: continue

- **WHEN** 调用方调用 continue 且上下文最后一条消息是 user 或 tool result
- **THEN** Agent 从该上下文继续执行;若最后一条是 assistant,调用被拒绝并返回明确错误

#### Scenario: 追问与注入

- **WHEN** 调用方提交 follow-up 或 steer 消息
- **THEN** follow-up 在当前 Agent 完成后启动新 turn,steer 在当前工具批次结束后于下一次模型请求前注入

#### Scenario: 取消时排队请求收尾

- **WHEN** 运行在处理 follow-up 或等待 steer 注入时被取消
- **THEN** 所有排队请求得到明确的取消结果或异常,不留下悬挂 Future,也不启动新的 turn

### Requirement: Agent Runtime 扩展钩子

Agent Runtime SHALL 在每次模型请求前提供 `transform_context` 上下文转换点,并在工具执行前后提供 `before_tool_call`、`after_tool_call` 钩子;扩展可以修改本次模型可见上下文、阻止或修饰工具结果,但不得直接依赖 AI provider、Session 存储、MCP 客户端或 Skill 文件格式。对于需要预算信息的上下文扩展,Runtime SHALL 提供与 provider、session 和工具实现解耦的请求预算视图;扩展返回的上下文 SHALL 只作用于当前请求,不得改写持久化历史。已有只接收消息列表的 `transform_context` 扩展 SHALL 继续可用。扩展异常 SHALL 产生可诊断的 Agent 错误并遵循取消与回滚语义。

#### Scenario: 上下文扩展

- **WHEN** 注册了 `transform_context` 扩展
- **THEN** 每次模型请求前扩展可以基于当前消息生成模型可见上下文,而不修改 session 持久化的原始消息

#### Scenario: 预算感知上下文扩展

- **WHEN** 注册了需要预算信息的上下文扩展
- **THEN** 扩展收到中立的请求预算视图并可以生成当前请求的临时上下文,不得要求 core 直接提供 provider、session、MCP 或 Skill 具体实现

#### Scenario: 工具前置拦截

- **WHEN** `before_tool_call` 扩展阻止某个调用
- **THEN** 该调用不执行并生成结构化错误结果,同批其它调用按正常策略处理

#### Scenario: 工具结果后处理

- **WHEN** `after_tool_call` 扩展修改工具结果或声明终止后续模型请求
- **THEN** Agent 使用修改后的结果完成当前 turn,并按终止决策决定是否继续下一次模型请求

#### Scenario: 扩展异常

- **WHEN** 上下文或工具扩展抛出异常
- **THEN** Agent 发出带错误类型和阶段信息的错误事件,调用方可以回滚本轮且不得静默继续执行

#### Scenario: 预算计算失败

- **WHEN** 预算感知扩展无法解析请求组成或收到不确定的模型窗口
- **THEN** Runtime 发出带阶段和不确定性信息的诊断错误或受控结果,不得把未确认的预算当作精确值继续发送请求
