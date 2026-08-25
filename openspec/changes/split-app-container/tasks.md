## 1. 建立兼容基线

- [x] 1.1 盘点 `container.py` 当前公开入口、测试使用的私有符号、动态导入和资源关闭路径，形成拆分前兼容清单。
- [x] 1.2 为旧导入路径、fake provider 零网络装配、runtime 幂等关闭和 TUI 无 key 懒启动补齐或固化回归测试。
- [x] 1.3 创建 `src/codeagent/app/composition/` 包，并增加禁止反向导入 `container.py` 的导入烟测。

## 2. 拆分模型、上下文、策略和工具装配

- [x] 2.1 将消息转换、usage 归一化、`ChatModelPort`、`LlmSummarizer` 和 model/context 解析迁移到 `composition/model_factory.py`，保持函数签名与事件字段不变。
- [x] 2.2 将 workspace、AGENTS.md、Skill 加载、system prompt 和来源/诊断视图迁移到 `composition/prompt_builder.py`，保持 Skill 渐进式披露语义。
- [x] 2.3 将安全策略和工作区边界适配迁移到 `composition/policy_factory.py`，保持 `interactive`、`deny`、`allow` 三种模式。
- [x] 2.4 将内建工具、Skill 渲染注册表和 MCP 工具加载迁移到 `composition/tool_factory.py`，保持工具顺序、命名和诊断透传。

## 3. 拆分运行时和会话工厂

- [x] 3.1 将 `AgentRuntime`、runtime registry、lazy wrapper 和关闭适配迁移到 `composition/runtime_factory.py`，保留 lazy wrapper 解包和幂等释放逻辑。
- [x] 3.2 将 `create_agent_ports()` 与 `create_agent_runtime()` 迁移到 runtime 工厂，验证模型、工具、策略、Skill 和 MCP 的装配结果与拆分前一致。
- [x] 3.3 将 `create_agent_session()` 与 `create_session_manager()` 迁移到 `composition/session_factory.py`，保持 store、summarizer、context window 和 runtime closer 注入行为。
- [x] 3.4 为端口热切换补充回归测试，确认新 runtime 构造成功后才关闭旧模型客户端和 MCP 资源。

## 4. 重构 TUI 装配

- [x] 4.1 在 `composition/tui_factory.py` 创建 `TuiAssembler`，显式持有配置、注册表、PackageManager、SessionManager 和诊断状态。
- [x] 4.2 将 Skill 刷新、Package install/update/remove/reload/list、候选项和已配置 provider 解析迁移到 TUI 装配模块。
- [x] 4.3 将 `rebuild_ports()` 和 `save_key()` 迁移为 `TuiAssembler` 方法，保持登录写入 `.env`、热切换和状态栏返回值语义。
- [x] 4.4 保持 `create_tui_app()` 的参数、backend 注入、懒端口/懒摘要器以及 SessionManager 初始会话行为不变。
- [x] 4.5 增加 TUI 装配回归测试，覆盖 Package reload、`/login`、provider/model/effort 切换、Skill 刷新和 MCP diagnostics。

## 5. 收敛兼容 façade 和架构边界

- [x] 5.1 将 `container.py` 改为从 composition 子模块 re-export 的兼容 façade，保留现有工厂、适配器和测试使用的私有符号。
- [x] 5.2 更新 `tests/test_decoupling.py`，允许 `app/composition/**` 跨层导入，同时继续限制 `app/tui/**` 不得直接依赖 AI、工具和配置层。
- [x] 5.3 更新模块文档字符串和导入说明，明确 composition 子包是组合根，且不得反向导入 façade。
- [x] 5.4 检查 `app/main.py`、`app/tui/main.py` 和外部现有导入无需改动，避免引入破坏性 API 变化。

## 6. 验证与收尾

- [x] 6.1 运行容器、模型、Skill、MCP、会话和 TUI 的定向测试，修复拆分造成的导入或生命周期回归。
- [x] 6.2 运行完整 pytest、Python 编译检查和 `git diff --check`，确认无持久化文件或配置格式变化。
- [x] 6.3 运行 `openspec validate split-app-container --type change --strict`，确认变更规划和 `skip_specs` 配置有效。
