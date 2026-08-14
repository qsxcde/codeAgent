# codeagent 架构设计文档

> 版本: v0.1(已落地)
> 适用范围: 基于 LangGraph 的 Code Agent 项目
> 更新日期: 2026-08-14(校准至当前树:app/ 包重组、TUI 恢复、255 测试、工具 4→7)

## 1. 背景与目标

本项目是一个基于 **LangGraph** 的编程 Agent(codeagent)。设计目标:

1. **可演进**:从"单个工具调用型 Agent"平滑演进到多 Agent / 多会话 / 平台部署。
2. **可替换**:更换模型供应商(DeepSeek / OpenAI / Qwen / GLM / Kimi / MiniMax)、更换工具集、更换存储,均不触碰 Agent 编排代码。
3. **可感知**:会话的运行过程以事件流对外暴露,CLI、TUI、Web、测试都能订阅,而不是只拿一个最终返回值。
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
- 依赖:`httpx`、`langchain-core>=1.5.3`、`langgraph>=1.2.10`、`pydantic-settings`、`textual`;dev 依赖 `pytest`。
- 入口:`pyproject.toml` 中 `codeagent = "codeagent.app.main:main"`。
- **已完成(v0.1)**:
- 密钥外置:固定目录 `~/.codeagent/.env`(首次启动幂等生成模板),**不读取 CWD 下 `.env`**(安全决策 H10);全局 `Settings` 仅存 `llm_provider`。
- `ai/` 层:五层细分(providers / catalog / protocol / transport / bridge)+ `factory.create_llm()` 统一入口,支持 6 个真实 provider(deepseek / openai / qwen / glm / kimi / minimax)+ 离线 `fake`;模型客户端自研(httpx + 自研 SSE 解析,thinking / usage 全量透传),经 `ai/bridge/langchain.py` 包装成 langchain Runnable 供编排层消费(2026-08-13 落地,pyproject 已移除 langchain-openai)。
- 工具层(hexagonal,2026-08-13 重构):`AtomicTool` 无状态基类 + `FsOps` 文件系统抽象缝 + cwd 注入;read / write / edit / bash / grep / find / ls 七个工具;bash 带危险命令黑名单、树级进程击杀、默认 120s 超时、输出保尾截断。
- `core/` 编排层:ports / state / loop / nodes / events(全异步 ReAct),模块顶层零副作用。
- `session/` 会话层:bus + session(会话维度 thread 累积),`abort()` 运行中断、`replace_graph()` 换图保留 thread、失败自动回滚本轮消息。
- 事件 10 类:`session_started / text_delta / thinking_delta / agent_message / tool_call / tool_result / turn_end / error / run_cancelled / usage`。
- 入口形态:`app/main.py` headless 双路径(`--prompt` / stdin)+ `--tui` 交互式终端(MVP,2026-08-13 恢复,08-14 主流形态改造:多行 composer、命令记录行、工具块折叠点击展开、单行状态栏 + 上下文用量条、Esc 打断/退出、alt 屏)。
- 测试基建:`tests/` 按 src 模块镜像分包 + `FakeClient`(离线假模型),`uv run pytest` **266 全绿**(2026-08-14 实测)。

**待办(v0.2 起)**:
1. 会话持久化(`SessionStore`)、`SessionManager`、上下文压缩(`compaction`)、`steer / followup`。
2. 解耦扫描测试按 `app/` 新分层重写(`test_decoupling.py` 已于 2026-08-13 移除)。
3. TUI 增强:斜杠命令 / 模糊补全 / 选择器、Markdown 渲染、滚动交互。
4. 资源层 `resources/skills`、扩展层 `extensions/`、平台部署(`langgraph.json` 已于 2026-08-13 移除,登记 v0.3 重建)。

## 4. 总体结构

### 4.1 目录树

