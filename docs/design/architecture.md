# codeagent 架构设计文档

> 版本: v0.1(已落地)
> 适用范围: 基于 LangGraph 的 Code Agent 项目
> 更新日期: 2026-08-11

## 1. 背景与目标

本项目是一个基于 **LangGraph** 的编程 Agent(codeagent)。设计目标:

1. **可演进**:从"单个工具调用型 Agent"平滑演进到多 Agent / 多会话 / 平台部署。
2. **可替换**:更换模型供应商(DeepSeek / OpenAI / 本地)、更换工具集、更换存储,均不触碰 Agent 编排代码。
3. **可感知**:会话的运行过程以事件流对外暴露,CLI、Web、测试都能订阅,而不是只拿一个最终返回值。
4. **可测试**:核心编排层零网络、零密钥即可运行(注入 fake 模型)。

设计参考:Pi-Agent(`earendil-works/pi`)的"三层协作 / 双层 loop / 事件驱动 / 会话即状态"思想。

## 2. 设计原则:两条正交轴

整个结构由两条独立的分离轴合成,不要混淆:

| 轴 | 分的是什么 | 来源 |
|---|---|---|
| **横切轴:依赖方向** | config / 工具 / 编排 / 调用 之间谁认识谁 | 端口-适配器(hexagonal) |
| **纵切轴:生命周期** | 装配(Factory) / 单个对话(Session) / 会话生命周期(Runtime) | Pi-Agent 三层协作 |

- **横切轴**解决"零件怎么装":依赖单向流动,组合根是唯一交汇点。
- **纵切轴**解决"装好之后会话怎么活":三层生命周期不同、变化率不同,不该绑在一个类里。

**Loop 双层(无状态循环 / 有状态 Agent)在 Pi 里是另一条正交结构**:本项目里 LangGraph 已经提供了无状态循环(编译后的图),有状态外壳由 `session/` 层补齐。不要把它与横切/纵切混淆。

## 3. 现状

- 工具链:`uv` + `src` 布局,Python 3.12。
- 依赖:`httpx`、`langgraph>=1.2.10`、`pydantic-settings`、`textual`;dev 依赖 `pytest`。
- 入口:`pyproject.toml` 中 `codeagent = "codeagent.cli:main"`。
- **已完成(v0.1 起步)**:
- 密钥外置:`.env` / `.env.example`,`.env` 已 gitignore;全局 `Settings` 仅存 `llm_provider`。
- `ai/` 层:五层细分(providers / catalog / protocol / transport / bridge)+ `factory.create_llm()` 统一入口,支持 6 个真实 provider(deepseek / openai / qwen / glm / kimi / minimax)+ 离线 `fake`。
- 测试基建:`tests/` 按 src 模块镜像分包 + `FakeClient`(离线假模型),`uv run pytest` 304 全绿。
- **TUI(调用层)**:`tui/` 子包,Claude 风格布局 + 斜杠模糊命令浮层 + 输入框下侧状态栏 + 真实会话客户端;入口迁移至 `codeagent.cli:main`。
- 原 `demo2.py`(直连 DeepSeek 演示)已删除。

**已完成(v0.1 编排+会话)**:
- `tools/` 原子工具 + registry 已落地(08-09)。
- `core/` ports / state / loop / nodes / events 已落地(08-10,全异步 ReAct)。
- `session/` bus + session 已落地(08-10,会话维度 thread 累积)。
- `container.py` `create_agent_graph` / `create_agent_session` 已落地(08-10)。
- **TUI 接入真实 Agent**:`SessionAgentClient`(组合 `AgentSession`)+ 流式增量渲染已落地(08-10);headless 双路径(`--prompt` / stdin)可用。
- 代码评审 22 项 bug(P1×4 + P2×18)已全部修复并归档。

**待办(v0.2 起)**:
1. 会话持久化(`SessionStore`)、`SessionManager`、上下文压缩(`compaction`)。
2. 资源层 `resources/skills`、扩展层 `extensions/`、平台部署深化。

## 4. 总体结构

### 4.1 目录树

