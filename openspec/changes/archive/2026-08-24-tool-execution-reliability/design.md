## Context

本变更涉及 `core`、原子工具、MCP、模型传输和组合根多个层面。当前 `run_turn()` 在流式路径中聚合工具参数并直接进入工具执行；工具执行通过 `asyncio.to_thread()` 兼容同步工具；bash 自身已有进程树超时清理，MCP 则通过独立后台事件循环桥接同步调用。模型热切换由组合根重新创建 ports，但现有端口没有统一的资源所有者。

既有事件类型、消息历史和 `AgentSession` 的回滚语义已经被 TUI、CLI 和测试消费。本变更必须保持事件类型兼容、保持成功轮次才落盘，并且不让 `core` 依赖具体的 AI、tools 或 app 实现。

## Goals / Non-Goals

**Goals:**

- 让非法工具参数成为可诊断、可回灌模型的工具错误，而不是静默空参数执行。
- 为工具执行提供统一的并发、超时、取消和清理状态。
- 让 bash 和 MCP 具备真实的取消路径，并对无法强制抢占的同步工具明确降级。
- 为模型客户端、MCP server 和工具集合建立显式、幂等的资源释放生命周期。
- 在不改变既有事件类型的前提下，让订阅方通过 metadata 获取稳定的执行状态。
- 通过离线测试覆盖解析失败、并发限制、取消、超时、热切换和资源清理。

**Non-Goals:**

- 不在本变更中实现“修改代码后自动测试和修复”的任务 Supervisor。
- 不增加 AST/LSP、Git checkpoint/undo、记忆、多智能体、Web/HTTP 或新的 Skill 能力。
- 不强求所有同步工具都能被硬终止；不可抢占工具必须显式报告清理不确定性。
- 不引入新的第三方执行框架或进程管理依赖。

## Decisions

### 1. 在 core 消息模型中记录参数错误，但不持久化原始参数

为 `ToolCall` 增加运行时可观察的参数错误字段，例如 `argument_error`，解析失败时仍创建一个规范化的工具调用，`args` 使用空对象以满足供应商消息格式，但该调用被标记为不可执行。原始参数只用于当前错误诊断，不写入会话文件，避免把截断内容或潜在敏感值重复持久化。

执行器看到 `argument_error` 后直接生成 `ToolResult(status="invalid_arguments")`，不调用实际工具。工具结果继续挂在该 assistant tool call 之后，下一轮模型可以看到错误并重试。

**选择原因：**保留消息链完整性，避免向 OpenAI 兼容供应商发送无法序列化的 tool call，同时让模型获得可修复的错误上下文。

**替代方案：**在 `_call_model()` 直接抛异常。该方案会触发整轮回滚，模型无法重试，而且 TUI 只能显示一次通用错误，因此不采用。

### 2. 统一流式和非流式参数解析

在组合根和 `core` 之间提供一个框架无关的参数解析函数或结果对象，统一处理：

- 空字符串 → 合法空对象；
- 合法 JSON 对象 → 正常参数；
- JSON 数组、字符串、数字 → 非对象参数错误；
- 截断或非法 JSON → 解析错误；
- 可选的 `finish_reason=length` → 在错误诊断中标记可能被截断。

流式路径和 `ChatModelPort.generate()` 必须使用同一语义，避免测试和真实调用在不同路径下表现不一致。

### 3. 用 ToolExecutionRuntime 管理并发和生命周期

在 `core` 内新增面向端口的执行器抽象，建议职责如下：

```text
ToolExecutionRuntime
├── execute(call)
├── max_concurrency
├── active_operations
├── cancel(operation_id)
├── timeout(operation_id)
└── cleanup(operation_id)
```

执行器只依赖工具的最小协议，不导入具体的 `BashTool`、MCP client 或 AI client。它负责：

- 使用 semaphore 限制并发；
- 保持调用顺序与结果顺序；
- 为每次调用分配 operation id；
- 将 `running/completed/failed/timed_out/cancelled/cleanup_uncertain` 转为稳定状态；
- 取消时优先调用工具提供的异步取消接口；
- 对只有同步 `invoke()` 的工具使用兼容降级路径。

现有 `_execute_tools()` 可以保留确认策略和结果排序逻辑，但将实际执行委托给该运行时。

**选择原因：**避免把超时、并发和资源清理继续堆积到 `core/loop.py`，也避免为每种工具复制一套生命周期逻辑。

**替代方案：**只在 `_execute_one()` 外层增加更多 `wait_for()`。这只能停止等待，无法终止底层同步工作，也无法跟踪清理状态，因此不采用。

### 4. Bash 使用原生可取消执行路径，同步路径保留兼容

Bash 当前已经有 Unix 进程组和 Windows `taskkill /T` 清理逻辑。新增的异步执行入口应持有进程句柄，并在超时/取消时复用同一进程树清理函数。现有同步 `_invoke()` 保留给直接工具调用和离线测试；Agent 执行器优先选择可取消入口。

Windows MSYS/Git Bash 派生孙进程无法完全确认清理时，结果状态必须为 `cleanup_uncertain`，不得伪装成普通 `timed_out` 完成。

