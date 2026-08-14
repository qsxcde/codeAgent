# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

基于 **LangGraph** 的编程 Agent(codeagent),采用 Pi-Agent 设计哲学(三层协作 / 双层 loop / 事件驱动 / 会话即状态)+ 端口-适配器(hexagonal)横切解耦。当前为 v0.1:CLI(headless 默认 + `--tui` 交互式终端)可对话、可调用 read/write/edit/bash/grep/find/ls 七个工具,事件流可订阅。

**注意:README.md 与 docs/design/architecture.md 已于 2026-08-14 校准至当前树**(此前曾描述已移除的 cli.py / 304 测试 / test_decoupling.py)。权威记录是 `docs/iteration/v0.1.md`(任务分解 + 变更记录 E1~E12)。

## 常用命令

环境:Python 3.12 + [uv](https://docs.astral.sh/uv/)。

```bash
uv sync              # 安装项目依赖
uv sync --group dev  # 开发环境(含 pytest)
uv run codeagent --prompt "你好"          # 一次性输入(headless 为默认形态,无 --headless 参数)
uv run codeagent --tui                    # 交互式终端(alt 屏;Esc 运行中打断 / 空闲退出打印完整文档)
echo "你好" | uv run codeagent            # 从 stdin 逐行读取
uv run python -m codeagent --prompt "你好"
uv run pytest -q                           # 全量测试
uv run pytest tests/tools/test_tools.py    # 单个测试文件
uv run pytest tests/tools/test_tools.py::test_bash_timeout  # 单个测试
```

配置:密钥写在固定目录 `~/.codeagent/.env`(首次启动幂等生成模板),**不读取 CWD 下的 `.env`**(安全决策 H10,防止在任意仓库运行时被其 `.env` 劫持)。`LLM_PROVIDER` 选 provider(deepseek / openai / qwen / glm / kimi / minimax / fake)。

**当前测试状态:260 项全绿**(2026-08-14 实测,清理 TUI 死代码后)。注:另有 3 项 bash 环境敏感测试待回归(ARG_MAX / Git bash ps 语义 / NO_COLOR,见审查记录)。新增代码请保证 `uv run pytest` 不引入新的失败。

## 架构与分层

两条正交轴(不要混淆):

- **横切轴(依赖方向)**:config / ai / tools / core / session 之间谁认识谁。依赖单向流动,组合根是唯一交汇点。
- **纵切轴(生命周期)**:装配(Factory)/ 单个对话(Session)/ 会话生命周期(Runtime)。

### 分层依赖规则(最重要约束)

| 模块 | 禁止 import |
|---|---|
| `core/` | config、ai、tools、session(只认识 `ports.py` + langgraph/langchain) |
| `session/` | ai、tools、config |
| `ai/`、`tools/` | core、session |
| `app/container.py`、`app/main.py` | 全部允许(**仅这两个文件可以跨层 import**) |

判据:`core/` 中 grep 不到 `config / tools / ai / session` 字面量 → 横切解耦成立。此规则目前靠人工遵守(`test_decoupling.py` 已在重构中删除,计划 v0.2 重写)。

### 模块职责

- **`app/container.py` — 组合根**:全项目唯一跨层交汇点。装配链:`create_llm` + `make_tools` → `llm.bind_tools(tools)`(★ 工具/模型唯一交汇行)→ `to_langchain_runnable` 包装 → 组装 `AgentPorts(bound_model, tool_executor=ToolNode, checkpointer=InMemorySaver)` → `build_graph`。`create_agent_session()` 供 CLI 入口消费。
- **`app/main.py` — CLI 入口**:解析 `--prompt` / stdin / `--tui`,订阅 `AgentSession` 事件流聚合成最终回复(TEXT_DELTA 累积、TOOL_CALL 前清零、AGENT_MESSAGE 兜底去重);`--tui` 转交 `app/tui/main.py`。
- **`core/` — 纯编排层**:模块顶层零副作用(不建模型、不发请求、不读 key),可被平台直接 import。`AgentPorts`(core 认识外部世界的唯一窗口);`build_graph` 纯组装 ReAct 循环;`should_continue` 只看 state 形状(最后一条消息有没有 tool_calls),不 import 任何具体工具。
- **`session/` — 有状态会话**:`AgentSession.run()` 全异步,用 `graph.astream(stream_mode=["messages","updates"])` 运行并把过程翻译成 `AgentEvent` 经 `EventBus` 分发(**不返回值**,订阅方感知进度)。每个 session 分配稳定 `thread_id`,同一会话多轮对话靠 checkpointer 累积上下文。失败自动回滚本轮消息;`abort()` 中断当前 run;`replace_graph()` 换图保留 thread。
- **`ai/` — 模型配置层,五层细分**:
  - `providers/`:每 provider 一个自包含文件(配置类 + `make_llm` 工厂),在 `ai/providers/__init__.py` 的 `PROVIDERS` 注册表登记;`fake.py` 提供离线 `FakeClient`(脚本化多轮,支撑全量离线测试)。
  - `catalog/`:不可变值对象 `ModelSpec` + `ModelRegistry` 两遍解析(先全部精确 id → 再全部别名)+ `models.json` 按 id upsert 合并。
  - `protocol/`:框架无关协议(`ChatClient` / `ChatMessage` / `ToolCall` / `ChatResponse` / `StreamEvent`)。
  - `transport/`:`OpenAICompatClient`(httpx,重试/流式,thinking/usage 全量透传)。
  - `bridge/`:`to_langchain_runnable` 把自研客户端包装成 langchain Runnable,**只被组合根消费**,`ai/` 内部其它模块不 import 它。
- **`tools/`**:`AtomicTool` 基类(无状态,子类实现 `_invoke` + 定义 `Args` pydantic schema,经 `to_langchain()` 转 `StructuredTool`)。`make_tools` 注册表产出七个工具:read / write / edit / bash / grep / find / ls;`shared/` 提供 `FsOps` 文件系统抽象缝(注入内存实现即可离线测)、路径/文本/截断/写串行化等共享设施。`BashTool` 带危险命令黑名单(字符串正则 + shlex 分词语义级检测 `rm -rf` 等价写法)、Git for Windows/WSL bash 探测链、默认 120s 超时(上限 600)、30k 输出截断。
- **`app/tui/` — 交互式终端(MVP)**:`view.py`(TuiApp 视图逻辑)只依赖 `backend.py` 的 `TuiBackend` 端口;`components.py` 纯渲染组件树(样式标签段,引擎无关可离线测);`textual_backend.py` 是当前唯一引擎实现。装配经组合根 `create_tui_app`(footer 的 model/effort 解析固化),本包不读配置、不跨层。
- **`resources/`、`extensions/`**:占位,延后(v0.2/v0.3)。

### 事件驱动

事件类型常量见 `core/events.py` 的 `EventType`:`session_started / text_delta / thinking_delta / agent_message / tool_call / tool_result / turn_end / error / run_cancelled / usage`。CLI、Web、测试都通过 `session.subscribe()` 感知,而不是拿单个返回值。

## 编码规范

### 风格规范(Python)

- **PEP 8 风格**:4 空格缩进(禁 Tab)、`snake_case` 函数/变量、`PascalCase` 类、常量全大写;行宽与现有文件保持一致(项目未配置格式化器)。
- **全量类型注解**(PEP 484 / 585 / 604):函数签名与数据结构必带类型标注,用现代写法(`list[int]`、`X | None`),不用旧式 `List[int]` / `Optional[X]`。
- **命名即文档**:标识符读起来像一句完整的话(如 `should_continue`、`create_agent_session`),不看函数体应能猜到行为。
- **注释只写"为什么"**:解释约束、设计取舍、踩过的坑(参考 `tools/atomic/bash.py` 黑名单正则注释),不逐行翻译代码。
- **docstring 全中文**,模块级先讲职责与分层约束,再进入实现。
- **模块顶层零副作用 + 延迟导入**:新模块禁止顶层建对象/发请求/读密钥;langchain 只在 `ai/bridge/` 与 `app/container.py` 加载,保持启动路径轻量。
- **`__all__` 显式声明导出**。

### 内聚 / 耦合 / 可读性(结构与复杂度)

- **单一职责**:一个文件/函数只做一件事。模块 docstring 若不能一句话说清职责 → 内聚出问题。
- **函数一屏内**(约 ≤60 行),层层抽象:调用方读"做什么",细节下沉到私有方法(`session/session.py` 的 `_translate_*` 是范例)。
- **文件行数双阈值(启发式,目标是内聚而非数字)**:
  - 超过 ~300 行 → code review 时必须能解释"为什么不拆";
  - 超过 ~500 行 → 应拆分或批准豁免;
  - 拆必须按职责拆:为凑行数拆成互相 import 的小文件反而破坏内聚、增加耦合(现有最大的 `app/tui/components.py` 515 行是组件树,`ai/transport/openai_compat.py` 359 行,均为高内聚的正当大文件,不是问题)。
- **低耦合**:
  - 跨层 import 只允许在 `app/container.py` / `app/main.py`(见上文"分层依赖规则");
  - 依赖抽象/端口而非具体实现(`AgentPorts`、`ChatClient`);
  - 跨模块通知用事件(`EventBus`)而非直接调用;
  - 依赖显式传入,不隐式读全局/环境变量。
- **可独立测试 = 耦合低的客观检验**:新模块应能不联网、不碰其它模块、注入 `FakeClient` 即可测通。

### 复杂度工具(可选)

项目当前未配置静态检查工具链。如需落地,在 dev 组加 Black(格式)+ Ruff(lint)+ mypy(类型),阈值按"软告警 + 硬失败"双阈值配置(同上行数双阈值)。

### 测试规范

- **离线可测是最高原则**(NFR-M2):核心编排层零网络、零密钥即可运行;新模块应能不联网、不碰其它模块、注入 `FakeClient` 即可测通。覆盖目标:核心编排层 100% 离线可测,总体覆盖率 ≥ 80%。
- **目录按层镜像,不逐文件 1:1**:`src/<layer>/` 对应 `tests/<layer>/`,层内文件按被测单元命名(`tests/ai/test_bridge.py` ↔ `ai/bridge/langchain.py`)。例外:`tools/` 单文件 `test_tools.py` 覆盖整个工具包(内聚优先);`app/` 层测试拍平到 `tests/` 根(`test_config.py` / `test_container.py` / `test_cli.py`)。镜像纯为可导航性,测试代码可跨层 import。
- **夹具集中在 `tests/conftest.py`**:`_isolate_config_dir`(autouse,把 `CONFIG_DIR` 重定向到临时目录,防污染真实 `~/.codeagent`)、`memory_fsops`(内存 FsOps,注入测试用)。离线测试注入 `FakeClient` 或 mock `create_llm`。
- **`FakeClient` 是编排测试的核心注入点**(`ai/providers/fake.py`,实现 `ChatClient` 协议):`response` 固定文本 / `responses` 按序返回 / `steps` 脚本化多轮 ReAct(含 tool_calls)/ `thinking` / `usage` / `call_history` 断言。异常路径用其**子类覆盖 `_generate`** 抛错,不重写协议层。
- **桩对象代替真实依赖测节点级行为**:`_StubTool` / `_StubExecutor`(并行+config 透传)、`StubGraph` / `SimpleGraph`(run 的 recursion_limit、abort、usage)。桩只实现被测代码用到的接口。
- **断言行为/结果,不断言实现细节**:消息序列断言 `types == [...]`、事件类型断言 `EventType.X in seen`,验证"图走完的路径"而非中间表示;多 tool_calls 结果按 `tool_call_id` 分组断言。
- **文件系统用 `tmp_path`,环境用 `monkeypatch`**:绝不写真实路径;`monkeypatch.chdir` 注意是进程级;环境变量用 `setenv` / `delenv`。
- **断言必须平台无关**(Windows / Linux / macOS 都要跑):不出现特定平台的路径表示、shell 行为(`pwd` 输出、`PIPESTATUS`)。验证"命令在目标目录执行"用行为验证(标记文件 + `test -f marker && echo CWD_OK`)而非路径字符串断言。
- **回归测试写明 bug 背景**:函数名或 docstring 标注 `(回归:P2-x)`,并说明早期缺陷是什么、现在的正确行为是什么。
- **async 测试不引 `pytest-asyncio`**:统一 `asyncio.run(...)` 包一层。
- **修测试时不要糊绿**:不用 `|| true` 掩盖失败路径,不平台特判跳过;改断言/命令,验证强度不降反升(如补 `"退出码: 1"` 锁定豁免路径)。

## 约定与易踩坑

- **配置命名空间隔离**:全局 `Settings` 与各 provider 的 `Config` 各自解析、各自只认自己的键,所有配置类必须设 `extra="ignore"`(否则共享 `.env` 里其它命名空间的键会报 `extra_forbidden`)。新增 provider 时沿用此模式。
- **新增 provider 只需动 `ai/providers/` + 环境变量**:不应触碰 `session/`、`core/`。新增工具同理只动 `tools/`。改编排形状只动 `core/`。
- **模型名解析唯一实现**:`ai/model_pattern.py` 的 `split_model_pattern`(解析 `model:effort` 后缀),不要另写一份。
- 测试规范(夹具 / FakeClient / 镜像结构 / 平台无关断言等)见上文"测试规范"章节。
