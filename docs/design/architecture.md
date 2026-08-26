# codeagent 架构设计文档

> 版本: v0.3(阶段 1~4 落地后校准)
> 适用范围: 自研编排(2026-08-14 起,已弃用 langgraph/langchain)的 Code Agent 项目
> 更新日期: 2026-08-24(校准至 v0.3.0 当前树:自研 ReAct 主循环、JSONL 树形会话、安全确认环、Skills / MCP / token 用量 / 会话树、TUI 命令体系)
> 事实来源: 本文描述当前代码树;演进决策见 [self-built-orchestration-blueprint.md](./self-built-orchestration-blueprint.md)(决策与收益记录)、迭代记录 `docs/iteration/v0.1.md` / `v0.2.md` / `v0.3.md`

## 1. 背景与目标

本项目是基于**自研编排**的编程 Agent(codeagent)。设计目标:

1. **可演进**:从"单个工具调用型 Agent"平滑演进到多 Agent / 多会话 / 平台部署。
2. **可替换**:更换模型供应商(DeepSeek / OpenAI / Qwen / GLM / Kimi / MiniMax)、更换工具集、更换存储,均不触碰 Agent 编排代码。
3. **可感知**:会话的运行过程以事件流对外暴露,CLI、TUI、测试和 CI 都能订阅,而不是只拿一个最终返回值；Web/HTTP 订阅暂未实现。
4. **可测试**:核心编排层零网络、零密钥即可运行(注入 fake 模型)。

设计参考:Pi-Agent(`earendil-works/pi`)的"三层协作 / 双层 loop / 事件驱动 / 会话即状态"思想。

**编排演进**:v0.1 曾基于 langgraph(StateGraph / ToolNode / checkpointer)。2026-08-14 自研编排落地(`self-built-orchestration` change):自研 ReAct 主循环 + 消息归约 + JSONL 树形会话替换 langgraph,pyproject 移除 langchain-core/langgraph。当前树**无任何 langgraph/langchain 依赖**。

## 2. 设计原则:两条正交轴

整个结构由两条独立的分离轴合成,不要混淆:

| 轴 | 分的是什么 | 来源 |
|---|---|---|
| **横切轴:依赖方向** | config / 工具 / 编排 / 调用 之间谁认识谁 | 端口-适配器(hexagonal) |
| **纵切轴:生命周期** | 装配(Factory) / 单个对话(Session) / 会话生命周期(Runtime) | Pi-Agent 三层协作 |

- **横切轴**解决"零件怎么装":依赖单向流动,组合根是唯一交汇点。
- **纵切轴**解决"装好之后会话怎么活":三层生命周期不同、变化率不同,不该绑在一个类里。

**Loop 双层(无状态循环 / 有状态 Agent)是另一条正交结构**:无状态循环是 `core/loop.py` 的 `run_agent_loop` / `run_agent_loop_continue`，有状态内存外壳是 `core/agent.py` 的 `Agent`，而 `session/` 只补齐历史提交、落盘、压缩和 Session 事件。不要把它与横切/纵切混淆。

## 3. 现状

