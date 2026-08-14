# codeagent

基于 **LangGraph** 的编程 Agent,采用 Pi-Agent 的设计哲学(三层协作 / 双层 loop / 事件驱动 / 会话即状态),配合端口-适配器(hexagonal)做横切解耦。

当前处于 **v0.1 最小可跑**阶段:模型配置层(`ai/`)、Agent 编排(`core/`)、工具层(`tools/`)、会话层(`session/`)与终端交互层(`app/tui/`)均已落地,CLI 可对话、可调用 read / write / edit / bash / grep / find / ls 七个工具,事件流可订阅。

## 项目介绍

`codeagent` 的目标是构建一个可演进、可替换、可感知、可测试的编程 Agent:

- **可演进**:从单个工具调用型 Agent 平滑演进到多 Agent / 多会话 / 平台部署。
- **可替换**:更换模型供应商(DeepSeek / OpenAI / Qwen / GLM / Kimi / MiniMax)、更换工具集、更换存储,均不触碰 Agent 编排代码。
- **可感知**:会话运行过程以事件流对外暴露,CLI、TUI、Web、测试都能订阅,而不是只拿一个最终返回值。
- **可测试**:核心编排层零网络、零密钥即可运行(注入 `FakeClient` 离线假模型)。

设计参考:[earendil-works/pi](https://github.com/earendil-works/pi) 的"三层协作 / 双层 loop / 事件驱动 / 会话即状态"思想。架构设计见 [`docs/design/architecture.md`](docs/design/architecture.md),迭代记录见 [`docs/iteration/v0.1.md`](docs/iteration/v0.1.md)。

### 当前能力(v0.1)

- **交互式 TUI**(`--tui` 进入):终端操作记录界面——单行 composer 输入框、用户消息命令记录行、Agent 流式增量渲染、思维链弱化展示、工具调用块默认折叠可点击展开、状态栏 + 底部双端状态条(model · effort)、Esc 运行中打断 / 空闲退出并打印完整文档。
- **Headless CLI**(默认形态):`--prompt` 一次性输入或 stdin 逐行读取,事件聚合输出最终回复。
- **模型配置层**:每 provider 一个文件(配置 + 工厂自包含),内置模型目录 + `models.json` 按 id upsert 合并,支持思考强度(`model:effort`)与运行时换图(`replace_graph`)。
- **工具层(hexagonal)**:`AtomicTool` 无状态基类 + `FsOps` 文件系统抽象缝 + cwd 注入;read / write / edit / bash / grep / find / ls 七个工具;bash 带危险命令黑名单、树级进程击杀、默认 120s 超时、输出保尾截断。
- **离线可测**:`fake` provider + `FakeClient`,无需网络与密钥即可跑通全部测试(当前 255 passed)。

## 项目环境设置

### 前置要求

- **Python 3.12+**(见 [`.python-version`](.python-version))
- **[uv](https://docs.astral.sh/uv/)** 包管理器

### 安装依赖

```bash
# 安装项目依赖(含运行 TUI 所需的 textual / langgraph)
uv sync

# 如需开发环境(运行测试),安装 dev 依赖组
uv sync --group dev
```

### 配置环境变量

密钥统一写在**固定目录** `~/.codeagent/.env`(首次启动幂等生成模板,已存在的文件**不会被覆盖**)。项目**不读取**当前目录下的 `.env`(安全决策 H10:防止在任意仓库内运行时被其 `.env` 劫持流量与密钥)。

```ini
# 全局:选 provider(deepseek / openai / qwen / glm / kimi / minimax / fake)
LLM_PROVIDER=deepseek

# DeepSeek(DEEPSEEK_ 前缀自动映射到 DeepSeekConfig)
DEEPSEEK_API_KEY=sk-你的key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_REASONING_EFFORT=high
```

> **配置命名空间隔离**:`.env` 是共享文件,但全局 `Settings` 与各 provider 的 `Config` 各自解析、各自只认自己的键(全部配置类均设置 `extra="ignore"`)。切到其它 provider 时只需追加对应的 `*_API_KEY` 等键,无需改动其它。

### 自定义模型(可选)

用户可编辑 `~/.codeagent/models.json`,按 `id` 与内置目录 **upsert 合并**(同 id 覆盖、新 id 追加、内置保留):

```json
{
  "deepseek": {
    "models": [
      {
        "id": "deepseek-v4-pro",
        "reasoning": true,
        "maxTokens": 8192,
        "aliases": ["pro"]
      }
    ]
  }
}
```

## 项目启动方式

### 交互式 TUI

```bash
uv run codeagent --tui
```

启动后进入终端操作记录界面。交互规则:

| 输入 | 行为 |
|---|---|
| 普通文本 | 发送给 Agent,经 ReAct 循环执行(read/write/edit/bash/grep/find/ls)后流式回复 |
| `Esc`(运行中) | 打断当前回复(RUN_CANCELLED 回状态栏) |
| `Esc`(空闲) | 退出,并打印本次会话完整文档 |
| 点击工具调用块 | 折叠 / 展开(参数摘要 ↔ 全文) |

### Headless(默认形态)

```bash
# 一次性输入
uv run codeagent --prompt "你好"

# 从 stdin 逐行读取
echo "你好" | uv run codeagent

# 不配置任何 key 也可用 fake provider 测试:
# 将 .env 中 LLM_PROVIDER 改为 fake,或直接删除 .env 中的 key
```

### 运行测试

```bash
uv run pytest -q        # 当前 255 passed(全量离线,以实际运行结果为准)
```

## 项目结构

```
codeagent/
├── pyproject.toml / uv.lock     # 依赖、CLI 入口(codeagent = codeagent.app.main:main)
├── CLAUDE.md                    # Claude Code 工作指南(当前树的权威快速参考)
├── docs/
│   ├── design/                  # 需求分析 / 架构设计 / 演进蓝图
│   └── iteration/v0.1.md        # v0.1 迭代记录(权威)
├── openspec/                    # OpenSpec 规格与归档变更
│
└── src/codeagent/
    ├── app/                     # [组合根 + 入口] ★ 全项目唯一跨层交汇点
    │   ├── container.py         #   组合根:create_agent_graph / create_agent_session / create_tui_app
    │   ├── main.py              #   CLI 入口:--prompt / stdin / --tui
    │   ├── config.py            #   全局 Settings + ~/.codeagent 模板幂等生成
    │   └── tui/                 #   交互式终端(MVP)
    │       ├── view.py          #     TuiApp 视图逻辑(事件→渲染,只依赖 TuiBackend 端口)
    │       ├── components.py    #     纯渲染组件树(Span 样式标签段,引擎无关)
    │       ├── backend.py       #     TuiBackend 端口协议
    │       ├── textual_backend.py #   textual 引擎实现
    │       └── theme.py / main.py
    │
    ├── ai/                      # [模型配置层] 五层细分
    │   ├── factory.py           #   create_llm 统一构造入口 + get_available_providers
    │   ├── catalog/             #   ModelSpec / 内置目录 / models.json / 两遍解析注册表
    │   ├── protocol/            #   ChatClient 协议 + 自研 SSE 解析(thinking/usage 透传)
    │   ├── transport/           #   OpenAICompatClient(httpx,重试/流式)
    │   ├── bridge/              #   to_langchain_runnable(仅组合根消费)
    │   ├── providers/           #   每 provider 一个文件:deepseek/openai/qwen/glm/kimi/minimax/fake
    │   └── model_pattern.py     #   model:effort 解析唯一实现
    │
    ├── core/                    # [编排层] 零副作用,不 import config/tools/ai/session
    │   ├── ports.py             #   AgentPorts(编排认识的唯一外部世界)
    │   ├── state.py / loop.py   #   AgentState / build_graph 纯组装 + should_continue
    │   ├── events.py            #   EventType × 10 + AgentEvent
    │   └── nodes/               #   agent(astream 聚合)/ tools(按 call 粒度并行 + 兜底)
    │
    ├── session/                 # [会话层] 有状态会话壳
    │   ├── session.py           #   AgentSession:run(事件分发)/ abort / replace_graph / 失败回滚
    │   └── bus.py               #   EventBus:subscribe/emit,订阅方异常隔离
    │
    ├── tools/                   # [工具层] hexagonal
    │   ├── base.py / registry.py#   AtomicTool 基类 + make_tools 工厂
    │   ├── atomic/              #   read / write / edit / bash / grep / find / ls
    │   └── shared/              #   FsOps 抽象 / paths / textfile / truncate / mutation_queue / ignore
    │
    └── resources/ extensions/   # [资源/扩展层] 🔲 占位,延后 v0.2/v0.3

tests/                          # 按 src 模块镜像分包,255 个测试全绿(离线)
├── conftest.py                 #   _isolate_config_dir / fake_model / InMemoryFsOps 夹具
├── test_cli.py / test_config.py / test_container.py   # 应用层(拍平到根)
├── ai/                         #   factory / fake_client / model_store / providers / sse / transport / bridge
├── core/                       #   loop / events
├── session/                    #   session(事件 / thread 累积 / abort / 回滚)
├── tools/                      #   test_tools.py(单文件覆盖整个工具包)
└── tui/                        #   view / components
```

**分层依赖规则**:依赖单向流动,跨层 import 只允许出现在 `app/container.py` / `app/main.py`。判据:`core/` 中 grep 不到 `config / tools / ai / session` 字面量(当前人工遵守,自动扫描测试计划 v0.2 重写)。详见 [`docs/design/architecture.md`](docs/design/architecture.md) §8-9。

## 待完成的功能

当前 **v0.1 已打通闭环**(CLI/TUI 可对话、可调用七个工具、事件流可订阅),剩余增强:

1. **`session/` 会话完善**(v0.2):`SessionStore` 会话持久化、`SessionManager` 会话创建/切换/分叉、上下文压缩、`steer / followup`。
2. **解耦扫描测试重写**(v0.2 验收):按 `app/` 新分层重写 `test_decoupling.py`。
3. **TUI 增强**(v0.2):斜杠命令体系 / 模糊补全 / provider/model/effort 选择器、Agent 正文 Markdown 渲染、滚动与视口点击命中。
4. **`resources/` / `extensions/`**(v0.3):skills / prompts 按需加载、插件加载与钩子。
5. **平台部署**(v0.3):补全 `langgraph.json` 平台入口配置,与 CLI 共享同一份图定义。

## 未来展望

按 [`docs/design/architecture.md`](docs/design/architecture.md) §11 的落地路线:

| 阶段 | 范围 | 产物 |
|---|---|---|
| **v0.1 最小可跑** | `config + container + ai + tools + core + session(session+bus) + app(main/tui)` | CLI/TUI 可对话、可调用七工具,事件流可订阅 ✅ |
| **v0.2 会话完善** | `store(线性) + manager + compaction(手动) + TUI 命令体系` | 会话可恢复、可切换、可压缩 |
| **v0.3 资源扩展** | `resources/ + extensions/ + 分支 fork` | 插件化、skills 按需加载 |

更远期:多 Agent 协作、`langgraph.json` 平台部署(与 CLI 共享同一份图定义)、Web / API 暴露(事件流天然适配)。

## 参考

- [earendil-works/pi](https://github.com/earendil-works/pi) — Pi Agent SDK(三层协作 / 双层 loop / 事件驱动 / 会话即状态)
- [learning-pi-agent](https://github.com/yamsfeer/learning-pi-agent) — 架构深度笔记
- [how-pi-agent-works](https://github.com/myxiaoao/how-pi-agent-works) — 中文教学实现
- [LangGraph 文档](https://langchain-ai.github.io/langgraph/) — StateGraph / checkpointer / ToolNode
