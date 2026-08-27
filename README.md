# codeagent

基于**自研编排**(2026-08-14 起,已弃用 langgraph/langchain)的编程 Agent,采用 Pi-Agent 的设计哲学(三层协作 / 双层 loop / 事件驱动 / 会话即状态),配合端口-适配器(hexagonal)做横切解耦。

当前 **v0.3.0 已完成验收**:阶段 1~4（Skills、MCP、token 用量透明、会话树 UI）已落地，阶段 6 全量验收已闭环。模型配置层(`ai/`)、自研 Agent 编排(`core/`)、工具层(`tools/`)、会话层(`session/`)与终端交互层(`app/tui/`)均可用；CLI 可对话、可调用 8 个内建工具与按配置加载的 MCP 工具，事件流可订阅，会话可恢复 / 切换 / 压缩 / 分叉 / 树形导航。

当前验收基线（2026-08-27）：`uv run pytest -q` **944 passed**。测试已完成分层与结构迁移；CI 已配置快速质量门禁、Ubuntu/Windows/macOS 离线矩阵、构建后安装冒烟和非阻塞性能报告。Ruff 首阶段只检查阻塞级正确性问题，不把历史风格债务混入本次变更。

## 项目介绍

`codeagent` 的目标是构建一个可演进、可替换、可感知、可测试的编程 Agent:

- **可演进**:从单个工具调用型 Agent 平滑演进到多 Agent / 多会话 / 平台部署。
- **可替换**:更换模型供应商(DeepSeek / OpenAI / Qwen / GLM / Kimi / MiniMax)、更换工具集、更换存储,均不触碰 Agent 编排代码。
- **可感知**:会话运行过程以事件流对外暴露,CLI、TUI、测试和 CI 都能订阅,而不是只拿一个最终返回值。
- **可测试**:核心编排层零网络、零密钥即可运行(注入 `FakeClient` 离线假模型)。