```
codeagent/
├── pyproject.toml / uv.lock          # 依赖、CLI 入口
├── langgraph.json                    # 平台部署入口 → container:create_agent_graph
├── README.md / .env.example / .env   # 说明 + 密钥(不入库)
│
├── src/codeagent/
│   ├── __init__.py / __main__.py     # 版本 + python -m codeagent
│   ├── cli.py                        # [调用层入口] argv 解析 + --headless,启动 TUI
│   │
│   ├── container.py                  # [Factory/组合根] ★ 唯一交汇点
│   │                                 #   create_tui_deps() → (AgentClient, 项目名)
│   ├── config.py                     # [配置层] pydantic-settings(仅 provider 无关字段)
│   │
│   ├── tui/                          # [调用层·TUI] Claude 风格终端界面 ✅ 已落地
│   │   ├── ports.py                  #   AgentClient 端口协议(tui 只认这里)
│   │   ├── agent_client.py           #   占位 + 真实客户端公共基类(状态维护)
│   │   ├── session_client.py         #   SessionAgentClient: 事件流→StreamChunk 翻译
│   │   ├── messages.py               #   StreamChunk / StreamKind / MessageKind
│   │   ├── commands.py               #   斜杠命令注册表 + 校验 + 解析
│   │   ├── fuzzy.py                  #   轻量模糊匹配(命令过滤)
│   │   ├── pickers.py                #   provider/model/effort 选择器
│   │   ├── state.py                  #   RunState / TuiState
│   │   ├── widgets.py                #   聊天区 / 命令浮层 / 状态栏
│   │   ├── app.py                    #   TuiApp(唯一 import Textual 处)
│   │   └── app.css                   #   Claude 风格样式
│   │
│   ├── ai/                           # [模型配置层]  ← pi-ai ✅ 已落地
│   │   ├── factory.py                #   create_llm 统一构造入口 + get_available_providers
│   │   ├── catalog/                  #   模型目录与解析
│   │   │   ├── spec.py               #     ModelSpec(不可变值对象)
│   │   │   ├── builtin.py            #     内置模型目录(deepseek/openai/qwen/glm/kimi/minimax)
│   │   │   ├── store.py              #     models.json 读写(upsert 合并)
│   │   │   └── registry.py           #     ModelRegistry 两遍解析(精确 id → 别名)
│   │   ├── protocol/                 #   框架无关协议层
│   │   │   ├── messages.py           #     ChatClient 协议 / ChatMessage / ToolCall / ChatResponse
│   │   │   └── sse.py                #     StreamEvent / SSEParser(thinking/usage 全量透传)
│   │   ├── transport/                #   OpenAI 兼容传输层
│   │   │   └── openai_compat.py      #     OpenAICompatClient(httpx,重试/流式)
│   │   ├── bridge/                   #   langchain 编排桥接(仅组合根消费)
│   │   │   └── langchain.py          #     to_langchain_ai_message / to_langchain_runnable
│   │   └── providers/                #   每 provider 一个文件,配置+工厂自包含
│   │       ├── deepseek.py / openai.py / qwen.py / glm.py / kimi.py / minimax.py
│   │       └── fake.py               #   FakeClient + make_llm(离线测试)
│   │
│   ├── model_pattern.py              #   [跨层共享] model:effort 解析唯一实现
│   │
│   ├── core/                         # [编排层]  ← pi-agent-core ✅ 已落地
│   │   ├── ports.py                  #   AgentPorts(编排认识的唯一外部世界)
│   │   ├── state.py                  #   AgentState
│   │   ├── loop.py                   #   build_graph(ports) 纯组装 + 条件边
│   │   ├── events.py                 #   AgentEvent 类型
│   │   └── nodes/
│   │       ├── agent.py              #   make_agent_node(bound_model)
│   │       └── tools.py              #   make_tools_node(tool_executor)
│   │
│   ├── session/                      # [Session + Runtime]  ← Pi 核心增量 ✅ 已落地
│   │   ├── session.py                #   AgentSession: run / subscribe / run_sync
│   │   └── bus.py                    #   事件总线: subscribe/emit
│   │
│   ├── tools/                        # [工具层] ✅ 已落地
│   │   ├── base.py / registry.py     #   AtomicTool 基类 + make_tools 注册表
│   │   └── atomic/                   #   read / write / edit / bash
│   │
│   ├── resources/                    # [资源层]  ← Pi 资源系统(轻做,延后)
│   │   └── skills/ prompts/          #   *.md 技能文件 / 提示词模板
│   │
│   └── extensions/                   # [扩展层]  ← 延后
│       └── __init__.py               #   插件扩展占位
│
└── tests/                            # 按 src 模块镜像分包,304 全绿
    ├── conftest.py                   # fake_model / settings 夹具
    ├── test_cli.py / test_config.py / test_container.py / test_decoupling.py   # 调用层与应用层
    ├── ai/                           # factory / fake_client / model_store / providers / sse / transport / bridge
    ├── core/                         # loop(假 ports 跑通整个图)
    ├── session/                      # session(事件 / thread 累积 / run_sync)
    ├── tools/                        # tools(原子工具 + 黑名单 + 退出码语义)
    └── tui/                          # app_picker / app_commands / app_streaming / session_client / tui_widgets / commands / fuzzy / agent_client
```