```
codeagent/
├── pyproject.toml / uv.lock          # 依赖、CLI 入口(codeagent.app.main:main)
├── README.md / CLAUDE.md             # 说明 + Claude Code 工作指南
├── .env.example                      # 密钥模板(不入库;实际密钥在 ~/.codeagent/.env)
├── docs/                             # design/(需求/架构/蓝图)+ iteration/v0.1.md(权威)
├── openspec/                         # OpenSpec 规格与归档变更
│
├── src/codeagent/
│   ├── __init__.py / __main__.py     # 版本 + python -m codeagent
│   │
│   ├── app/                          # [组合根 + 入口] ★ 唯一跨层交汇点
│   │   ├── container.py              #   组合根:create_agent_graph / create_agent_session / create_tui_app
│   │   ├── main.py                   #   CLI 入口:--prompt / stdin / --tui
│   │   ├── config.py                 #   全局 Settings + ~/.codeagent 模板幂等生成
│   │   └── tui/                      #   [调用层·TUI] 交互式终端 MVP ✅ 已落地
│   │       ├── view.py               #     TuiApp 视图逻辑(事件→渲染,只依赖 TuiBackend 端口)
│   │       ├── components.py         #     纯渲染组件树(Span 样式标签段,引擎无关可离线测)
│   │       ├── backend.py            #     TuiBackend 端口协议
│   │       ├── textual_backend.py    #     textual 引擎实现(当前唯一后端)
│   │       ├── theme.py              #     样式标签词表
│   │       └── main.py               #     TUI 入口(--tui 转交此处,装配在组合根)
│   │
│   ├── ai/                           # [模型配置层]  ← pi-ai ✅ 已落地
│   │   ├── factory.py                #   create_llm 统一构造入口 + get_available_providers
│   │   ├── model_pattern.py          #   model:effort 解析唯一实现(跨层共享)
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
│   ├── core/                         # [编排层]  ← pi-agent-core ✅ 已落地
│   │   ├── ports.py                  #   AgentPorts(编排认识的唯一外部世界)
│   │   ├── state.py                  #   AgentState
│   │   ├── loop.py                   #   build_graph(ports) 纯组装 + 条件边
│   │   ├── events.py                 #   事件类型(10 类)+ AgentEvent
│   │   └── nodes/
│   │       ├── agent.py              #   make_agent_node(bound_model)
│   │       └── tools.py              #   make_tools_node(tool_executor,按 call 粒度并行 + 兜底)
│   │
│   ├── session/                      # [Session + Runtime]  ← Pi 核心增量 ✅ 已落地
│   │   ├── session.py                #   AgentSession: run / subscribe / run_sync / abort / replace_graph
│   │   └── bus.py                    #   事件总线: subscribe/emit
│   │
│   ├── tools/                        # [工具层] hexagonal ✅ 已落地
│   │   ├── base.py                   #   AtomicTool 基类(Args pydantic schema → StructuredTool)
│   │   ├── registry.py               #   make_tools 工厂(7 个工具,cwd/ops 注入)
│   │   ├── atomic/                   #   read / write / edit / bash / grep / find / ls
│   │   └── shared/                   #   FsOps 抽象 / paths / textfile / truncate / mutation_queue / ignore
│   │
│   ├── resources/                    # [资源层]  ← Pi 资源系统(轻做,延后)
│   │   └── skills/ prompts/          #   *.md 技能文件 / 提示词模板
│   │
│   └── extensions/                   # [扩展层]  ← 延后
│       └── __init__.py               #   插件扩展占位
│
└── tests/                            # 按 src 模块镜像分包,266 全绿(2026-08-14 实测)
    ├── conftest.py                   # _isolate_config_dir / fake_model / InMemoryFsOps 夹具
    ├── test_cli.py / test_config.py / test_container.py   # 应用层(拍平到根)
    ├── ai/                           # factory / fake_client / model_store / providers / sse / transport / bridge
    ├── core/                         # loop / events
    ├── session/                      # session(事件 / thread 累积 / abort / 回滚)
    ├── tools/                        # test_tools.py(单文件覆盖整个工具包)
    └── tui/                          # view / components
```

### 4.2 模块职责一览

