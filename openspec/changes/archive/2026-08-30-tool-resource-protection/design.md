## Context

当前 `ToolExecutionRuntime` 已有并发信号量，`ProcessRequest` 已有输出字节/行限制，Bash 和进程后端也已有超时及进程树清理；但限制值分散且 Bash/原子工具不能共享配置。详见 proposal.md。

## Goals / Non-Goals

**Goals:**

- 建立 frozen `ToolResourceLimits`，集中校验资源边界并保留现有默认值。
- 在组合根解析限制并传入 runtime、原子工具和 ProcessRunner；测试可直接注入对象，不依赖环境变量或真实网络。
- 让进程预览物化严格受有效内存上限约束，清理等待使用有限超时并产生结构化不确定状态。

**Non-Goals:**

- 不改变工具安全分类、输出治理字段、搜索语义或模型请求重试。
- 不保证限制底层任意外部进程的磁盘写入量；当前进程采集使用临时文件，内存上限约束返回预览物化。
- 不把资源模型放入 core；core 只继续消费 `ToolExecutionRuntime` 接口。

## Decisions

1. **限制模型放在 `tools/shared`。** 它描述工具基础设施资源，不属于 Agent 领域；原子工具和组合根都能使用，core 不反向依赖具体工具。
2. **组合根是唯一默认解析点。** `create_agent_config` 解析显式限制或配置对象，向 `make_tools` 与 `ToolExecutionRuntime` 传递同一实例；直接使用原子工具时仍可得到兼容默认值。
3. **有效输出上限取配置输出上限与内存上限的较小值。** 这样任何单次预览都不会超过可物化内存预算，同时保留原始总量和截断事实。
4. **清理等待采用请求级有限时限。** 取消/超时如果在时限内确认则保持 confirmed，否则返回 uncertain；不以取消等待任务代替清理，也不无限阻塞整个 session。
5. **配置字段使用明确命名和严格校验。** 通过 `tool_*` 属性读取，允许 Settings、SimpleNamespace 和显式对象复用；不读取秘密、不执行命令。

## Risks / Trade-offs

- [限制过小导致信息过早截断] → 默认保持现有值，结果携带总量、展示量和继续读取/诊断信息。
- [进程清理超时后资源仍存活] → 返回 cleanup uncertain，阻止调用方把结果当作安全完成；Windows 继续保留既有 best-effort 语义。
- [直接构造工具绕过组合根] → `AtomicTool` 和 `BashTool` 自带兼容默认限制，但生产入口仍由 composition 注入并测试一致性。

## Migration Plan

先加入资源对象及失败测试，再将现有固定常量替换为限制读取；默认配置不变，旧 `ProcessRequest` positional 调用继续有效。回滚只需去掉组合根注入和新参数，不涉及 JSONL 数据迁移。