### 4.2 模块职责一览

| 目录/文件 | 一句话职责 | 关键约束 |
|---|---|---|
| `container.py` | 组合根,创建图与会话 | 全项目唯一 import 所有层的地方 |
| `config.py` | 全局配置(仅 provider 无关字段) | 只被 container / ai / tools 读取 |
| `ai/` | 模型配置层:五层细分(providers/catalog/protocol/transport/bridge)+ factory 统一入口 | 不 import 工具、编排 |
| `core/` | 编排层:端口、状态、图、节点 | 不 import config / ai / tools / session |
| `session/` | 有状态会话 + 事件分发 | 不 import ai / tools / config |
| `tools/` | 工具层:原子工具 + 注册表 | 不 import 模型、编排 |
| `resources/` | 技能 / 提示词按需加载 | 延后可先空 |
| `extensions/` | 插件:两阶段(注册→绑定) | 延后 |

### 4.3 配置命名空间(重要)

`.env` 是共享文件,但全局 `Settings` 与各 provider 的 `Config` **各自解析、各自只认自己的键**:

| 配置类 | 认的键 | 忽略 |
|---|---|---|
| `Settings`(全局) | `LLM_PROVIDER` 等 | `DEEPSEEK_*` / `OPENAI_*` |
| `DeepSeekConfig` | `DEEPSEEK_*`(env_prefix) | `LLM_PROVIDER` 等 |
| `OpenAIConfig` | `OPENAI_*`(env_prefix) | 其它 |

因此**所有配置类必须设置 `extra="ignore"`**,否则共享 `.env` 中任一命名空间的键都会让其它配置类报 `extra_forbidden`(实现时实际踩过,已修复并补防回归测试)。

## 5. 核心契约

### 5.1 AgentPorts —— 编排认识外部世界的唯一窗口

```python
# core/ports.py
from dataclasses import dataclass
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable

@dataclass(frozen=True)
class AgentPorts:
    bound_model: BaseChatModel            # 已 bind 工具(由组合根负责 bind)
    tool_executor: Runnable               # 工具执行器,对 loop 是黑盒
    checkpointer: object | None = None    # 持久化,由组合根决定
```

**为什么 `bound_model` 而不是 `model + tools`**:编排层连"工具"这个概念都不需要知道。工具绑定是组合根的事(`llm.bind_tools(tools)`),这样加/换工具时 `core/` 零改动。

### 5.2 build_graph —— 纯组装,零副作用

```python
# core/loop.py
from langgraph.graph import StateGraph, START, END

def build_graph(ports: AgentPorts) -> CompiledGraph:
    agent = make_agent_node(ports.bound_model)
    tools = make_tools_node(ports.tool_executor)

    g = StateGraph(AgentState)
    g.add_node("agent", agent)
    g.add_node("tools", tools)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile(checkpointer=ports.checkpointer)
```

要点:
- 模块顶层**没有任何副作用**(不建模型、不发请求、不读 key),平台可直接 import。
- 循环条件 `should_continue` 只看 state 形状(最后一条消息有没有 `tool_calls`),**不 import 任何具体工具**。