设计参考:[earendil-works/pi](https://github.com/earendil-works/pi) 的"三层协作 / 双层 loop / 事件驱动 / 会话即状态"思想。架构设计见 [`docs/design/architecture.md`](docs/design/architecture.md),需求基线见 [`docs/design/requirements-analysis.md`](docs/design/requirements-analysis.md),迭代记录见 [`docs/iteration/v0.1.md`](docs/iteration/v0.1.md) / [`v0.2.md`](docs/iteration/v0.2.md) / [`v0.3.md`](docs/iteration/v0.3.md)。

### 当前能力(v0.3.0)

- **交互式 TUI**(`--tui` 进入):Codex 风格终端界面——无边框多行 composer(Enter 提交 / Shift+Enter 换行,1~4 行自动增高)、全宽用户消息块、圆点前缀的流式 Agent 正文、隐藏原始思维链与低频"思考中"提示、人类可读的工具摘要及可展开 edit/write 意图差异、model/effort/cwd 状态栏、斜杠命令体系(含 `/provider` `/model` `/effort` `/login` `/skills` `/mcp` `/sessions` `/tree` `/tools` `/status` `/quit`)与模糊补全 / 选择器、Markdown 渲染、Esc 运行中打断 / 空闲退出并打印完整文档。
- **Headless CLI**(默认形态):`--prompt` 一次性输入或 stdin 逐行读取,事件聚合输出最终回复。
- **自研编排引擎**:`core/agent.py` 的纯内存 `Agent` 外壳与 `core/loop.py` 的 `run_agent_loop`/`run_agent_loop_continue` 驱动 ReAct（模型→工具→继续/结束）；Session 只负责持久化、压缩和会话事件，零 langgraph/langchain 依赖。
- **会话层**:`SessionStore`(JSONL 树形,重启可恢复,含用量累计)+ `SessionManager`(create / switch / fork / dispose)+ 上下文压缩;成功轮次才落盘,失败/取消内存回滚;`abort` / `steer` / `followup`;`/tree` 和 `/sessions list` 提供分叉树导航。
- **安全确认环**:执行前 `ApprovalPolicy`(bash 危险命令黑名单 + 语义级检测 + 文件访问边界三档 deny/ask/allow);headless 缺省 fail closed。
- **模型配置层**:每 provider 一个文件(配置 + 工厂自包含),内置模型目录 + `models.json` 按 id upsert 合并,支持思考强度(`model:effort`)与运行时热切换(/provider /model /effort /login)。
- **工具层(hexagonal)**:`AtomicTool` 无状态基类 + `FsOps` 文件系统抽象缝 + cwd 注入;read / write / edit / bash / grep / find / ls / skill 八个内建工具;MCP 客户端可按用户配置接入 `tools/list` / `tools/call` 工具，并以 `mcp__<server>__<tool>` 命名空间化和分组预算控制提示词膨胀。
- **Skills 技能系统**:SKILL.md 格式 + 三源发现(内建 / 个人 / 项目)+ 渐进式披露(描述入 system prompt,**正文经 `skill` 工具按需获取**);`/skills` 手动加载。
- **用量透明**:归一并累计输入 / 输出 / 推理 / 缓存命中 token；`/status` 与 headless CLI 展示会话或本轮用量（不估算费用）。
- **离线可测**:`fake` provider + `FakeClient`,无需网络与密钥即可跑通全部测试；测试分层和 CI 命令见 [`docs/testing.md`](docs/testing.md)。

## 项目环境设置

### 前置要求

- **Python 3.12+**(见 [`.python-version`](.python-version))
- **[uv](https://docs.astral.sh/uv/)** 包管理器

### 安装依赖

```bash
# 安装项目依赖(含运行 TUI 所需的 textual)
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

### Skills(可选)

技能文件三源发现:内建 `resources/skills/<name>/SKILL.md`、个人 `<config_dir>/skills/<name>/SKILL.md`、项目 `<cwd>/.codeagent/skills/<name>/SKILL.md`;同名遮蔽 **个人 > 项目 > 内建**。技能描述注入 system prompt,正文经 `skill` 工具按需获取(`/skills` 可查看与手动加载)。

## 项目启动方式

### 交互式 TUI

```bash
uv run codeagent --tui
```

启动后进入终端操作记录界面。交互规则:

| 输入 | 行为 |
| --- | --- |
| 普通文本 | 发送给 Agent,经 ReAct 循环执行(read/write/edit/bash/grep/find/ls/skill)后流式回复 |
| `/provider` `/model` `/effort` | 热切换模型配置(选择器 + 模糊补全) |
| `/login` | 配置/保存 provider API key(写回 `~/.codeagent/.env` 并热切换) |
| `/skills` | 列出可用技能;`/skills <name>` 手动加载并立即触发一轮回复 |
| `/sessions` `/fork` | 会话列表与切换 / 分支会话(JSONL 树形) |
| `Esc`(运行中) | 打断当前回复(RUN_CANCELLED 回状态栏);敏感命令按确认条放行/拒绝 |
| `Esc`(空闲) | 退出,并打印本次会话完整文档 |
| 点击工具调用块 | 折叠 / 展开;edit/write 显示红绿意图差异,其它工具显示完整结果 |

### Headless(默认形态)

```bash
# 一次性输入
uv run codeagent --prompt "你好"

# 从 stdin 逐行读取
echo "你好" | uv run codeagent

# 不配置任何 key 也可用 fake provider 测试:
# 将 .env 中 LLM_PROVIDER 改为 fake,或直接删除 .env 中的 key

# 危险/敏感命令默认 fail closed(--yes 显式放行):
uv run codeagent --prompt "删除全部文件"      # deny,不执行
uv run codeagent --yes --prompt "..."        # 显式承担风险
```

### 运行测试

```bash
uv run pytest -q        # 全量离线测试(结果以实际运行结果为准)

uv run ruff check src tests scripts  # 基础正确性静态检查

# 运行 TUI 离线性能基准(结果只包含指标与环境元数据)
uv run python scripts/benchmark_tui.py --scenario stream --blocks 100 --stream-chars 10000 --iterations 3
```

## 项目结构

```text
codeagent/
├── pyproject.toml / uv.lock     # 依赖、CLI 入口(codeagent = codeagent.app.main:main)
├── CLAUDE.md                    # Claude Code 工作指南(当前树的权威快速参考)
├── docs/
│   ├── design/                  # 需求分析 / 架构设计 / 自研蓝图
│   ├── iteration/               # v0.1 / v0.2 / v0.3 / v0.4 迭代记录(权威)
│   ├── testing.md               # 测试分层、CI、覆盖率和安装冒烟
│   └── benchmarks/              # TUI 性能基线与优化记录
│   └── review/                  # 审计报告
├── openspec/                    # OpenSpec 规格与归档变更
│
└── src/codeagent/
    ├── app/                     # [组合根 + 入口] ★ 全项目唯一跨层交汇点
    │   ├── container.py         #   组合根:create_agent_config / create_agent_session
    │   │                        #     / create_session_manager / create_tui_app
    │   ├── main.py              #   CLI 入口:--prompt / stdin / --tui
    │   ├── config.py            #   全局 Settings + ~/.codeagent 模板幂等生成
    │   ├── agents.py            #   AGENTS.md 分层加载 + 基础提示词
    │   ├── skills.py            #   SKILL.md 三源加载 / 提示词构建 / 渲染块
    │   ├── composition/         #   provider、runtime、tool、session、TUI 组合工厂
    │   └── tui/                 #   交互式终端(状态、协调器、渲染、命令、后端)
    │
    ├── ai/                      # [模型基础设施层] 模型、provider、transport、目录
    │   ├── model/               #   ChatClient / 消息 / 响应 / 工具 / 流事件契约
    │   ├── catalog/             #   ModelSpec / 内置目录 / models.json / 两遍解析注册表
    │   ├── transport/            #   SSEParser + OpenAICompatClient(httpx,重试/流式)
    │   └── providers/            #   每 provider 一个文件:deepseek/openai/qwen/glm/kimi/minimax/fake
    │
    ├── core/                    # [Agent Runtime] 纯内存,不 import config/tools/ai/session
    │   ├── agent.py             #   Agent:prompt / continue / abort / steer / follow-up
    │   ├── context.py           #   AgentContext:运行期消息与工具
    │   ├── loop.py              #   run_agent_loop(+continue):本轮新增消息
    │   ├── execution.py         #   共享工具执行器:并发/超时/取消/清理
    │   ├── ports.py             #   AgentLoopConfig / AgentTool / 模型流端口
    │   ├── messages.py          #   Agent Runtime 消息、ToolCall、ToolResult
    │   └── events.py            #   Agent 生命周期事件
    │
    ├── session/                 # [会话层] Agent 外壳 + 持久化/压缩/事件适配
    │   ├── session.py           #   AgentSession:run(事件分发)/ abort / steer / followup
    │   ├── manager.py           #   SessionManager:create / switch / fork / dispose
    │   ├── persistence/         #   JSONL/MemoryStore、索引、锁、记录模型
    │   ├── runtime/             #   运行控制、确认、事件映射、错误策略
    │   ├── compaction/          #   上下文压缩策略与摘要
    │   ├── events/              #   EventBus:subscribe/emit
    │   └── navigation/          #   会话树与分支导航
    │
    ├── tools/                   # [工具层] hexagonal
    │   ├── base.py / registry.py#   AtomicTool 基类 + make_tools 工厂(8 个内建工具)
    │   ├── security/            #   执行前安全分类器(deny/ask/allow)
    │   ├── atomic/              #   read / write / edit / bash / grep / find / ls / skill
    │   ├── mcp/                 #   MCP client / loader / adapter / budget / config
    │   └── shared/              #   FsOps 抽象 / paths / textfile / truncate / mutation_queue / ignore
    │
    └── resources/               # [资源层] 内建 skills / prompts（Skills 已启用）

tests/                          # 按行为域分包，944 passed（2026-08-27）
├── conftest.py / fixtures/     #   marker、隔离环境和共享离线夹具
├── contracts/                  #   跨实现公共契约与分层边界
├── ai/ / core/ / mcp/          #   模型、编排和 MCP 行为
├── app/container/              #   组合根装配与生命周期
├── session/store/               #   JSONL、MemoryStore 和索引
│   └── behavior/               #   运行、恢复、取消、确认、压缩和用量
├── tools/atomic/                #   原子工具；execution/security 独立
└── tui/view/                    #   TUI 生命周期、命令、会话、状态和扩展
```

**分层依赖规则**:依赖单向流动,跨层 import 只允许出现在 `app/container.py` / `app/main.py`。判据:`core/` 中 grep 不到 `config / tools / ai / session` 字面量,由 `tests/test_decoupling.py` AST 扫描强制校验。详见 [`docs/design/architecture.md`](docs/design/architecture.md) §8-9。

**运行时边界**：`core` 只执行内存 Agent Runtime；模型 provider 的消息/参数转换由 `app/composition/model_factory.py` 完成，Atomic/MCP 工具由组合根适配为 `AgentTool`，Memory 通过 `transform_context`、安全确认通过 `before_tool_call` 注入。Skill 文件、MCP 客户端、JSONL、压缩和会话树不进入 core 主循环。

## 当前状态与后续

v0.3.0 已完成 Skills、MCP、token 用量透明、会话树导航及全量验收，详见 [`docs/iteration/v0.3.md`](docs/iteration/v0.3.md)。当前未实现且已明确移出本版本的能力包括：费用估算、Web / HTTP 事件订阅、轻量记忆、插件系统、多智能体和自动化任务；它们在出现真实需求后重新评估。

工程后续优先级是补充 Hooks 与完成前验证门禁、积累跨平台性能数据并评估硬门槛、构建/安装冒烟测试和发布流程。性能基线在 CI 数据稳定前保持非阻塞。

## 参考

- [earendil-works/pi](https://github.com/earendil-works/pi) — Pi Agent SDK(三层协作 / 双层 loop / 事件驱动 / 会话即状态)
- [learning-pi-agent](https://github.com/yamsfeer/learning-pi-agent) — 架构深度笔记
- [how-pi-agent-works](https://github.com/myxiaoao/how-pi-agent-works) — 中文教学实现