- 工具链:`uv` + `src` 布局,Python 3.12。
- 依赖:`httpx`、`mcp`、`pydantic`、`pydantic-settings`、`pyyaml`、`textual`;dev 依赖 `pytest`。**无 langchain/langgraph**。
- 入口:`pyproject.toml` 中 `codeagent = "codeagent.app.main:main"`。
- **已完成(v0.1~v0.3 阶段 1~4)**:
- 密钥外置:固定目录 `~/.codeagent/.env`(首次启动幂等生成模板),**不读取 CWD 下 `.env`**(安全决策 H10);全局 `Settings` 仅存 `llm_provider`。
- `ai/` 层:模型基础设施(provider / catalog / model / transport),**不负责应用装配**;支持 6 个真实 provider(deepseek / openai / qwen / glm / kimi / minimax)+ 离线 `fake`;模型客户端自研(httpx + 自研 SSE 解析,thinking / usage 全量透传);provider/model/effort 选择位于 `app/composition/model_selection.py`,适配自研循环的 `ChatModelPort` 在组合根。
- 工具层(hexagonal):`AtomicTool` 无状态基类 + `FsOps` 文件系统抽象缝 + cwd 注入;read / write / edit / bash / grep / find / ls / skill 八个内建工具;MCP 客户端可接入 `tools/list` / `tools/call`，以 `mcp__<server>__<tool>` 命名空间化，并实施全局 / 单 server / 描述长度分组预算;bash 带危险命令黑名单(字符串正则 + shlex 分词语义级检测)、树级进程击杀、默认 120s 超时(上限 600)、30k 输出截断;`tools/security.py` 提供执行前安全分类器(deny > ask > allow)。
- `core/` Agent Runtime:context / agent / loop / execution / ports / messages / events(纯内存、全异步),模块顶层零副作用。
- `session/` 会话层:bus + session + manager + store(JSONL 树形,含 usage entry)+ compaction + tree;`abort()` 运行中断、`steer()` 运行中注入、`followup()` 结束后续跑一轮、成功轮次才落盘、失败/取消内存回滚。
- 事件 11 类:`session_started / text_delta / thinking_delta / agent_message / tool_call / tool_result / turn_end / error / run_cancelled / usage / confirmation_requested`。
- 入口形态:`app/main.py` headless 双路径(`--prompt` / stdin)+ `--tui` 交互式终端(斜杠命令 / 模糊补全 / 选择器 / Markdown / 滚动 / `/login` / `/skills` / `/mcp` / `/tree` 等命令体系)。
- Skills 系统(v0.3 阶段 1~4):SKILL.md 格式 + 三源发现(内建 `resources/skills/` / 个人 `<config_dir>/skills/` / 项目 `<cwd>/.codeagent/skills/`)+ 渐进式披露(名称/描述入 system prompt,**正文经 `skill` 工具按需获取**)+ TUI `/skills` 手动加载。
- MCP(v0.3 阶段 2):用户级配置发现、工具 schema 适配、权限分类、`/mcp` 可见诊断与分组预算。
- token 用量透明(v0.3 阶段 3):usage 归一、会话级 append-only 落库、`/status` 与 headless CLI 展示输入 / 输出 / 缓存命中（不做费用估算）。
- 会话树(v0.3 阶段 4):`build_tree` 纯函数、`/tree` 导航及 `/sessions list` 父子缩进展示。
- 安全确认环(v0.2):执行前 `ApprovalPolicy`(组合根把 `tools/security.py` 分类器适配为端口),`ask` 由循环 emit `confirmation_requested` 并等待会话确认队列;headless 缺省 deny(fail closed),`--yes` 逃生舱。
- 测试基建:`tests/` 按 src 模块镜像分包 + `FakeClient`(离线假模型),`uv run pytest` **666 项收集，665 passed / 1 skipped，无失败**(2026-08-24 复核；唯一跳过项是 Windows 无符号链接权限；2026-08-21 综合审计的 12 条 CONFIRMED 缺陷已修复闭环,见 `docs/review/audit-2026-08-21.md` 与 v0.3 §6.5)。

**v0.3.0 验收与远期**:阶段 1~4 已落地，阶段 6 全量验收已完成。插件系统、轻量记忆及 Web/HTTP 事件流订阅均已移出 v0.3，待出现真实消费者或价值域扩大时重估。当前未配置覆盖率、静态检查、构建安装冒烟和发布门禁，这些属于下一阶段工程治理。

## 4. 总体结构

### 4.1 目录树