### 5.3 AgentSession —— 有状态会话壳(单个对话)

```python
# session/session.py
class AgentSession:
    def __init__(self, graph, bus, recursion_limit=50): ...

    async def run(self, text, recursion_limit=None) -> None: ...  # 发布事件,不返回值
    def run_sync(self, text) -> None: ...                         # 同步便捷入口(CLI/脚本)
    def subscribe(self, fn) -> None: ...                          # 订阅事件
```

- 持有 thread_id / 事件路由,`recursion_limit` 默认 50 且单轮可覆盖。
- **`run` 返回事件流而不是单个 `AIMessage`**——CLI/Web/测试都通过 `subscribe` 感知进度。
- `steer / followup / abort` 未落地,延后 v0.2(会话生命周期由 SessionManager 承接)。

**v0.1 落地决策(2026-08-10)**:
- **全异步**:`run()` 为 `async def`,用 `graph.astream(stream_mode=["messages","updates"])` 运行,天然配合 Textual 事件循环;`run_sync()` 供无 loop 或已有 loop 的线程调用(新线程 + `asyncio.run`)。
- **会话维度 thread 累积**:`AgentSession` 构造时分配稳定 `thread_id`,同一会话所有 `run()` 打进同一 LangGraph thread;配合 checkpointer,多轮对话累积上下文(会话即状态)。
- **存储**:v0.1 只靠 checkpointer 兜底(`AgentPorts.checkpointer`),`SessionStore` 延后 v0.2。UI 流式 token 仅即时展示,最终完整消息由 checkpointer 持久化。
- **事件类型**:`session_started` / `text_delta`(token 增量)/ `agent_message`(最终完整回复)/ `tool_call` / `tool_result` / `turn_end` / `error`。

### 5.4 SessionManager —— 会话生命周期

```python
# session/manager.py
class SessionManager:
    def __init__(self, store: SessionStore): ...
    def create(self) -> SessionRef: ...
    def fork(self, session_id: str) -> SessionRef: ...   # 延后可做
    def switch(self, session_id: str) -> None: ...
    def dispose(self, session_id: str) -> None: ...
```

## 6. 组合根:三层解耦的唯一交汇点

```python
# container.py
#: 项目名缓存:首次读取后复用,不随 CWD 变化
_project_name_cache: str | None = None

def create_agent_graph(cfg=None, *, registry=None, checkpointer=None,   # ← langgraph.json 指向它
                       reasoning_effort=None, provider=None, model=None) -> CompiledGraph:
    llm = create_llm(cfg, registry=registry, reasoning_effort=reasoning_effort,
                     provider=provider, model=model)                   # ai/factory.create_llm
    tools = create_tools(cfg)                                          # 工具层 → 端口
    bound = to_langchain_runnable(llm.bind_tools(tools))               # ★ 工具/模型唯一交汇行
    ports = AgentPorts(
        bound_model=bound,
        tool_executor=ToolNode(tools),
        checkpointer=checkpointer or InMemorySaver(),                  # v0.1 内存兜底
    )
    return build_graph(ports)

def create_agent_session(cfg=None, *, registry=None, checkpointer=None, # ← CLI 入口
                         reasoning_effort=None, provider=None, model=None) -> AgentSession:
    graph = create_agent_graph(cfg, registry=registry, checkpointer=checkpointer,
                               reasoning_effort=reasoning_effort, provider=provider, model=model)
    return AgentSession(graph, EventBus(),
                        recursion_limit=getattr(cfg, "recursion_limit", None) or 50)
```

```json
// langgraph.json —— 平台与 CLI 共享同一份图定义
{
  "dependencies": ["."],
  "graphs": { "agent": "src/codeagent/container.py:create_agent_graph" },
  "env": ".env"
}
```

## 7. 运行时生命周期

