## Context

当前组合根集中在 `src/codeagent/app/container.py`。它同时包含 AI 协议适配、模型和上下文解析、Skill/AGENTS.md 装配、工具/MCP 装配、安全策略、运行时资源关闭、会话工厂以及 TUI 的状态切换回调。`app/main.py` 和 `app/tui/main.py` 通过 `codeagent.app.container` 使用这些入口，测试也直接导入其中的部分适配器和私有辅助函数。

本变更是纯内部重构。现有 provider、Skill、MCP、会话持久化、TUI 命令和模型配置优先级均属于既有行为，不能因为文件移动而改变。

## Goals / Non-Goals

**Goals:**

- 按职责和资源生命周期拆分组合根，降低单模块的认知和测试成本。
- 保留 `codeagent.app.container` 的稳定导入路径和现有工厂函数签名。
- 让 TUI 装配状态（Package、诊断、SessionManager、热切换）由显式对象持有，而不是依赖大量嵌套闭包。
- 明确模型客户端与 MCP 工具的唯一资源所有者，保持懒加载、热切换和幂等关闭语义。
- 让分层导入测试能够识别一个明确的组合包，同时保护 `app/tui/` 的依赖边界。

**Non-Goals:**

- 不改变任何会话、配置、Skill、MCP 或 TUI 对外行为。
- 不修改会话 JSONL 格式、模型/provider 解析优先级或安全策略规则。
- 不在本变更中移除 `_RUNTIMES_BY_PORTS`、引入 Skill/MCP 缓存或减少所有 `Any`。
- 不新增第三方依赖，也不把具体 AI、工具或配置依赖下移到 `core/`、`session/` 或 `app/tui/`。

## Decisions

### 1. 使用 `app/composition/` 子包，`container.py` 保留为 façade

新增组合包作为所有跨层装配实现的归属目录，`container.py` 只负责从子模块导出稳定入口和兼容符号。子模块不得反向导入 `container.py`，避免循环依赖。

选择子包而不是继续增加 `container_model.py` 等顶层文件，是为了把“这些模块仍属于组合根”表达在目录结构中，并为后续的组合边界测试提供明确范围。直接把实现移动到 `ai/` 或 `core/` 会违反当前依赖方向，因此不采用。

### 2. 按职责拆成七个实现模块

目录和职责固定如下：

```text
app/composition/
├── model_factory.py   # ChatModelPort、usage 归一、摘要器、model/context 解析
├── prompt_builder.py  # workspace、AGENTS.md、Skill、system prompt 和诊断视图
├── policy_factory.py  # approval policy 和工作区边界适配
├── tool_factory.py    # 内建工具、Skill 注册表和 MCP 工具
├── runtime_factory.py # AgentRuntime、lazy wrapper、runtime registry、端口装配
├── session_factory.py # AgentSession、SessionManager 的组合
└── tui_factory.py     # TUI 装配、候选项、Package、登录和热切换
```

`runtime_factory.py` 保留 `create_agent_ports()` 和 `create_agent_runtime()`，因为它们的输出和资源所有权属于同一装配阶段；`session_factory.py` 只负责把端口、存储、摘要器和会话选项注入 session 层。

### 3. 将 TUI 闭包提升为 `TuiAssembler`

`create_tui_app()` 先创建 `TuiAssembler`，再由其生成 `TuiApp`。装配对象显式持有配置、注册表、PackageManager、SessionManager 和诊断列表，并提供 `refresh_skills()`、`package_action()`、`rebuild_ports()`、`save_key()` 等方法。

这样可以保持现有回调签名，同时让 provider/model/effort 热切换的“停止旧会话 → 创建新端口 → 关闭旧 runtime → 更新 manager”顺序可单独测试。相比继续拆分更多闭包，显式对象更容易检查状态和资源所有权。

### 4. 以 façade re-export 保持兼容，不立即修改调用方

`container.py` 继续导出当前公开工厂和测试使用的适配器/辅助符号，包括 `ChatModelPort`、`AgentRuntime`、`_usage_of`、`_create_policy`、`_LazyPorts` 和 `_LazySummarizer`。实现模块中的函数使用原有签名，避免 CLI、TUI、测试和外部集成同时迁移。