### 5. MCP 暴露可取消的 Future/异步调用

现有 MCP client 通过 `run_coroutine_threadsafe(...).result(timeout)` 进行同步桥接。为支持真正取消，后台 loop 应保留对应的 concurrent Future 或提供异步提交接口，Agent 取消时调用 Future cancel，并等待后台 coroutine 收尾。

MCP server 的线程、事件循环和 stdio 子进程由一个显式资源对象持有，`close()` 必须幂等。初始化失败、热切换和 TUI 正常退出都走同一关闭路径，`atexit` 只做兜底。

### 6. 在组合根引入 AgentRuntime 资源所有者

保持现有 `AgentPorts` 的调用面兼容，在组合根新增运行时资源封装：

```text
AgentRuntime
├── ports: AgentPorts
├── model_client
├── mcp_clients
└── async close()
```

`create_agent_ports()` 可继续供现有测试和轻量调用使用；TUI、可持久化 CLI 和热切换流程使用带资源所有权的 runtime。替换 ports 时必须按以下顺序：

```text
停止当前运行
  → 等待旧任务进入 idle
  → 关闭旧 runtime
  → 创建新 runtime
  → 更新 SessionManager
```

关闭操作要在组合根或生命周期入口完成，`session` 层只接收可注入的关闭回调/协议，不直接依赖 AI 或 tools。

### 7. 扩展 metadata，不新增事件类型

继续使用现有 `tool_result`、`error` 和 `run_cancelled` 事件，在 metadata 中加入稳定字段：

```text
status: ok | invalid_arguments | failed | rejected |
        timed_out | cancelled | cleanup_uncertain
operation_id: string
cleanup_confirmed: bool
```

旧订阅方只读取已有字段时行为不变；新 TUI 可以根据 `status` 渲染状态，而不必解析中文错误文本。

### 8. 保持会话回滚边界

工具超时或参数错误但模型继续完成本轮时，该轮仍按成功轮次正常落盘，错误工具结果作为上下文的一部分保留。用户主动 abort、任务取消或运行级异常时，继续沿用现有 `AgentSession` 回滚路径：新增消息不落盘并发出 `run_cancelled` 或 `error`。

这一区分很重要：工具失败不是一定要回滚整轮，用户取消才需要回滚整轮。

## Risks / Trade-offs

- **[Risk]** 为 `ToolCall`/`ToolResult` 增加字段会影响 JSONL 往返与测试快照。  
  **Mitigation:** 新字段可选，旧会话缺失时使用默认值；不持久化原始参数，仅持久化稳定错误状态。

- **[Risk]** 原生异步 bash 路径可能与现有同步输出、Windows shell 发现逻辑产生差异。  
  **Mitigation:** 复用命令解析、环境白名单、临时文件和 `_kill_tree()`；保留同步路径作为回归对照，增加跨平台测试。

- **[Risk]** 对不可抢占同步工具报告 `cleanup_uncertain` 可能降低用户对“超时即停止”的直觉。  
  **Mitigation:** 在 TUI 和 headless 输出中明确说明状态，并逐步把高风险/长耗时工具迁移到可取消接口。

- **[Risk]** 热切换改为异步关闭可能改变现有同步 `/provider`、`/model` 命令调用方式。  
  **Mitigation:** 保留同步包装层；TUI 内部在事件循环中使用异步生命周期，旧 API 只在关闭可立即完成时同步返回。

- **[Risk]** 并发上限过低会降低多工具任务吞吐。  
  **Mitigation:** 默认采用小的有限上限并允许配置；读类工具可共享并发额度，写类工具继续依赖既有文件串行化。

- **[Risk]** MCP server 取消只取消客户端 coroutine，不一定能终止远端动作。  
  **Mitigation:** 区分“调用已取消”和“远端动作已停止”，保留明确状态；server 关闭时再执行连接级收尾。

## Migration Plan

1. 先增加兼容字段、状态枚举和统一参数解析测试，不改变正常合法调用路径。
2. 接入 `ToolExecutionRuntime`，默认并发上限保持与当前行为等价或设置为有限值；先覆盖普通同步工具。
3. 将 Bash 和 MCP 接入可取消执行入口，补充超时、取消和清理状态测试。
4. 在组合根引入 `AgentRuntime`，让 TUI 和热切换流程显式关闭旧资源。
5. 更新 TUI/CLI 对新 metadata 的展示和诊断。
6. 运行全量离线测试、MCP 测试、跨平台 bash 测试和资源泄漏回归。

回滚策略：

- 新增字段均保持可选，旧 JSONL 可继续读取；
- 执行器可以通过兼容适配器退回现有 `invoke()` 路径；
- 若原生异步 Bash/MCP 路径出现平台回归，可暂时保留同步路径，但必须继续报告 `cleanup_uncertain`，不得静默声称已清理。

## Open Questions

- 默认 `max_concurrency` 是否需要按工具类别配置，还是先使用单一全局上限？这不会改变外部契约，可在实现阶段根据基准测试确定。
- `operation_id` 是否需要跨会话持久化？当前设计只要求运行期诊断，后续如需审计可再扩展。