| 目录/文件 | 一句话职责 | 关键约束 |
|---|---|---|
| `app/container.py` | 组合根,创建图 / 会话 / TUI 应用 | 全项目唯一 import 所有层的地方 |
| `app/main.py` | CLI 入口(--prompt / stdin / --tui) | 与 container 同为跨层 import 允许点 |
| `app/config.py` | 全局配置(仅 provider 无关字段)+ 模板生成 | 只被 container / ai 读取 |
| `ai/` | 模型配置层:五层细分 + factory 统一入口 | 不 import 工具、编排 |
| `core/` | 编排层:端口、状态、图、节点、事件 | 不 import config / ai / tools / session |
| `session/` | 有状态会话 + 事件分发 | 不 import ai / tools / config |
| `tools/` | 工具层:原子工具 + 注册表 + 共享设施 | 不 import 模型、编排;`shared/` 只被 tools 内部使用 |
| `app/tui/` | 交互式终端(视图/组件/后端端口) | view 只依赖 TuiBackend 端口;禁止 import textual(具体后端除外) |
| `resources/` | 技能 / 提示词按需加载 | 延后可先空 |
| `extensions/` | 插件:两阶段(注册→绑定) | 延后 |

### 4.3 配置命名空间(重要)

`~/.codeagent/.env` 是共享文件,但全局 `Settings` 与各 provider 的 `Config` **各自解析、各自只认自己的键**:

| 配置类 | 认的键 | 忽略 |
|---|---|---|
| `Settings`(全局) | `LLM_PROVIDER` 等 | `DEEPSEEK_*` / `OPENAI_*` |
| `DeepSeekConfig` | `DEEPSEEK_*`(env_prefix) | `LLM_PROVIDER` 等 |
| `OpenAIConfig` | `OPENAI_*`(env_prefix) | 其它 |

因此**所有配置类必须设置 `extra="ignore"`**,否则共享 `.env` 中任一命名空间的键都会让其它配置类报 `extra_forbidden`(实现时实际踩过,已修复并补防回归测试)。配置来源固定为 `~/.codeagent/.env`,不读 CWD 相对路径 `.env`(H10)。

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

def build_graph(ports: AgentPorts, recursion_limit: int = 50) -> CompiledGraph:
    agent = make_agent_node(ports.bound_model)
    tools = make_tools_node(ports.tool_executor)

    g = StateGraph(AgentState)
    g.add_node("agent", agent)
    g.add_node("tools", tools)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
    g.add_edge("tools", "agent")
    return g.compile(checkpointer=ports.checkpointer)
```

要点:
- 模块顶层**没有任何副作用**(不建模型、不发请求、不读 key),平台可直接 import。
- 循环条件 `should_continue` 只看 state 形状(最后一条消息有没有 `tool_calls`),**不 import 任何具体工具**。
- `recursion_limit`(默认 50)是运行期 RunnableConfig 键,由 session 在 run config 中注入。
- agent 节点用 `bound_model.astream` 逐增量聚合为单一 AIMessage(激活流式路径);tools 节点按 `tool_call` 粒度并行执行,单调用失败只回填该调用的错误 ToolMessage,不崩整图(P2-2 回归)。

### 5.3 AgentSession —— 有状态会话壳(单个对话)

```python
# session/session.py
class AgentSession:
    def __init__(self, graph, bus, recursion_limit=50): ...

    async def run(self, text, recursion_limit=None) -> None: ...  # 发布事件,不返回值
    def run_sync(self, text) -> None: ...                         # 同步便捷入口(CLI/脚本)
    def subscribe(self, fn) -> Callable[[], None]: ...            # 订阅事件,返回退订函数
    def abort(self) -> None: ...                                  # 取消当前 run
    def replace_graph(self, graph) -> None: ...                   # 换图保留 thread_id