直接删除私有符号或要求所有调用方一次性改为新路径虽然可以减少 façade 内容，但会造成非必要的 BREAKING 变化，因此不采用。

### 5. 保留现有 runtime registry，分阶段迁移资源所有权

首阶段继续使用 `_RUNTIMES_BY_PORTS`，只把它移动到 `runtime_factory.py`，并保留 `runtime_for_ports()` 对 lazy wrapper 的解包逻辑。这样可以在不改变 `SessionManager` 和 TUI 热切换接口的情况下完成结构重构。

显式返回 `AgentRuntime`、彻底移除按 `id(ports)` 查找的隐式关联属于后续独立改进，不在本次拆分中混入。

### 6. 扩展组合根的导入约束

更新分层扫描测试，将 `app/composition/**` 与 `app/container.py`、`app/main.py` 一样视为允许跨层导入的组合根；`app/tui/**` 的禁止规则保持不变。增加一项反向依赖检查，确保 composition 模块不导入 `container.py`。

### 7. 通过兼容和生命周期回归测试控制风险

测试重点不是新增业务场景，而是证明拆分前后行为一致：

- 旧导入路径和工厂签名仍可用；
- fake provider 下的零网络装配仍成立；
- 无 API key 时 TUI 仍能懒启动；
- Skill、AGENTS.md、MCP diagnostics 仍注入到相同位置；
- provider/model/effort/login 热切换仍关闭旧 runtime 并更新 session manager；
- runtime 多次关闭只释放一次；
- 分层导入和循环依赖检查通过。

## Risks / Trade-offs

- **[导入兼容风险]** 外部代码可能从 `container` 导入当前私有符号。→ façade 保留这些符号，并为实现模块增加导入烟测；后续再单独规划弃用。
- **[测试 patch 路径风险]** 函数移动后，针对实现模块的 patch 路径可能失效。→ 测试优先 patch 实际依赖来源，兼容测试覆盖 `container` 导出，不改变运行时动态导入位置。
- **[资源泄漏风险]** 热切换同时涉及旧模型客户端和 MCP 子进程。→ 保留先构造新 runtime、再关闭旧 runtime 的顺序，补充关闭次数和异常路径测试。
- **[懒装配风险]** `_LazyPorts` 只有首次访问后才登记 runtime。→ 保留 wrapper 解包和 registry 查找逻辑，并覆盖无 key 启动、首次对话和 `/login` 后重建三条路径。
- **[循环依赖风险]** `tui_factory`、`session_factory` 和 `runtime_factory` 互相引用可能形成环。→ 依赖方向固定为 `model/prompt/policy/tool → runtime → session → tui`，`container` 只能向下导出，不作为实现依赖。
- **[架构测试漂移]** 只修改实现而不更新导入规则会让测试错误地拒绝新结构。→ 将 composition 目录纳入规则，并保留对 `app/tui` 的严格扫描。

## Migration Plan

1. 先记录当前 `container.py` 的兼容入口和生命周期行为，补齐缺失的回归断言。
2. 创建 `app/composition/`，先迁移模型适配、上下文、策略和工具装配；此阶段 `container.py` 仍可直接承载未迁移部分。
3. 迁移 runtime 和端口装配，再迁移 session 工厂，保持每一步都能通过现有容器和会话测试。
4. 创建 `TuiAssembler` 并迁移 TUI 装配；验证懒启动、Package 操作、登录和热切换。
5. 将 `container.py` 改为 façade，更新导入边界测试和模块导入烟测。
6. 运行容器、会话、TUI、MCP 和完整测试集；确认 `git diff --check` 与 OpenSpec 校验通过。

回滚策略是按阶段保留 façade 和旧调用路径：如果某一阶段出现行为回归，可暂时恢复该阶段的实现导入，而不需要恢复会话数据或配置文件。整个变更不涉及持久化格式迁移，因此无需数据回滚。
