# 编排引擎自研蓝图(第二步,已落地)

> 状态: **已落地**(2026-08-14,OpenSpec change `self-built-orchestration`)——自研 ReAct 主循环 + 消息归约 + JSONL 树形会话替换 langgraph 编排,pyproject 移除 langchain-core/langgraph;三未决问题结论:平台部署非刚需、归约 spike 通过(5 场景双跑 diff)、JSONL 树形为格式结论。本文保留为决策与收益记录。
> 更新日期: 2026-08-14
> 关系: 本文是「自研统一封装」两阶段规划的第二阶段。第一阶段(ModelRuntime,模型层)见对应 OpenSpec change;本文描述编排层自研的范围、收益、边界。

---

## 1. 背景:为什么会有这份蓝图

在「不依赖 langchain 自研统一封装」的讨论中,结论是分两步走:

```
第一步(当前):  自研 ModelRuntime  → 替代 langchain 模型客户端层(ai/)
第二步(暂缓):  自研 ReAct 编排   → 替代 langgraph 编排层(core/ + session/ 部分)
```

本文记录第二步「编排自研」的思考——包括自研哪些部分、收益、边界。它不作为当前工作项,而是为未来决策留存的分析。

---

## 2. 现状:langgraph 在编排层做了 4 件事

当前 `AgentSession.run` 到事件流之间的「图」由 langgraph 提供:

| # | 职责 | 实现 | 位置 |
|---|---|---|---|
| ① | 状态归约 | `add_messages`(同 role 合并 / 工具结果按 tool_call_id 归属) | `core/state.py` |
| ② | 图遍历 | `astream`(START→agent→should_continue→tools→agent/END,双通道 messages+updates) | `core/loop.py` |
| ③ | 工具执行 | `ToolNode`(我们已外包一层并行+错误归属) | `core/nodes/tools.py` |
| ④ | 持久化 | `InMemorySaver` + thread_id 快照 | `container.py` |

`session/session.py` 的 `_translate`(约 60 行)就是在消费 ② 的产物——`astream` 双通道 → `AgentEvent`。注意这层翻译已存在,说明「图输出→事件流」的桥已建好。

---

## 3. 需要自研的部分(范围)

### 3.1 自研 ReAct 主循环(约 100-200 行)

```
async def run(thread, text):
    state = load(thread)                      # ④ 持久化 → 手动字典
    state.messages.append(human)
    for _ in range(recursion_limit):          # 循环控制
        msg = await model(state.messages)     # ① 不再需要归约,直接传列表
        emit(text_delta / agent_message)
        if not msg.tool_calls: break
        emit(tool_call)
        results = await gather(execute(t) for t in msg.tool_calls)  # ③
        emit(tool_result)
        state.messages += results             # 手动 append
    save(thread, state)                       # ④ 手动存
```

### 3.2 需要自研的 5 个组件

| # | 组件 | 说明 |
|---|---|---|
| R1 | ReAct 主循环 | `for` 循环:模型→工具→继续/结束;天然单通道事件 |
| R2 | 消息归约 | `add_messages` 等价物:工具结果按 tool_call_id 归属(约 30 行,最关键) |
| R3 | 会话持久化 | JSONL 树形(id/parentId)或线性;替换 InMemorySaver |
| R4 | 工具调度 | 并行 `gather` + 单 call 错误归属(现在是 hack ToolNode) |
| R5 | 控制流 | recursion_limit / abort / 工具超时(`asyncio.wait_for`) |

### 3.3 明确不自研(边界外)

| 组件 | 归属 |
|---|---|
| SSE 流式解析 | 模型客户端层(第一步已做) |
| 工具 schema(AtomicTool→JSON Schema) | pydantic 已提供,不碰 |
| 平台部署入口 | 见 §5 代价 4,需单独决策 |

---

## 4. 收益(自研编排的 5 个真收益)

### 收益 1:事件流原生化,翻译层消失

```
现状:  图 astream → (messages, updates) 双通道 → _translate 翻译 → AgentEvent
自研:  for 循环里直接 emit(AgentEvent)  ← 翻译层整个消失
```

且能发现 langgraph 下发不了的事件:
- `thinking_delta`:流式帧里 DeepSeek 的 `reasoning_content`,现状 `_translate_message_stream` 只透传 `content`,thinking 丢失;
- `usage`:每轮结束直接发,不用事后从 `usage_metadata` 挖。

### 收益 2:steer/followup/abort 从「规划」变「几行代码」

