## Why

v0.1 的编排层依赖 langgraph(InMemorySaver + CompiledGraph + astream 翻译层),带来三重成本:会话持久化无法与"消息即状态"合一(重启即失忆)、steer/followup 等干预能力受限于图模型、10 类事件要经翻译层间接产出。三个蓝图未决问题已于 2026-08-14 评估:**平台部署非刚需**(可放弃 langgraph 生态,langgraph.json 改写为 HTTP/事件订阅并入 F-27)、**消息归约 spike 为正确性 gate**(且源码核实 add_messages 不做"插入归属",归约实际靠写入顺序)、**JSONL 树形为格式结论**(对齐 Pi)。本 change 按演进蓝图第二步自研编排,让"自研循环 + JSONL 会话"成为 v0.2 会话层(可恢复/可切换/可压缩)的地基。

## What Changes

- **自研 ReAct 主循环**(`core/loop.py` 重写):for 循环(模型→工具→继续/结束),10 类 AgentEvent 直接 emit,翻译层消失;thinking/usage 事件原生化;recursion_limit / abort / 工具超时均为普通代码。**BREAKING**:`build_graph` 返回类型不再是 CompiledGraph,`AgentPorts` 结构变化。
- **消息归约 R2**:按 `tool_call_id` 归属工具结果(写入顺序保证,~15 行平凡逻辑)+ RemoveMessage 等价(失败回滚 / compaction)+ 消息 id 稳定(**uuid7**,时间有序,对齐 Pi 的 `uuidv7` 并服务 JSONL 树形排序);删除 `core/state.py`(add_messages)与 `core/nodes/`(agent/tools 节点并入循环)。
- **JSONL 树形会话文件**(`session/store.py`):一个会话一个 JSONL 文件(append-only);entry 类型 `session header`(含 `parentSession`)/ `message`(含 `id`/`parentId`)/ `compaction`(预留 `summary` + `details.readFiles/modifiedFiles`,服务 T-37 undo 与 T-32 压缩);版本号策略;内存/文件后端注入(hexagonal 缝,复用 `with_path_lock`)。
- **删除编排桥接层**:`ai/bridge/langchain.py` 整文件删除(314 行),`ChatClient` 协议直接对接自研循环。**BREAKING**:外部 `to_langchain_runnable` / `to_langchain_ai_message` 消失。
- **工具层适配**:`tools/base.py` 删除 `to_langchain()`(自研工具直接可调用),`tools/registry.py` 返回自研工具列表(不再 BaseTool)。**BREAKING**:`make_tools` 返回类型变化。
- **组合根重装配**:`app/container.py` 注入自研端口(模型 / 工具执行器 / 会话存储),删除 ToolNode / InMemorySaver。
- **依赖移除**:pyproject 移除 `langchain-core` / `langgraph`(保留 httpx / pydantic / textual)。**BREAKING**。
- **测试重写**:删除 `tests/ai/test_bridge.py`(整文件);`test_loop` / `test_session` / `test_container` 从"图输出"断言改为"事件序列"断言;`test_factory` 小改。事件契约(10 类 AgentEvent)冻结,TUI/CLI 测试无感知。
- **文档勘误**:`core/state.py` docstring 与 CLAUDE.md 中"add_messages 同 role 相邻合并"的说法不实(源码核实),随重写修正。

## Capabilities

### New Capabilities

- `core`:Agent 编排执行能力——自研 ReAct 循环、消息归约(按 tool_call_id 归属、删除语义、id 稳定)、事件契约(10 类 AgentEvent)、控制流(recursion_limit / abort / 超时)。
- `sessions`:会话持久化能力——JSONL 树形会话文件(append-only、parentId/parentSession)、重启恢复、格式版本策略、compaction entry 预留。

### Modified Capabilities

(无——工具与 TUI 的行为契约不变,仅内部绑定机制变化,不属 spec 级行为变更)

## Impact

- **代码**:`core/loop.py`、`core/state.py`、`core/nodes/`(删)、`core/ports.py`、`session/session.py`、`session/store.py`(新)、`ai/bridge/langchain.py`(删)、`tools/base.py`、`tools/registry.py`、`app/container.py`;`session/bus.py`、`core/events.py` 不变。
- **测试**:约 1,700 行重写/删除(6 个文件);新增 spike 双跑 diff 基线与 JSONL 存储测试。
- **依赖**:移除 langchain-core、langgraph;运行时依赖收敛为 httpx / pydantic / textual。
- **平台**:`langgraph.json` 永久调整——不再依赖 LangGraph 平台;F-24 改写为 HTTP/事件订阅入口(并入 F-27)。
- **文档**:演进蓝图第二步落地;v0.2 任务书阶段 1(T-30~T-34);`core/state.py` 与 CLAUDE.md 的归约描述勘误。