```text
codeagent/
├── pyproject.toml / uv.lock          # 依赖、CLI 入口(codeagent.app.main:main)
├── README.md / CLAUDE.md             # 说明 + Claude Code 工作指南
├── .env.example                      # 密钥模板(不入库;实际密钥在 ~/.codeagent/.env)
├── docs/                             # design/(需求/架构/蓝图)+ iteration/(权威)+ review/audit
├── openspec/                         # OpenSpec 规格与归档变更
│
├── src/codeagent/
│   ├── __init__.py / __main__.py     # 版本 + python -m codeagent
│   │
│   ├── app/                          # [组合根 + 入口] ★ 唯一跨层交汇点
│   │   ├── container.py              #   组合根:create_agent_config / create_agent_session
│   │   │                             #     / create_session_manager / create_tui_app
│   │   ├── main.py                   #   CLI 入口:--prompt / stdin / --tui
│   │   ├── config.py                 #   全局 Settings + ~/.codeagent 模板幂等生成
│   │   ├── agents.py                 #   AGENTS.md 分层加载 + 基础提示词
│   │   ├── skills.py                 #   SKILL.md 三源加载 / 提示词构建 / 渲染块
│   │   └── tui/                      #   [调用层·TUI] 交互式终端 ✅ 已落地
│   │       ├── view.py               #     TuiApp 视图逻辑(事件→渲染,只依赖 TuiBackend 端口)
│   │       ├── components.py         #     纯渲染组件树(样式标签段,引擎无关可离线测)
│   │       ├── backend.py            #     TuiBackend 端口协议
│   │       ├── commands.py           #     斜杠命令注册表 + 解析纯函数
│   │       ├── fuzzy.py              #     模糊补全纯函数
│   │       ├── md_renderer.py        #     Markdown 渲染纯函数
│   │       ├── theme.py              #     样式标签词表
│   │       ├── textual_backend.py    #     textual 引擎实现(当前唯一后端)
│   │       └── main.py               #     TUI 入口(--tui 转交此处,装配在组合根)
│   │
│   ├── ai/                           # [模型基础设施层]  ← pi-ai ✅ 已落地
│   │   ├── model/                    #   ChatClient / 消息 / 响应 / 工具 / 流事件契约
│   │   ├── catalog/                  #   模型目录与解析
│   │   │   ├── spec.py               #     ModelSpec(不可变值对象)
│   │   │   ├── builtin.py            #     内置模型目录(deepseek/openai/qwen/glm/kimi/minimax)
│   │   │   ├── store.py              #     models.json 读写(upsert 合并)
│   │   │   └── registry.py           #     ModelRegistry 两遍解析(精确 id → 别名)
│   │   ├── transport/                #   OpenAI 兼容传输层
│   │   │   ├── sse.py                 #     SSEParser(thinking/usage 全量透传)
│   │   │   └── openai_compat.py      #     OpenAICompatClient(httpx,重试/流式)
│   │   └── providers/                #   每 provider 一个文件,配置+工厂自包含
│   │       ├── deepseek.py / openai.py / qwen.py / glm.py / kimi.py / minimax.py
│   │       └── fake.py               #   FakeClient + make_llm(离线测试)
│   │
│   ├── core/                         # [Agent Runtime]  ← pi-agent-core ✅ 已落地
│   │   ├── context.py                #   AgentContext(纯内存上下文)
│   │   ├── agent.py                  #   Agent(prompt/continue/abort/steer/follow-up)
│   │   ├── loop.py                   #   run_agent_loop(+continue),返回本轮新增消息
│   │   ├── execution.py              #   共享工具执行器(并发/超时/取消/清理)
│   │   ├── ports.py                  #   AgentLoopConfig / AgentTool / 模型流端口
│   │   ├── messages.py               #   Agent Runtime 消息、ToolCall、ToolResult
│   │   └── events.py                 #   Agent 生命周期事件
│   │
│   ├── session/                      # [Session + Runtime]  ← Pi 核心增量 ✅ 已落地
│   │   ├── session.py                #   AgentSession: run / subscribe / abort / steer / followup
│   │   ├── manager.py                #   SessionManager: create / switch / fork / dispose
│   │   ├── store.py                  #   SessionStore(JSONL 树形,id/parentId)
│   │   ├── bus.py                    #   事件总线: subscribe/emit
│   │   └── compaction.py             #   上下文压缩(窗口摘要,纯函数)
│   │
│   ├── tools/                        # [工具层] hexagonal ✅ 已落地
│   │   ├── base.py                   #   AtomicTool 基类(Args pydantic schema → invoke)
│   │   ├── registry.py               #   make_tools 工厂(8 个内建工具,cwd/ops 注入)
│   │   ├── security.py               #   执行前安全分类器(classify_bash/file/tool)
│   │   ├── atomic/                   #   read / write / edit / bash / grep / find / ls / skill
│   │   ├── mcp/                      #   MCP client / loader / adapter / budget / config
│   │   └── shared/                   #   FsOps 抽象 / paths / textfile / truncate / mutation_queue / ignore
│   │
│   └── resources/                    # [资源层]  ← Pi 资源系统(v0.3 已启用 skills)
│       └── skills/ prompts/          #   *.md 技能文件 / 提示词模板
│
└── tests/                            # 按 src 模块镜像分包,666 项收集(665 passed / 1 skipped,2026-08-24 复核)
    ├── conftest.py                   # _isolate_config_dir / memory_fsops 夹具
    ├── test_cli.py / test_config.py / test_container.py / test_agents.py / test_skills.py
    ├── test_decoupling.py            # 分层解耦 AST 扫描(AST 强制校验)
    ├── ai/                           # model / fake_client / model_store / providers / sse / transport
    ├── core/                         # loop / messages / events
    ├── session/                      # session / store / manager / compaction
    ├── tools/                        # test_tools.py + test_security.py(单文件覆盖工具包)
    └── tui/                          # view / components / commands / fuzzy / md_renderer / textual_backend
```

