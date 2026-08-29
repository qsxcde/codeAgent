## MODIFIED Requirements

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