```

- 持有 thread_id / 事件路由,`recursion_limit` 默认 50 且单轮可覆盖。
- **`run` 发布事件流而不是返回单个 `AIMessage`**——CLI/TUI/Web/测试都通过 `subscribe` 感知进度。
- **全异步**:`run()` 为 `async def`,用 `graph.astream(stream_mode=["messages","updates"])` 运行,把过程翻译成 `AgentEvent` 经 `EventBus` 分发;`run_sync()` 供无 loop 或已有 loop 的调用方使用(新线程 + `asyncio.run`)。
- **会话维度 thread 累积**:构造时分配稳定 `thread_id`,同一会话所有 `run()` 打进同一 LangGraph thread;配合 checkpointer,多轮对话累积上下文(会话即状态)。
- **失败回滚**:图级失败先按消息 id 快照回滚本轮已写入 thread 的消息(RemoveMessage),再发 `ERROR` 事件;`abort()` 触发 `RUN_CANCELLED` 后重抛。
- **事件类型(10 类)**:`session_started` / `text_delta`(token 增量)/ `thinking_delta`(思考过程)/ `agent_message`(完整回复,增量已流出时去重)/ `tool_call` / `tool_result` / `turn_end` / `error` / `run_cancelled` / `usage`(token 用量)。
- **存储**:v0.1 只靠 checkpointer 兜底(`AgentPorts.checkpointer`,默认 `InMemorySaver`),`SessionStore` 延后 v0.2。
- `steer / followup` 未落地,延后 v0.2(会话生命周期由 SessionManager 承接)。

### 5.4 SessionManager —— 会话生命周期(规划,未落地)

```python
# session/manager.py(规划)
class SessionManager:
    def __init__(self, store: SessionStore): ...
    def create(self) -> SessionRef: ...
    def fork(self, session_id: str) -> SessionRef: ...   # 延后可做
    def switch(self, session_id: str) -> None: ...
    def dispose(self, session_id: str) -> None: ...
```

> 当前树未落地;`abort()` / `replace_graph()` 已直接落在 `AgentSession` 上(v0.1 增量),Manager + Store 列入 v0.2。

## 6. 组合根:三层解耦的唯一交汇点

```python
# app/container.py
def create_agent_graph(cfg=None, *, registry=None, checkpointer=None,
                       reasoning_effort=None, provider=None, model=None) -> CompiledGraph:
    llm = create_llm(cfg, registry=registry, reasoning_effort=reasoning_effort,
                     provider=provider, model=model)                   # ai/factory.create_llm
    tools = create_tools(cfg)                                          # tools/registry.make_tools
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

def create_tui_app(cfg=None, *, backend=None, ...) -> TuiApp:          # ← TUI 入口
    # session + backend(缺省 TextualBackend)+ footer 的 model/effort 解析固化
```

要点:
- langchain 只在 `ai/bridge/` 与 `app/container.py` 加载(启动路径轻量);`bridge` 只被组合根消费。
- `checkpointer` / `registry` / `reasoning_effort` / `provider` / `model` 均可注入:运行时重建图(如切换模型/effort)时保留同一 thread 上下文(H8/M11)。
- `langgraph.json` 平台入口已移除(2026-08-13),登记 v0.3 重建。

## 7. 运行时生命周期

```
启动:   app/main.py → ensure_config_files() → create_agent_session()
        → ai/tools 各自产端口 → bind_tools 交汇 → build_graph(ports)
        → AgentSession(graph, bus)

一轮:   session.run(text)   [async]
        → bus.emit(session_started)
        → graph.astream(thread=thread_id, stream_mode=[messages, updates])
            → 翻译成 AgentEvent(text_delta / thinking_delta / tool_call / tool_result / usage …)
        → bus.emit(turn_end)
        → [v0.2] store.append(entry)

TUI:    app/main.py --tui → create_tui_app() → TuiApp.start()
        → 订阅 AgentSession 事件 → TuiModel.apply 更新组件状态 → 合并渲染(≥30fps)
        → 提交:session.run(text);Esc:运行中 abort / 空闲退出打印完整文档

