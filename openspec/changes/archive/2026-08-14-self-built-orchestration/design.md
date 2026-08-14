## Context

现状(参见 proposal.md - Why):编排层由 langgraph 提供(InMemorySaver + CompiledGraph + astream 双通道翻译层),重启即失忆、干预能力受图模型限制。蓝图第二步规划自研。三未决问题已评估:**平台部署非刚需**、**消息归约 spike 为 gate**、**JSONL 树形为格式结论**。

关键源码核实(langgraph 1.2.10 `langgraph/graph/message.py`):`add_messages` 真实语义 = 按 id 去重/替换 + RemoveMessage 删除 + 其余 append——**不存在**"同 role 相邻合并"、**不存在**"工具结果按 tool_call_id 插入归属"。工具结果的正确顺序来自我们的写入顺序(ReAct 串行 + `gather` 保序)。这使 R2(消息归约)从"~30 行最关键"收缩为"~15 行平凡逻辑",并把 spike 的判据从"语义等价论证"改为"端到端双跑 diff"。

## Goals / Non-Goals

**Goals:**
- 自研 ReAct 主循环 + 消息归约替换 langgraph 编排,10 类 AgentEvent 事件契约冻结(TUI/CLI/测试无感知);
- JSONL 树形会话文件成为消息唯一真相,运行时无第二份状态(不做"langgraph 运行期 + JSONL 双写");
- 消息 id 采用 **uuid7**(时间有序,对齐 Pi 的 `uuidv7`,服务 JSONL 树形排序与按 id 删除/归属);
- pyproject 移除 langchain-core / langgraph,运行时依赖收敛为 httpx / pydantic / textual。

**Non-Goals:**
- 会话生命周期高层 API(SessionManager create/switch/dispose)、compaction 触发策略、会话列表入口 —— 属后续会话层 change(specs 仅在本 change 定义持久化格式与恢复基础);
- fork 分叉 UI —— 格式已预留 parentId/parentSession,v0.3 落地;
- 编排自研以外的任何行为变更(工具、TUI 行为契约不变)。

## Decisions

### D1:自研循环直接 emit 事件(翻译层消失)

```
现状:  graph.astream → (messages, updates) → _translate → AgentEvent
自研:  循环体内直接 emit(AgentEvent)         ← 蓝图收益 1
```
10 类事件序列与既有契约逐项一致(spike 双跑 diff 为 gate,见 D4);thinking/usage 从 transport 层原样透传,不再经消息对象间接挖取。

### D2:消息模型与 uuid7

自研 `Message`(dataclass:role/content/tool_calls/tool_call_id/id/parentId),替代 langchain 消息类型;`id` 用 **uuid7**(时间前缀 + 随机后缀,手写 ~15 行,不引三方依赖——Python 3.12 无内置 uuid7)。备选:uuid4(简单,但无序,JSONL 树形排序靠时间戳字段)与三方 `uuid7` 库(新依赖,否决)。

### D3:归约策略 = 写入顺序 + 显式删除

- 归属:循环内"assistant(tool_calls) → gather(工具) → 按 calls 顺序 append ToolMessages",天然正确;不做插入扫描;
- 删除:失败/取消回滚与压缩复用同一语义——按 id 移除(`RemoveMessage` 等价物),压缩后旧消息仍在 JSONL 文件中(append-only),仅从"活跃上下文"剔除;
- 相邻同 role 消息不合并(与 langgraph 真实行为一致)。

### D4:spike 双跑 diff(本 change 首个任务,gate)

同一 FakeClient steps 分别驱动 langgraph 版(现状)与自研循环版,对比 5 场景的事件序列 + 消息列表:单工具 / 并行双工具成败归属 / 三轮循环 / 失败回滚 / 空响应兜底。判据:事件类型序列逐项相等;payload 仅允许非语义字段差异(如 id)。产出 = 循环原型 + 归约实现 + diff 基线 + 文档勘误(`core/state.py` 与 CLAUDE.md 的 add_messages 描述)。

