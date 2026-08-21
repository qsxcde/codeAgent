# codeagent

基于**自研编排**(2026-08-14 起,已弃用 langgraph/langchain)的编程 Agent,采用 Pi-Agent 的设计哲学(三层协作 / 双层 loop / 事件驱动 / 会话即状态),配合端口-适配器(hexagonal)做横切解耦。

当前处于 **v0.3 阶段 1**(生态成型):模型配置层(`ai/`)、自研 Agent 编排(`core/`)、工具层(`tools/`)、会话层(`session/`)与终端交互层(`app/tui/`)均已落地,CLI 可对话、可调用 read / write / edit / bash / grep / find / ls / skill 八个工具,事件流可订阅,会话可恢复 / 切换 / 压缩 / 分叉,Skills 技能系统已启用。

## 项目介绍

`codeagent` 的目标是构建一个可演进、可替换、可感知、可测试的编程 Agent:

- **可演进**:从单个工具调用型 Agent 平滑演进到多 Agent / 多会话 / 平台部署。
- **可替换**:更换模型供应商(DeepSeek / OpenAI / Qwen / GLM / Kimi / MiniMax)、更换工具集、更换存储,均不触碰 Agent 编排代码。
- **可感知**:会话运行过程以事件流对外暴露,CLI、TUI、Web、测试都能订阅,而不是只拿一个最终返回值。
- **可测试**:核心编排层零网络、零密钥即可运行(注入 `FakeClient` 离线假模型)。