### 4.2 模块职责一览

| 目录/文件 | 一句话职责 | 关键约束 |
|---|---|---|
| `app/container.py` | 组合根,创建端口 / 会话 / 会话管理器 / TUI 应用 | 全项目唯一 import 所有层的地方 |
| `app/main.py` | CLI 入口(--prompt / stdin / --tui) | 与 container 同为跨层 import 允许点 |
| `app/config.py` | 全局配置(仅 provider 无关字段)+ 模板生成 | 只被 container / ai 读取 |
| `app/agents.py` | AGENTS.md 分层加载 + 基础提示词 | 纯函数,可离线测 |
| `app/skills.py` | SKILL.md 三源加载 / 提示词构建 / 渲染块 | 纯函数,可离线测;三源同名遮蔽 个人>项目>内建 |
| `ai/` | 模型基础设施:模型契约、provider、transport、catalog | 不 import 应用、工具、编排 |
| `core/` | 纯内存 Agent Runtime:上下文、循环、工具执行、生命周期事件 | 不 import config / ai / tools / session |
| `session/` | AgentSession 外壳、事件适配、持久化、分支与压缩 | 不 import ai / tools / config |
| `tools/` | 工具层:原子工具 + 注册表 + 安全分类器 + 共享设施 | 不 import 模型、编排;`shared/` 只被 tools 内部使用 |
| `app/tui/` | 交互式终端(视图/组件/命令/后端端口) | view 只依赖 TuiBackend 端口;禁止 import textual(具体后端除外) |
| `resources/` | 技能 / 提示词按需加载 | v0.3 skills 已启用 |

### 4.3 配置命名空间(重要)

`~/.codeagent/.env` 是共享文件,但全局 `Settings` 与各 provider 的 `Config` **各自解析、各自只认自己的键**:

| 配置类 | 认的键 | 忽略 |
|---|---|---|
| `Settings`(全局) | `LLM_PROVIDER` 等 | `DEEPSEEK_*` / `OPENAI_*` |
| `DeepSeekConfig` | `DEEPSEEK_*`(env_prefix) | `LLM_PROVIDER` 等 |
| `OpenAIConfig` | `OPENAI_*`(env_prefix) | 其它 |

因此**所有配置类必须设置 `extra="ignore"`**,否则共享 `.env` 中任一命名空间的键都会让其它配置类报 `extra_forbidden`(实现时实际踩过,已修复并补防回归测试)。配置来源固定为 `~/.codeagent/.env`,不读 CWD 相对路径 `.env`(H10)。

## 5. 核心契约

### 5.1 AgentLoopConfig —— 编排认识外部世界的唯一窗口

```python
# core/ports.py
@dataclass
class AgentLoopConfig:
    model: ModelPort               # 模型端口(组合根适配 ai 层 ChatClient)
    tools: list[AgentTool]         # 统一 AgentTool 协议
    tool_runtime: ToolExecutionRuntimePort | None = None
    before_tool_call: Callable | None = None
```

**为什么 `model` 而不是 `model + tools` 绑定**:工具列表作为数据传入循环(循环按名查找 `invoke`),编排层不需要知道工具内部实现;加/换工具时 `core/` 零改动。

**`store` 不在端口内**:core 循环从不落盘(成功轮次才写由会话层负责),会话存储只经 `AgentSession` / `SessionManager` 注入(`session-manager` change 清理死字段)。

### 5.2 run_agent_loop —— 自研 ReAct 主循环

```python
# core/loop.py
async def run_agent_loop(context, config, prompt, *, emit=None, recursion_limit=50) -> list[Message]:
    # for 循环:模型 → 工具 → 继续/结束
    # 模型调用 stream/generate → emit(text_delta / thinking_delta / agent_message)
    # 有 tool_calls → 经 config.before_tool_call 决策 → 执行并回填结果
    # 无 tool_calls → 结束本轮
```

