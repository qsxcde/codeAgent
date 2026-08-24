## 1. 协议与状态模型

- [x] 1.1 定义工具执行状态集合(`ok`、`invalid_arguments`、`failed`、`rejected`、`timed_out`、`cancelled`、`cleanup_uncertain`)及其兼容默认值
- [x] 1.2 扩展 `ToolCall` 记录运行时参数错误，保持旧 JSONL 会话读取兼容且不持久化原始非法参数
- [x] 1.3 扩展 `ToolResult` 与工具事件 metadata，统一暴露 status、operation_id 和 cleanup_confirmed
- [x] 1.4 为流式和非流式模型响应实现并接入统一工具参数解析，覆盖空对象、非对象、非法 JSON 与截断 JSON

## 2. Core 工具执行运行时

- [x] 2.1 新增框架无关的工具执行运行时协议，支持 operation id、活动操作登记、取消和清理回调
- [x] 2.2 实现受控并发调度，设置有限的默认 max_concurrency，并保持工具结果按调用顺序回填
- [x] 2.3 将 `_execute_tools()` 的确认、策略拒绝、参数错误和实际执行接入统一运行时
- [x] 2.4 统一 Agent 层 timeout、abort 和工具状态转换；同步不可抢占工具超时必须标记 cleanup_uncertain
- [x] 2.5 保持 `AgentSession` 现有回滚语义：工具失败可继续完成本轮，主动取消或运行异常不落盘未完成轮次
- [x] 2.6 增加 core 回归测试：非法参数不执行真实工具、并发上限、超时、取消、单工具失败隔离和 metadata 状态

## 3. Bash 可取消执行

- [x] 3.1 为 `BashTool` 增加 Agent 执行器可调用的异步/可取消入口，保留现有同步 `_invoke()` 兼容测试和直接调用
- [x] 3.2 复用现有 Unix 进程组与 Windows `taskkill /T` 清理逻辑，返回 cleanup_confirmed 或 cleanup_uncertain 状态
- [x] 3.3 统一 Bash 自身 timeout 与 Agent timeout 的优先级、提示文本和退出码语义
- [x] 3.4 增加 bash 超时、外层取消、进程树清理和 Windows/MSYS 降级行为测试

## 4. MCP 取消与资源生命周期

- [x] 4.1 为 MCP server client 增加可跟踪的异步提交/Future 句柄，支持调用取消后等待 coroutine 收尾
- [x] 4.2 更新 MCP 工具适配器，使超时/取消结果带 timed_out 或 cancelled 状态且不占用后台调用槽位
- [x] 4.3 使 MCP server、后台线程、事件循环和 stdio 子进程的 close() 幂等，并覆盖初始化失败清理
- [x] 4.4 增加 MCP 取消、超时、重复关闭、初始化失败和 server 子进程回收测试

## 5. 模型与运行时资源所有权

- [x] 5.1 在组合根增加 AgentRuntime 资源所有者，统一持有模型客户端、MCP clients 和 AgentPorts
- [x] 5.2 实现 runtime.close()，显式关闭 OpenAI 兼容 AsyncClient、MCP 工具和其它可关闭资源
- [x] 5.3 修改 provider/model/login 热切换：停止当前运行、等待 idle、关闭旧 runtime、创建并安装新 runtime
- [x] 5.4 修改 TUI 和可持久化 CLI 生命周期，在正常退出、异常退出和初始化失败时显式关闭 runtime
- [x] 5.5 保持 create_agent_ports() 的现有测试调用兼容，必要时提供无资源所有权的轻量适配路径
- [x] 5.6 增加资源生命周期回归测试：重复热切换、TUI 退出、重复 close、旧客户端关闭和 MCP 线程无泄漏

## 6. 订阅方与兼容性

- [x] 6.1 更新 headless CLI 和 TUI 工具结果展示，优先根据 status metadata 渲染，不解析中文错误文本
- [x] 6.2 保持既有事件类型、确认流程、消息父子关系和旧会话 JSONL 读取兼容
- [x] 6.3 更新相关 core/tools/mcp/session/container 测试断言，确保新增 metadata 不破坏旧订阅方

## 7. 验证与交付

- [x] 7.1 运行 core、tools、mcp、session、container 和 TUI 定向测试并修复回归
- [x] 7.2 运行全量离线测试，确认无新增失败、无未关闭 MCP 线程和无残留测试进程
- [x] 7.3 在可用平台执行 bash 进程树测试，并记录 Windows/MSYS 清理限制
- [x] 7.4 运行 OpenSpec 严格校验和补丁格式检查，核对 proposal/spec/design/tasks 与实现范围一致