```
自研 for 循环里:
  steer(msg):   msg_queue.put(msg)   # 下一轮循环前插入
  followup():   循环结束后再跑一轮
  abort():      break + 保存已产出状态
```

这是 Pi 对比里 codeagent 最落后的地方(Pi 原生支持 steer/followup/Esc abort),自研编排是补上它的最短路。

### 收益 3:会话树/分叉从「不可能」变「一个字典」

```
fork(thread_id, from_msg_id):
    新 thread = copy(state up to from_msg_id)   # 一行深拷贝
```

Pi 的 JSONL 树形(id/parentId)可直接照搬——每条消息存 id/parentId,分叉=新消息挂到父节点。

### 收益 4:工具层解耦加深

不再有 ToolNode,执行就是:

```
for call in msg.tool_calls:
    tool = tools_by_name.get(call.name)
    try: result = await tool.ainvoke(call.args)
    except: result = f"[工具执行出错] {exc}"   # 天然单 call 兜底
```

之前修的「并行执行 + 错误归属精确」(P2-2/P2-14)变成循环里的天然写法。

### 收益 5:控制流全部是普通代码

`recursion_limit`→for 计数;`Ctrl+C`→`CancelledError` 自然传播;工具超时→`asyncio.wait_for`。不再依赖 RunnableConfig 注入。

---

## 5. 边界(代价)

### 代价 1:消息归约逻辑要自己写(最关键)

`add_messages` 的「工具结果按 tool_call_id 归属」——AIMessage 的 tool_calls 之后要正确接上对应 ToolMessage,模型才能看到工具结果。**这是最容易出错且直接影响模型行为的地方**,需先做 spike 验证。

### 代价 2:会话恢复要自己设计

现在 InMemorySaver 存完整快照。自研后要自己决定持久化格式——这不是坏事(Pi 的 JSONL 更简单:每轮 append,天然可恢复/可树形/可回放),但要做。

### 代价 3:219 测试全量重写

编排相关测试(test_loop / test_session / test_session_client / test_container,约 80+)依赖 CompiledGraph/astream 接口。自研后接口全变——断言从「图输出」改为「事件序列」(更贴近用户可见行为,但工作量大)。

### 代价 4:`langgraph.json` 平台部署入口失效

现在 `container.create_agent_graph` 返回 CompiledGraph,langgraph.json 指向它。自研后没有 CompiledGraph 了——平台部署(langgraph platform / LangSmith)要重设计或放弃。**这是边界判断的关键点**:若平台部署是刚需,自研编排的净收益需重新评估。

---

## 6. 边界判断总结

```
强烈建议自研(收益高、代价低):
  • ReAct 主循环  ~100 行
  • 事件流原生(thinking/usage 事件)
  • steer/followup/abort

建议自研但要认真设计(收益高、代价中):
  • 消息归约(add_messages 等价物)
  • 会话持久化(JSONL 树形,对齐 Pi)

不建议自研(边界外):
  • SSE 流式解析(归模型层)
  • 工具 schema(pydantic 已给)
  • 平台部署(若要保留 langgraph 生态,需权衡)
```

---

## 7. 自研后的整体形态

```
┌─────────────────────────────────────────────────────────────┐
│              自研后的 codeagent 核心                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ModelRuntime(第一步)         ReActLoop(第二步)              │
│  ├ OpenAICompatClient         ├ 主循环 for                    │
│  ├ FakeClient                 ├ 事件流 emit                   │
│  └ SSE 解析                   ├ steer/followup/abort         │
│       │                       └ 会话树(JSONL)                │
│       │                             │                       │
│       └────────────┬────────────────┘                       │
│                    ▼                                        │
│          AgentSession(事件壳) → TUI/CLI                      │
│                                                             │
│  依赖: httpx + pydantic(去 langchain/langgraph)             │
└─────────────────────────────────────────────────────────────┘
```

**这个形态就是 Pi 的 Python 版**——ModelRuntime 对应 pi-ai,ReActLoop 对应 pi-agent-core。

---

## 8. 未决问题(第二步启动前需回答)

1. **平台部署是不是刚需**?langgraph.json 现在指向 create_agent_graph。放弃 langgraph 生态则平台部署要么重设计、要么放弃——显著影响净收益。
2. **消息归约正确性**spike:工具结果按 tool_call_id 归属——写不对则模型工具链断裂。建议第二步前先写 spike 验证。
3. **会话持久化格式**:直接对齐 Pi 的 JSONL 树形,还是先线性?树形一开始做,分叉/回放就都有了。