要点:
- 模块顶层**没有任何副作用**(不建模型、不发请求、不读 key),平台可直接 import。
- 循环条件由消息形状驱动(最后一条有没有 `tool_calls`),**不 import 任何具体工具**。
- 事件在循环内**直接 emit**(无翻译层),thinking / usage 事件原生化。
- `recursion_limit`(默认 50)是循环计数;`abort()` 抛 CancelledError 自然传播;工具执行 `asyncio.to_thread` + 超时。
- 安全策略经 `policy.decide` 在每个工具调用执行前调用。

### 5.3 AgentSession —— 有状态会话壳(单个对话)

```python
# session/session.py
class AgentSession:
    def __init__(self, config, bus, store=None, session_id=None,
                 recursion_limit=50, tool_timeout=None, summarizer=None): ...

    async def run(self, text) -> None: ...    # 直接驱动 run_agent_loop,发布事件,不返回值
    async def steer(self, text) -> None: ...  # 运行中注入消息
    async def followup(self) -> None: ...     # 结束后续跑一轮
    def subscribe(self, fn) -> Callable[[], None]: ...   # 订阅事件,返回退订函数
    def abort(self) -> None: ...              # 取消当前 run
```

- **`run` 发布事件流而不是返回单个回复**——CLI/TUI/测试/CI 都通过 `subscribe` 感知进度。
- **全异步**:`run()` 为 `async def`,直接驱动 `core/loop.py` 的 `run_agent_loop`,把循环内事件经 `EventBus` 分发。
- **成功才落盘**:本轮工作在局部历史副本上,`self._history` 仅成功时重赋值,store 循环在其后;失败/取消时内存回滚(历史从未被就地修改,回滚是空操作)。
- **会话历史**:自研 `Message`(role/content/tool_calls/tool_call_id/id/parentId),`id` 用 uuid7;归约按 tool_call_id 归属、按 id 删除。
- **事件类型(11 类)**:`session_started / text_delta / thinking_delta / agent_message / tool_call / tool_result / turn_end / error / run_cancelled / usage / confirmation_requested`。
- **上下文压缩**:`summarizer` 端口(session-compaction),自动/手动触发窗口摘要。

### 5.4 SessionManager / SessionStore —— 会话生命周期与持久化

```python
# session/manager.py + store.py
class SessionManager:
    def __init__(self, config, store=None, model="", effort="", ...): ...
    def create(self) -> SessionRef: ...
    def switch(self, session_id) -> None: ...
    def fork(self, session_id) -> SessionRef: ...   # 分支会话(JSONL 树形)
    def dispose(self, session_id) -> None: ...
    def replace_config(self, config, *, model, effort) -> None: ...   # 热切换

class SessionStore:
    # JSONL 树形:每轮 append 一条(含消息),重启可恢复;fork 只读源文件、新文件带 parentId
```

- `SessionStore`(JSONL 树形,`id`/`parentId`):会话可恢复、可切换、可分叉;MemoryStore 镜像同一语义,两个后端行为一致。
- `SessionManager` 薄管理器:ports 装配一次共享(模型端口 / 工具无状态,跨会话复用);`replace_config` 支持 /provider /model /effort 热切换。
- `fork`(v0.2 提前落地):只读源文件、新文件带 `parentSession`,按压缩切点拷贝保留窗口、父链重连。

## 6. 组合根:三层解耦的唯一交汇点

```python
# app/container.py
def create_agent_config(cfg=None, *, registry=None, reasoning_effort=None,
                       provider=None, model=None, approval_mode="deny") -> AgentLoopConfig:
    client = create_llm(cfg, registry=registry, reasoning_effort=reasoning_effort,
                        provider=provider, model=model)               # app.composition.model_selection.create_llm
    skills, _ = _load_skills(cfg)                                     # 技能一次加载两处消费
    rendered = {s.name: format_skill_invocation(s) for s in skills}
    config = AgentLoopConfig(
        model=ChatModelPort(client, system_prompt=_build_system_prompt(cfg, skills)),
        tools=create_tools(cfg, skills=rendered),                     # tools/registry.make_tools
    )
    # policy 由 composition/session 作为 before_tool_call 适配，不进入 core config
    return config

def create_agent_session(cfg=None, *, registry=None, store=None, session_id=None, ...) -> AgentSession:
    config = create_agent_config(cfg, registry=registry, ...)
    return AgentSession(config, EventBus(), store=store, session_id=session_id, ...)

def create_session_manager(cfg=None, *, store=None, ...) -> SessionManager: ...
def create_tui_app(cfg=None, *, backend=None, store=None, ...) -> TuiApp: ...
```