```
启动:   cli → create_agent_session()
        → ai/tools 各自产端口 → bind_tools 交汇 → build_graph(ports)
        → AgentSession(graph, bus)

一轮:   session.run(text)   [async]
        → bus.emit(session_started)
        → graph.astream(thread=thread_id, stream_mode=[messages, updates])
            → 翻译成 AgentEvent(text_delta / tool_call / tool_result / agent_message)
        → bus.emit(turn_end)
        → [v0.2] store.append(entry)

TUI:    TuiApp → SessionAgentClient.respond_stream(prompt)
        → session.run(text) → 事件经 asyncio.Queue 桥接 → StreamChunk(text/tool_call/tool_result/done)
        → TranscriptView 增量渲染(append 单条 / update_assistant 流式)

干预:   run_sync(text)   [CLI/脚本同步入口]
生命周期: manager.create() / dispose()   [P1/v0.2]
```

## 8. 依赖规则

| 模块 | 可以 import | 禁止 import |
|---|---|---|
| `config` | —(只被 container / ai / tools 读取) | core、session、cli |
| `ai` / `tools` | config | core、session、container 的反向 |
| `core` | 只有 `ports.py`(及 langchain/langgraph) | config、ai、tools、session |
| `session` | core(ports/loop)、bus、store | ai、tools、config |
| `container` | 全部(唯一交汇点) | — |
| `cli` | container、session、bus | core、ai、tools |

## 9. 解耦判据(泄漏检测)

分层是否成立,不看文件多整齐,看**改一层要不要动另一层**:

| 变更 | 应动的文件 | 若还动了 | 结论 |
|---|---|---|---|
| 新增一个 provider | `ai/` + 环境变量 | `session.py` / `core/` | ❌ 泄漏 |
| 新增/更换一个工具 | `tools/` | `core/loop.py` / `ai/` | ❌ 泄漏 |
| 改编排形状(加节点/改循环) | `core/` | `ai/` / `tools/` | ❌ 泄漏 |
| 换会话存储 | `store.py` + `container` | `cli.py` / `core/` | ❌ 泄漏 |
| 加会话分叉 | `session/` | `core/graph.py` | ❌ 泄漏 |

最严格判据:**`core/` 里 grep 不到 `config / tools / ai / session` 字面量 → 横切解耦成立;`session.py` 里 grep 不到 `ai / tools` → 纵切解耦成立。**

## 10. 决策溯源

| 结构 | 对应讨论结论 |
|---|---|
| `container.py` + `config.py` | 组合根 + 配置层独立 |
| `ai/` + `tools/` | 工具层 / 模型配置层 / Agent 创建层三层解耦 |
| `core/` | 端口-适配器、编排层独立 |
| `session/` | Pi 三层协作的 Session + Runtime、会话即状态 |
| `events.py` + `bus.py` | Pi 事件驱动,替代"返回单个 AIMessage" |
| `resources/` + `extensions/` | Pi 资源 / 扩展系统(延后档) |

## 11. 落地路线

| 阶段 | 范围 | 产物 |
|---|---|---|
| **v0.1 最小可跑** | `config + container + ai + tools + core + session(session+bus) + cli + tui` | CLI 可对话、可调用 read/write/edit/bash,事件可打印。进度:✅ 全部落地(2026-08-10):`config` ✅、`ai` ✅、`tools` ✅、`core` ✅(全异步 ReAct)、`session` ✅(bus+session)、`container` ✅(graph/session)、`tui` ✅(SessionAgentClient 接入 + 流式渲染)、headless ✅。代码评审 22 项 bug 已修复并归档。 |
| **v0.2 会话完善** | `store(线性) + manager + compaction(手动)` | 会话可恢复、可切换、可压缩 |
| **v0.3 资源扩展** | `resources/ + extensions/ + 分支 fork` | 插件化、skills 按需加载 |

v0.1 是最终结构树的**子集**,结构与定稿一致,延后目录先留空。

## 12. 参考

- [earendil-works/pi](https://github.com/earendil-works/pi) — Pi Agent SDK(三层协作 / 双层 loop / 事件驱动 / 会话即状态)
- [learning-pi-agent](https://github.com/yamsfeer/learning-pi-agent) — 架构深度笔记
- [how-pi-agent-works](https://github.com/myxiaoao/how-pi-agent-works) — 中文教学实现
- [LangGraph 文档](https://langchain-ai.github.io/langgraph/) — StateGraph / checkpointer / ToolNode
