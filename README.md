# codeagent

基于 **LangGraph** 的编程 Agent,采用 Pi-Agent 的设计哲学(三层协作 / 双层 loop / 事件驱动 / 会话即状态),配合端口-适配器(hexagonal)做横切解耦。

当前处于 **v0.1 最小可跑**阶段:模型配置层(`ai/`)、Agent 编排(`core/`)、工具层(`tools/`)、会话层(`session/`)与终端交互层(`tui/`)均已落地,CLI 可对话、可调用 read/write/edit/bash 工具。

## 项目介绍

`codeagent` 的目标是构建一个可演进、可替换、可感知、可测试的编程 Agent:

- **可演进**:从单个工具调用型 Agent 平滑演进到多 Agent / 多会话 / 平台部署。
- **可替换**:更换模型供应商(DeepSeek / OpenAI / 本地)、更换工具集、更换存储,均不触碰 Agent 编排代码。
- **可感知**:会话运行过程以事件流对外暴露,CLI、Web、测试都能订阅,而不是只拿一个最终返回值。
- **可测试**:核心编排层零网络、零密钥即可运行(注入 `FakeClient` 离线假模型)。

设计参考:[earendil-works/pi](https://github.com/earendil-works/pi) 的"三层协作 / 双层 loop / 事件驱动 / 会话即状态"思想。完整架构设计见 [`docs/architecture.md`](docs/architecture.md)。

### 当前能力(v0.1)

- **Claude 风格 TUI**:透明背景 + 白色圆角输入框、命令浮层、输入框下侧状态栏。
- **斜杠命令**:输入 `/` 弹出模糊命令列表,`↑/↓` 选择后先**填入输入框**,补全参数回车执行;`//` 转义可发送以 `/` 开头的内容。
- **模型配置层**:每 provider 一个文件(配置 + 工厂自包含),内置模型目录 + `models.json` 按 id upsert 合并,支持运行时思考强度切换(`model:effort`)。
- **离线可测**:`fake` provider + `FakeClient`,无需网络与密钥即可跑通全部测试(当前 304 passed)。

## 项目环境设置

### 前置要求

- **Python 3.12+**(见 [`.python-version`](.python-version))
- **[uv](https://docs.astral.sh/uv/)** 包管理器

### 安装依赖

```bash
# 安装项目依赖(含运行 TUI 所需的 textual / langchain-openai / langgraph)
uv sync

# 如需开发环境(运行测试),安装 dev 依赖组
uv sync --group dev
```

### 配置环境变量

首次启动会自动创建 `~/.codeagent/` 目录,并生成 `.env` / `models.json` 模板(幂等:已存在的文件**不会被覆盖**,请放心编辑)。

```bash
# 手动方式(可选):复制示例配置
cp .env.example ~/.codeagent/.env
```

编辑 `~/.codeagent/.env`,至少填写所选 provider 的 API Key。该文件不会被 git 追踪,不会入库。

```ini
# 全局:选 provider(deepseek / openai / qwen / glm / kimi / minimax / fake)
LLM_PROVIDER=deepseek

# DeepSeek(DEEPSEEK_ 前缀自动映射到 DeepSeekConfig)
DEEPSEEK_API_KEY=sk-你的key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_REASONING_EFFORT=high
```

> **配置命名空间隔离**:`.env` 是共享文件,但全局 `Settings` 与各 provider 的 `Config` 各自解析、各自只认自己的键(全部配置类均设置 `extra="ignore"`)。切到 OpenAI 时只需追加 `OPENAI_API_KEY` 等 `OPENAI_*` 键,无需改动其它。

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

### 交互式 TUI(默认)

```bash
uv run codeagent
# 或
uv run python -m codeagent
```

启动后进入 Claude 风格终端界面。交互规则:

| 输入 | 行为 |
|---|---|
| 普通文本 | 发送给 Agent,经 ReAct 循环执行(read/write/edit/bash)后流式回复 |
| `/` | 弹出模糊命令列表,`↑/↓` 选择,回车**填入输入框**,补参数后再回车执行 |
| `//hello` | 转义,发送字面量 `/hello` |
| `Ctrl+L` | 聚焦输入框 |
| `Ctrl+Q` | 退出 |

### 斜杠命令

| 命令 | 别名 | 说明 |
|---|---|---|
| `/help [cmd]` | `h` `?` | 显示命令帮助 |
| `/clear` | `c` | 清空对话 |
| `/quit` | `q` `exit` | 退出 |
| `/status` | `st` | 显示当前 provider / model / effort |
| `/provider [name]` | `p` | 切换供应商 |
| `/model [name[:effort]]` | `m` | 切换模型,支持 `:high` 内联思考强度 |
| `/effort [low|medium|high]` | `e` | 设置思考强度 |
| `/tools` | `t` | 显示已实现工具列表(read / write / edit / bash) |
| `/session` | `s` | 显示会话状态(会话级上下文累积已启用) |

### 无界面模式(Headless)

```bash
# 一次性输入
uv run codeagent --headless --prompt "你好"

# 从 stdin 逐行读取
echo "你好" | uv run codeagent --headless

# 不配置任何 key 也可用 fake provider 测试:
# 将 .env 中 LLM_PROVIDER 改为 fake,或直接删除 .env 中的 key
```

### 运行测试

```bash
uv run pytest -q        # 当前 304 passed(以实际运行结果为准)
```

## 项目结构

```
codeagent/
├── pyproject.toml / uv.lock     # 依赖、CLI 入口(codeagent = codeagent.cli:main)
├── .env.example / .env          # 环境变量模板 / 密钥(不入库)
├── docs/architecture.md         # 架构设计文档(两条分离轴、核心契约、依赖规则)
│
└── src/codeagent/
    ├── cli.py                   # [调用层入口] argv 解析 + --headless,启动 TUI
    ├── container.py             # [组合根 / Factory] ★ 全项目唯一跨层交汇点
    ├── config.py                # [配置层] 全局 Settings(仅 provider 无关字段)
    ├── model_pattern.py         # [跨层共享] model:effort 解析 + KNOWN_EFFORTS 白名单
    │
    ├── tui/                     # [调用层·TUI] ✅ 已落地
    │   ├── ports.py             #   AgentClient 端口协议(tui 只认这里)
    │   ├── agent_client.py      #   AgentClientBase + PlaceholderAgentClient(状态维护 + 默认 respond)
    │   ├── session_client.py    #   SessionAgentClient: 事件流→StreamChunk 翻译
    │   ├── messages.py          #   StreamChunk / StreamKind / MessageKind
    │   ├── commands.py          #   斜杠命令注册表 + 校验 + 解析
    │   ├── fuzzy.py             #   轻量模糊匹配(命令过滤)
    │   ├── pickers.py           #   provider/model/effort 选择器
    │   ├── state.py             #   RunState / TuiState
    │   ├── widgets.py           #   转录区 / 命令浮层 / 状态栏
    │   ├── app.py               #   TuiApp(唯一 import Textual 处)
    │   └── app.css              #   Claude 风格样式
    │
    ├── ai/                      # [模型配置层] ✅ 已落地
    │   ├── factory.py           #   create_llm 统一构造入口 + get_available_providers
    │   ├── catalog/             #   模型目录与解析
    │   │   ├── spec.py          #     ModelSpec(不可变值对象)
    │   │   ├── builtin.py       #     内置模型目录(deepseek/openai/qwen/glm/kimi/minimax)
    │   │   ├── store.py         #     models.json 读写(upsert 合并)
    │   │   └── registry.py      #     ModelRegistry 两遍解析(精确 id → 别名)
    │   ├── protocol/            #   框架无关协议层
    │   │   ├── messages.py      #     ChatClient 协议 / ChatMessage / ToolCall / ChatResponse
    │   │   └── sse.py           #     StreamEvent / SSEParser(thinking/usage 全量透传)
    │   ├── transport/           #   OpenAI 兼容传输层
    │   │   └── openai_compat.py #     OpenAICompatClient(httpx,重试/流式)
    │   ├── bridge/              #   langchain 编排桥接(仅组合根消费)
    │   │   └── langchain.py     #     to_langchain_ai_message / to_langchain_runnable
    │   └── providers/           #   每 provider 一个文件,配置 + 工厂自包含
    │       ├── deepseek.py / openai.py / qwen.py / glm.py / kimi.py / minimax.py
    │       └── fake.py          #   FakeClient + make_llm(离线测试)
    │
    ├── core/                    # [编排层] ✅ 已落地
    │   ├── ports.py             #   AgentPorts(编排认识的唯一外部世界)
    │   ├── state.py             #   AgentState
    │   ├── loop.py              #   build_graph(ports) 纯组装 + 条件边
    │   ├── events.py            #   AgentEvent 类型
    │   └── nodes/               #   agent / tools 节点
    │
    ├── session/                 # [Session + Runtime] ✅ 已落地
    │   ├── session.py           #   AgentSession: run / subscribe / run_sync
    │   └── bus.py               #   事件总线: subscribe/emit
    │
    ├── tools/                   # [工具层] ✅ 已落地
    │   ├── base.py / registry.py #   AtomicTool 基类 + make_tools 注册表
    │   └── atomic/              #   read / write / edit / bash
    │
    ├── resources/               # [资源层] 🔲 延后(目录已建)
    │   └── skills/ prompts/     #   技能 / 提示词按需加载(渐进式披露)
    │
    └── extensions/              # [扩展层] 🔲 延后(目录已建)
        └── __init__.py          #   插件扩展占位

tests/                          # 按 src 模块镜像分包,304 个测试全绿
├── conftest.py                 #   fake_model / settings 夹具
├── test_cli.py / test_config.py / test_container.py / test_decoupling.py   # 调用层与应用层
├── ai/                         #   factory / fake_client / model_store / providers / sse / transport / bridge
├── core/                       #   loop(假 ports 跑通整个图)
├── session/                    #   session(事件 / thread 累积 / run_sync)
├── tools/                      #   tools(原子工具 + 黑名单 + 退出码语义)
└── tui/                        #   app_picker / app_commands / app_streaming / session_client / tui_widgets / commands / fuzzy / agent_client
```

**分层依赖规则**:依赖单向流动,跨层 import 只允许出现在 `container.py` / `cli.py`。已有 `tests/test_decoupling.py` 强制校验:`tui/` 源码不得 import `config / ai / session / core / tools`。详见 [`docs/architecture.md`](docs/architecture.md) §8-9。

## 待完成的功能

当前 **v0.1 已打通闭环**(CLI 可对话、可调用 read/write/edit/bash 工具),剩余增强:

1. **`session/` 会话完善**(v0.2):`SessionStore` 会话持久化、`SessionManager` 会话创建/切换/分叉、上下文压缩。
2. **`resources/` 资源扩展**(v0.3):skills / prompts 按需加载(渐进式披露)。
3. **`extensions/` 扩展层**(v0.3):插件加载与钩子(注册→绑定)。
4. **平台部署**:补全 `langgraph.json` 平台入口配置,与 CLI 共享同一份图定义。

## 未来展望

按 [`docs/architecture.md`](docs/architecture.md) §11 的落地路线:

| 阶段 | 范围 | 产物 |
|---|---|---|
| **v0.1 最小可跑** | `config + container + ai + tools + core + session(session+bus) + cli` | CLI 可对话、可调用 read/write/edit/bash,事件可打印 |
| **v0.2 会话完善** | `store(线性) + manager + compaction(手动)` | 会话可恢复、可切换、可压缩 |
| **v0.3 资源扩展** | `resources/ + extensions/ + 分支 fork` | 插件化、skills 按需加载 |

更远期:多 Agent 协作、`langgraph.json` 平台部署(与 CLI 共享同一份图定义)、Web / API 暴露(事件流天然适配)。

## 参考

- [earendil-works/pi](https://github.com/earendil-works/pi) — Pi Agent SDK(三层协作 / 双层 loop / 事件驱动 / 会话即状态)
- [learning-pi-agent](https://github.com/yamsfeer/learning-pi-agent) — 架构深度笔记
- [how-pi-agent-works](https://github.com/myxiaoao/how-pi-agent-works) — 中文教学实现
- [LangGraph 文档](https://langchain-ai.github.io/langgraph/) — StateGraph / checkpointer / ToolNode