要点:

- `approval_mode`(`deny` / `interactive` / `allow`):headless 缺省 `deny`(ask 降级 deny,fail closed),TUI 传 `interactive`(ask 由确认条响应),`--yes` 传 `allow`。
- `store` 经 `AgentSession` / `SessionManager` 注入;**不进 `AgentLoopConfig`**(core 循环不落盘)。
- `registry` / `reasoning_effort` / `provider` / `model` 均可注入;`create_tui_app` 的 `rebuild_ports` 回调支持运行时热切换(/provider /model /effort /login)。
- `create_agent_config` 返回端口(平台 / 测试用);`create_agent_session` 供 CLI 入口消费。

## 7. 运行时生命周期

```
启动:   app/main.py → ensure_config_files() → create_agent_session()
        → create_agent_config:create_llm + _load_skills + _build_system_prompt + make_tools + _create_policy
        → AgentSession(config, bus, store)

一轮:   session.run(text)   [async]
        → run_agent_loop(config)
            → model.stream → emit(text_delta / thinking_delta / usage)
            → agent_message(有 tool_calls 则继续)
            → 逐个 tool_call → policy.decide(allow/ask/deny) → invoke → emit(tool_call / tool_result)
            → 无 tool_calls → turn_end
        → [成功] store.append(entry)   (失败/取消:内存回滚,不落盘)

TUI:    app/main.py --tui → create_tui_app() → TuiApp.start()
        → 订阅 AgentSession 事件 → TuiModel.apply 更新组件状态 → 合并渲染
        → 提交:session.run(text);Esc:运行中 abort / 空闲退出打印完整文档
        → /provider /model /effort → rebuild_ports() 热切换; /login → save_key() 写 .env + 热切换

干预:   abort() 中断当前 run;steer() 运行中注入消息;followup() 结束后续跑一轮
生命周期: manager.create() / switch() / fork() / dispose()
```

## 8. 依赖规则

| 模块 | 可以 import | 禁止 import |
|---|---|---|
| `app/config.py` | —(只被 container / ai 读取) | core、session、tools、app/tui |
| `ai` / `tools` | config(工具层内部:shared) | core、session |
| `core` | 只有 `ports.py`(及 core 内部) | config、ai、tools、session |
| `session` | core(ports/loop/events/messages)、bus | ai、tools、config |
| `app/container.py` | 全部(唯一交汇点) | — |
| `app/main.py` | container、session、bus | core、ai、tools(直接) |
| `app/tui/` | session、core(events)、theme | ai、tools、config;textual 仅 textual_backend |

## 9. 解耦判据(泄漏检测)

分层是否成立,不看文件多整齐,看**改一层要不要动另一层**:

| 变更 | 应动的文件 | 若还动了 | 结论 |
|---|---|---|---|
| 新增一个 provider | `ai/` + 环境变量 | `session.py` / `core/` | ❌ 泄漏 |
| 新增/更换一个工具 | `tools/` | `core/loop.py` / `ai/` | ❌ 泄漏 |
| 改编排形状(改循环) | `core/` | `ai/` / `tools/` | ❌ 泄漏 |
| 换会话存储 | `store.py` + `container` | `app/main.py` / `core/` | ❌ 泄漏 |
| 加会话分叉 | `session/` | `core/` | ❌ 泄漏 |

最严格判据:**`core/` 里 grep 不到 `config / tools / ai / session` 字面量 → 横切解耦成立;`session/` 里 grep 不到 `ai / tools / config` → 纵切解耦成立。**

> `tests/test_decoupling.py` 逐文件 AST 扫描强制校验(2026-08-14 重写,70+ 项断言),并带 anti-wargaming 守卫(`test_scan_has_content` / `test_composition_roots_exist` / `test_textual_only_in_engine_backend`),规则写错或例外文件被删都会被抓住。

## 10. 决策溯源