设计参考:[earendil-works/pi](https://github.com/earendil-works/pi) 的"三层协作 / 双层 loop / 事件驱动 / 会话即状态"思想。架构设计见 [`docs/design/architecture.md`](docs/design/architecture.md),需求基线见 [`docs/design/requirements-analysis.md`](docs/design/requirements-analysis.md),迭代记录见 [`docs/iteration/v0.1.md`](docs/iteration/v0.1.md) / [`v0.2.md`](docs/iteration/v0.2.md) / [`v0.3.md`](docs/iteration/v0.3.md)。

### 当前能力(v0.3 阶段 1)

- **交互式 TUI**(`--tui` 进入):Codex 风格终端界面——无边框多行 composer(Enter 提交 / Shift+Enter 换行,1~4 行自动增高)、全宽用户消息块、圆点前缀的流式 Agent 正文、隐藏原始思维链与低频"思考中"提示、人类可读的工具摘要及可展开 edit/write 意图差异、model/effort/cwd 状态栏、斜杠命令体系(含 `/provider` `/model` `/effort` `/login` `/skills` `/sessions` `/tools` `/status` 等)与模糊补全 / 选择器、Markdown 渲染、Esc 运行中打断 / 空闲退出并打印完整文档。
- **Headless CLI**(默认形态):`--prompt` 一次性输入或 stdin 逐行读取,事件聚合输出最终回复。
- **自研编排引擎**:`core/loop.py` 的 `run_turn` 自研 ReAct 主循环(模型→工具→继续/结束,事件直接 emit),消息归约按 tool_call_id 归属(uuid7);零 langgraph/langchain 依赖。
- **会话层**:`SessionStore`(JSONL 树形,重启可恢复)+ `SessionManager`(create / switch / fork / dispose)+ 上下文压缩;成功轮次才落盘,失败/取消内存回滚;`abort` / `steer` / `followup`。
- **安全确认环**:执行前 `ApprovalPolicy`(bash 危险命令黑名单 + 语义级检测 + 文件访问边界三档 deny/ask/allow);headless 缺省 fail closed。
- **模型配置层**:每 provider 一个文件(配置 + 工厂自包含),内置模型目录 + `models.json` 按 id upsert 合并,支持思考强度(`model:effort`)与运行时热切换(/provider /model /effort /login)。
- **工具层(hexagonal)**:`AtomicTool` 无状态基类 + `FsOps` 文件系统抽象缝 + cwd 注入;read / write / edit / bash / grep / find / ls / skill 八个工具;bash 带危险命令黑名单、树级进程击杀、默认 120s 超时(上限 600)、输出保尾截断。
- **Skills 技能系统**:SKILL.md 格式 + 三源发现(内建 / 个人 / 项目)+ 渐进式披露(描述入 system prompt,**正文经 `skill` 工具按需获取**);`/skills` 手动加载。
- **离线可测**:`fake` provider + `FakeClient`,无需网络与密钥即可跑通全部测试(当前 598 项全绿)。

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
uv run pytest -q        # 全量离线测试(当前 598 项全绿,以实际运行结果为准)
```

## 项目结构

```text
codeagent/
├── pyproject.toml / uv.lock     # 依赖、CLI 入口(codeagent = codeagent.app.main:main)
├── CLAUDE.md                    # Claude Code 工作指南(当前树的权威快速参考)
├── docs/
│   ├── design/                  # 需求分析 / 架构设计 / 自研蓝图
│   ├── iteration/               # v0.1 / v0.2 / v0.3 迭代记录(权威)
│   └── review/                  # 审计报告
├── openspec/                    # OpenSpec 规格与归档变更
│
└── src/codeagent/
    ├── app/                     # [组合根 + 入口] ★ 全项目唯一跨层交汇点
    │   ├── container.py         #   组合根:create_agent_ports / create_agent_session
    │   │                        #     / create_session_manager / create_tui_app
    │   ├── main.py              #   CLI 入口:--prompt / stdin / --tui
    │   ├── config.py            #   全局 Settings + ~/.codeagent 模板幂等生成
    │   ├── agents.py            #   AGENTS.md 分层加载 + 基础提示词
    │   ├── skills.py            #   SKILL.md 三源加载 / 提示词构建 / 渲染块
    │   └── tui/                 #   交互式终端(命令/补全/选择器/Markdown)
    │
    ├── ai/                      # [模型配置层] 五层细分
    │   ├── factory.py           #   create_llm 统一构造入口
    │   ├── catalog/             #   ModelSpec / 内置目录 / models.json / 两遍解析注册表
    │   ├── protocol/            #   ChatClient 协议 + 自研 SSE 解析(thinking/usage 透传)
    │   ├── transport/           #   OpenAICompatClient(httpx,重试/流式)
    │   ├── providers/           #   每 provider 一个文件:deepseek/openai/qwen/glm/kimi/minimax/fake
    │   └── model_pattern.py     #   model:effort 解析唯一实现
    │
    ├── core/                    # [编排层] 零副作用,不 import config/tools/ai/session
    │   ├── ports.py             #   AgentPorts(model / tools / policy)
    │   ├── messages.py          #   自研消息模型 + 归约(按 tool_call_id 归属,uuid7)
    │   ├── loop.py              #   run_turn 自研 ReAct 主循环
    │   └── events.py            #   EventType × 11 + AgentEvent
    │
    ├── session/                 # [会话层] 有状态会话 + 持久化
    │   ├── session.py           #   AgentSession:run(事件分发)/ abort / steer / followup
    │   ├── manager.py           #   SessionManager:create / switch / fork / dispose
    │   ├── store.py             #   SessionStore(JSONL 树形,id/parentId)
    │   ├── bus.py               #   EventBus:subscribe/emit,订阅方异常隔离
    │   └── compaction.py        #   上下文压缩(窗口摘要)
    │
    ├── tools/                   # [工具层] hexagonal
    │   ├── base.py / registry.py#   AtomicTool 基类 + make_tools 工厂(8 工具)
    │   ├── security.py          #   执行前安全分类器(deny/ask/allow)
    │   ├── atomic/              #   read / write / edit / bash / grep / find / ls / skill
    │   └── shared/              #   FsOps 抽象 / paths / textfile / truncate / mutation_queue / ignore
    │
    └── resources/ extensions/   # [资源/扩展层]  skills 已启用(v0.3 阶段 1);插件 v0.3 阶段 2

tests/                          # 按 src 模块镜像分包,598 项全绿(离线)
├── conftest.py                 #   _isolate_config_dir / memory_fsops 夹具
├── test_cli.py / test_config.py / test_container.py / test_agents.py / test_skills.py
├── test_decoupling.py          #   分层解耦 AST 扫描(AST 强制校验)
├── ai/                         #   factory / fake_client / model_store / providers / sse / transport
├── core/                       #   loop / messages / events
├── session/                    #   session / store / manager / compaction
├── tools/                      #   test_tools.py + test_security.py
└── tui/                        #   view / components / commands / fuzzy / md_renderer / textual_backend
```

**分层依赖规则**:依赖单向流动,跨层 import 只允许出现在 `app/container.py` / `app/main.py`。判据:`core/` 中 grep 不到 `config / tools / ai / session` 字面量,由 `tests/test_decoupling.py` AST 扫描强制校验。详见 [`docs/design/architecture.md`](docs/design/architecture.md) §8-9。

## 待完成的功能

当前 **v0.3 阶段 1**(Skills)已落地,剩余按 [`docs/iteration/v0.3.md`](docs/iteration/v0.3.md) 推进:

1. **插件系统**(v0.3 阶段 2):`extensions/` 两阶段(注册→绑定),插件可注册工具与命令。
2. **MCP 客户端**(v0.3 阶段 3):外部工具接入(最小协议面 + 工具数分组预算)。
3. **轻量记忆**(v0.3 阶段 4):`~/.codeagent/memory` 跨会话偏好/事实。
4. **成本透明**(v0.3 阶段 5):usage 落库 + 费用估算 + 状态栏/事件流展示。
5. **会话树 UI**(v0.3 阶段 6):fork 链导航(`/tree` 或 `/sessions` 父子展示增强)。
6. **Web / HTTP 事件订阅**(v0.3 阶段 7):SSE 订阅 + 会话 create/run/subscribe 闭环(F-27,承接 v0.2 平台部署改写决策)。

## 参考

- [earendil-works/pi](https://github.com/earendil-works/pi) — Pi Agent SDK(三层协作 / 双层 loop / 事件驱动 / 会话即状态)
- [learning-pi-agent](https://github.com/yamsfeer/learning-pi-agent) — 架构深度笔记
- [how-pi-agent-works](https://github.com/myxiaoao/how-pi-agent-works) — 中文教学实现
