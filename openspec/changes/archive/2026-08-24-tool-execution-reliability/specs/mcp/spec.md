## MODIFIED Requirements

### Requirement: 外部工具接入

MCP server 的工具 SHALL 以 `mcp__<server>__<tool>` 命名接入工具列表,与内建工具(名称不含 `:` 前缀)不冲突;工具参数 SHALL 透传 server 声明的 JSON Schema 语义(server 自行校验);工具结果 SHALL 以文本回填,server 标记的错误 SHALL 以错误结果回填;MCP 工具调用 SHALL 复用既有执行超时保护,并 SHALL 支持 Agent 执行器发出的取消信号。超时或取消后,调用方 SHALL 等待或触发 MCP coroutine 的清理,不得把已取消调用继续作为可运行任务遗留。

#### Scenario: 工具命名带前缀

- **WHEN** server "github" 声明工具 "list_issues"
- **THEN** 接入的工具名为 `mcp__github__list_issues`,与内建工具名不冲突

#### Scenario: 调用成功回填文本

- **WHEN** 模型调用 MCP 工具且 server 正常返回
- **THEN** 工具结果以文本形式回填消息历史

#### Scenario: 调用错误回填错误

- **WHEN** server 返回错误或调用超时/崩溃
- **THEN** 该调用以错误结果回填,不中断本轮其余工具

#### Scenario: 调用取消

- **WHEN** Agent 运行被取消或 MCP 工具达到执行超时
- **THEN** 对应 MCP 调用被取消或进入明确的清理状态,工具结果标记 cancelled 或 timed_out,不得继续占用后台调用槽位

## ADDED Requirements

### Requirement: MCP server 资源生命周期

MCP server 客户端 SHALL 提供幂等的显式关闭能力。热切换工具集合、TUI 退出和运行时初始化失败收尾时 SHALL 关闭不再使用的 server 线程、事件循环和 stdio 子进程;进程退出钩子只能作为异常退出兜底,不能作为正常生命周期的唯一释放机制。

#### Scenario: 显式关闭 server

- **WHEN** MCP 工具集合被替换或运行时正常退出
- **THEN** 已加载 server 的后台线程、事件循环和 stdio 子进程均进入关闭流程

#### Scenario: 重复关闭

- **WHEN** 同一 MCP server 被关闭多次
- **THEN** 后续关闭调用幂等完成,不抛出未处理异常

#### Scenario: 初始化失败收尾

- **WHEN** server 启动或 tools/list 初始化失败
- **THEN** 已创建的线程、事件循环和子进程被清理,该 server 产生诊断并从工具列表跳过