干预:   run_sync(text)   [CLI/脚本同步入口]
生命周期: manager.create() / dispose()   [P1/v0.2]
```

## 8. 依赖规则

| 模块 | 可以 import | 禁止 import |
|---|---|---|
| `app/config.py` | —(只被 container / ai 读取) | core、session、tools、app/tui |
| `ai` / `tools` | config(工具层内部:shared) | core、session |
| `core` | 只有 `ports.py`(及 langchain/langgraph) | config、ai、tools、session |
| `session` | core(ports/loop/events)、bus | ai、tools、config |
| `app/container.py` | 全部(唯一交汇点) | — |
| `app/main.py` | container、session、bus | core、ai、tools(直接) |
| `app/tui/` | session、core(events)、theme | ai、tools、config;textual 仅 textual_backend |

## 9. 解耦判据(泄漏检测)

分层是否成立,不看文件多整齐,看**改一层要不要动另一层**:

| 变更 | 应动的文件 | 若还动了 | 结论 |
|---|---|---|---|
| 新增一个 provider | `ai/` + 环境变量 | `session.py` / `core/` | ❌ 泄漏 |
| 新增/更换一个工具 | `tools/` | `core/loop.py` / `ai/` | ❌ 泄漏 |
| 改编排形状(加节点/改循环) | `core/` | `ai/` / `tools/` | ❌ 泄漏 |
| 换会话存储 | `store.py` + `container` | `app/main.py` / `core/` | ❌ 泄漏 |
| 加会话分叉 | `session/` | `core/graph.py` | ❌ 泄漏 |

最严格判据:**`core/` 里 grep 不到 `config / tools / ai / session` 字面量 → 横切解耦成立;`session/` 里 grep 不到 `ai / tools / config` → 纵切解耦成立。**

> 注:`test_decoupling.py` 自动扫描测试已于 2026-08-13 移除,当前判据靠人工遵守;按 `app/` 新分层重写列入 v0.2 验收。

## 10. 决策溯源

| 结构 | 对应讨论结论 |
|---|---|
| `app/container.py` + `app/config.py` | 组合根 + 配置层独立(2026-08-13 由顶层迁入 `app/` 包) |
| `ai/` + `tools/` | 工具层 / 模型配置层 / Agent 创建层三层解耦 |
| `core/` | 端口-适配器、编排层独立 |
| `session/` | Pi 三层协作的 Session + Runtime、会话即状态 |
| `events.py` + `bus.py` | Pi 事件驱动,替代"返回单个 AIMessage" |
| `ai/protocol|transport|bridge` | 模型客户端自研三层(2026-08-13,E1):框架无关协议 + OpenAI 兼容传输 + langchain 桥接 |
| `app/tui/`(view/components/backend)| TUI 恢复 MVP(2026-08-13,E9~E11):视图逻辑只依赖 `TuiBackend` 端口,组件纯渲染可离线测 |
| `tools/shared/`(FsOps 等) | 工具层 hexagonal 重构(2026-08-13,E8):文件系统抽象缝 + cwd 注入 |
| `resources/` + `extensions/` | Pi 资源 / 扩展系统(延后档) |

## 11. 落地路线

| 阶段 | 范围 | 产物 |
|---|---|---|
| **v0.1 最小可跑** | `config + container + ai + tools + core + session(session+bus) + app(main/tui)` | CLI/TUI 可对话、可调用七个工具,事件流可订阅。进度:✅ 全部落地:`config` ✅、`ai` ✅(自研客户端)、`tools` ✅(7 工具 hexagonal)、`core` ✅(全异步 ReAct)、`session` ✅(bus+session+abort)、`container` ✅(graph/session/tui)、TUI ✅(MVP 恢复)、headless ✅。测试 266 全绿(2026-08-14 实测)。 |
| **v0.2 会话完善** | `store(线性) + manager + compaction(手动) + 解耦扫描重写 + TUI 命令体系` | 会话可恢复、可切换、可压缩;斜杠命令/模糊补全恢复 |
| **v0.3 资源扩展** | `resources/ + extensions/ + 分支 fork + langgraph.json` | 插件化、skills 按需加载、平台部署 |

v0.1 是最终结构树的**子集**,结构与定稿一致,延后目录先留空。

## 12. 参考

- 迭代记录:[`docs/iteration/v0.1.md`](../iteration/v0.1.md)(任务分解与变更记录 E1~E12,权威)
- [earendil-works/pi](https://github.com/earendil-works/pi) — Pi Agent SDK(三层协作 / 双层 loop / 事件驱动 / 会话即状态)
- [learning-pi-agent](https://github.com/yamsfeer/learning-pi-agent) — 架构深度笔记
- [how-pi-agent-works](https://github.com/myxiaoao/how-pi-agent-works) — 中文教学实现
- [LangGraph 文档](https://langchain-ai.github.io/langgraph/) — StateGraph / checkpointer / ToolNode