| 结构 | 对应讨论结论 |
|---|---|
| `app/container.py` + `app/config.py` | 组合根 + 配置层独立(2026-08-13 由顶层迁入 `app/` 包) |
| 自研编排(`core/loop.py` + `core/messages.py`) | 2026-08-14 `self-built-orchestration`:自研 ReAct 主循环 + 消息归约替换 langgraph;删除 `ai/bridge`、`core/state.py`、`core/nodes/`;pyproject 移除 langchain-core/langgraph(决策见 blueprint.md) |
| `core/` 端口(model / tools / policy) | 端口-适配器、编排层独立;`store` 不进端口(会话层负责落盘) |
| `session/`(session/manager/store/bus/compaction) | Pi 三层协作的 Session + Runtime、会话即状态;JSONL 树形(2026-08-14 格式结论) |
| `events.py` + `bus.py` | Pi 事件驱动,替代"返回单个 AIMessage";11 类事件 |
| `tools/security.py` + `ApprovalPolicy` | 2026-08-15 `security-permissions`:执行前安全策略,ask 确认环 + headless fail closed |
| `tools/`(AtomicTool + FsOps) | 2026-08-13 工具层 hexagonal 重构(E8):文件系统抽象缝 + cwd 注入 + 并发写锁 |
| `app/skills.py` + `skill` 工具 | 2026-08-19 `skills-system`:三源发现 + 渐进式披露(描述入 prompt,正文经 skill 工具按需获取) |
| `app/agents.py` | AGENTS.md 全局→项目→子目录分层加载(2026-08-15 `agents-md-hierarchy`) |
| `app/tui/`(view/components/backend) | TUI 恢复 MVP(2026-08-13,E9~E11)+ 命令体系 / 补全 / 选择器(2026-08-14)+ /login(2026-08-19) |
| `resources/` | Pi 资源系统（v0.3 skills 已启用；插件系统移出本迭代） |

## 11. 落地路线

| 阶段 | 范围 | 产物 |
|---|---|---|
| **v0.1 最小可跑** | `config + container + ai + tools + core + session + app(main/tui)` | CLI/TUI 可对话、可调用七个工具(当时集;v0.3 加 skill 后为八工具),事件流可订阅(历史记录) |
| **v0.2 会话完善** | 编排自研 + JSONL 树形 `SessionStore` + `SessionManager` + `compaction` + 安全确认环 + AGENTS.md + `/fork` + TUI 命令体系 | 会话可恢复、可切换、可压缩、可分叉;安全确认;命令/补全/选择器 |
| **v0.3 生态成型** | Skills(✅)+ MCP(✅)+ 成本透明(✅)+ 会话树 UI(✅);插件 / 轻量记忆 / Web 经评估移出(见 E5/E4/E12) | 扩展生态、体验差异、平台导航 |

v0.3.0 当前进度:阶段 1~4 已全部落地(Skills / MCP / token 用量透明 / 会话树);阶段 5 Web/HTTP 已移出(E12);阶段 6 全量验收已完成(T-64)。2026-08-24 复核结果:`uv run pytest -q` **666 collected / 665 passed / 1 skipped**（无失败，跳过原因是 Windows 无符号链接权限）、`openspec validate --specs` **9 passed**、`git diff --check` 通过。CI 已覆盖这些质量检查，但尚未覆盖构建、安装冒烟、覆盖率和静态检查。

## 12. 参考

- 编排自研决策与收益:[`self-built-orchestration-blueprint.md`](./self-built-orchestration-blueprint.md)
- 需求基线:[`requirements-analysis.md`](./requirements-analysis.md)(FR / NFR / F-xx 编号出处)
- 迭代记录:[`docs/iteration/v0.1.md`](../iteration/v0.1.md) / [`v0.2.md`](../iteration/v0.2.md) / [`v0.3.md`](../iteration/v0.3.md)(权威)
- 审计报告:[`docs/review/audit-2026-08-21.md`](../review/audit-2026-08-21.md)(文档漂移 / 安全 / 测试基线核查)
- [earendil-works/pi](https://github.com/earendil-works/pi) — Pi Agent SDK(三层协作 / 双层 loop / 事件驱动 / 会话即状态)
- [learning-pi-agent](https://github.com/yamsfeer/learning-pi-agent) — 架构深度笔记
- [how-pi-agent-works](https://github.com/myxiaoao/how-pi-agent-works) — 中文教学实现