### D5:JSONL 树形会话格式(草案,版本 1)

```
~/.codeagent/sessions/<session-id>.jsonl
{"type":"session","version":1,"id":"s1","parentSession":null,"timestamp":"...","cwd":"..."}
{"type":"message","id":"m1","parentId":null,"timestamp":"...","role":"user","content":"..."}
{"type":"message","id":"m2","parentId":"m1","timestamp":"...","role":"assistant","tool_calls":[...]}
{"type":"message","id":"m3","parentId":"m2","timestamp":"...","role":"tool","tool_call_id":"c1","content":"..."}
{"type":"compaction","id":"c1","parentId":"m10","timestamp":"...","summary":"...","details":{"readFiles":[...],"modifiedFiles":[...]}}
```
- append-only(崩溃安全、可回放);`parentId` 显式因果链(回放/回滚/分叉基础);`compaction` entry 预留(服务后续压缩与 undo);
- 存储经 hexagonal 缝:SessionStore 协议 + JsonFileStore / MemoryStore(测试),写串行化复用 `tools/shared/mutation_queue.with_path_lock`;
- 版本字段:读侧按 version 解析,不兼容版本明确报错。

### D6:工具执行与组合根

- 工具执行逻辑(core/nodes/tools.py 的并行 gather + 单 call 错误归属 + additional_kwargs.error 标记)上移为循环内普通代码;
- `tools/base.py` 删除 `to_langchain()`,工具直接暴露 `invoke(args) -> str`;`registry.make_tools` 返回自研工具列表;
- `container.py` 重装配:模型(ChatClient)→ 工具列表 → 会话存储(JsonFileStore)注入自研循环与事件壳;删除 ToolNode / InMemorySaver。

### D7:依赖移除顺序与测试重写

- 先删 `ai/bridge/langchain.py` 与 `tests/ai/test_bridge.py`(互相锁定);再重写 core/loop、session/session、container;最后删 pyproject 依赖;
- 测试断言从"图输出"机械转换为"事件序列"(spike diff 基线即断言数据);`FakeClient` 协议不变,直接对接自研循环(不再经 to_langchain_runnable)。

## Risks / Trade-offs

- [消息归约写错(工具链断裂)] → spike gate 先行;5 场景覆盖;既有 test_loop 断言平移为事件序列断言
- [事件契约漂移(TUI/CLI/测试无感知承诺被破坏)] → spike 场景 c 逐事件 diff;10 类事件为冻结契约,后续会话层 change 不得新增类型
- [测试重写量大(~1,700 行)] → 断言转换机械化(spike 基线即断言数据);test_bridge 整文件删除
- [平台部署入口永久失效] → 已评估非刚需;F-24 改写为 HTTP/事件订阅(并入 F-27)
- [uuid7 手写实现正确性] → ~15 行,时间前缀 + 随机后缀;单测锁定单调性
- [JSONL 并发写] → with_path_lock 串行化;单进程单会话写入为主
- [文档与实现历史漂移] → 本 change 同时勘误 core/state.py 与 CLAUDE.md 的归约描述

## Migration Plan

1. **Spike**(D4)通过为 gate;
2. 实现顺序:循环原型 → 消息模型/归约 → JSONL store → 事件壳(session.py 重写)→ tools/container 适配;
3. 测试同步:test_bridge 删除 → test_loop/test_session 改写 → test_container/test_factory 适配 → 全量跑绿;
4. pyproject 移除依赖后全量复跑;
5. 回滚策略:本 change 为地基级,回滚 = 恢复 langgraph 版(session.py/loop.py/container.py 三文件 + 依赖声明),JSONL 文件在恢复期间不写入。

## Open Questions

- 无(后续会话层 change 的 Manager/compaction 触发策略已明确非本 change 范围;uuid7 手写已决策)。
