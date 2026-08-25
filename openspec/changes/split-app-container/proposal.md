## Why

`src/codeagent/app/container.py` 已增长到约 900 行，同时承担模型适配、Skill/AGENTS 上下文、工具与 MCP、安全策略、运行时资源、会话装配以及 TUI 登录和热切换等职责。组合根过度集中使跨层依赖、资源所有权和 TUI 回调难以单独测试，也提高了后续修改会话、模型或界面时产生回归的风险。

当前会话层已经完成模块拆分，下一步应将应用层组合根按生命周期和职责拆开，同时保留现有入口和运行行为。

## What Changes

- 新增 `app/composition/` 组合包，按职责拆分模型适配、提示词/Skill、策略、工具/MCP、运行时、会话和 TUI 装配。
- 将 `container.py` 收敛为兼容 façade，继续导出现有的 `create_agent_ports`、`create_agent_session`、`create_session_manager`、`create_tui_app`、`ChatModelPort` 等符号。
- 将 TUI 的登录、Package 操作、Skill 刷新和 provider/model/effort 热切换从嵌套闭包整理为显式装配对象，保持现有回调语义。
- 明确模型客户端与 MCP 工具的资源关闭边界，保持懒加载、热切换、幂等关闭和退出兜底行为不变。
- 扩展分层导入检查，使 `app/composition/` 被视为组合根，同时继续禁止 `app/tui/` 直接依赖 AI、工具和配置层。
- 增加模块导入、兼容导出、TUI 懒装配、热切换和运行时关闭的回归测试。
- 不修改会话持久化格式、Skill 优先级、配置优先级、provider 行为、TUI 命令语义或对外可观察协议。

## Capabilities

### New Capabilities

无。本变更只重组内部实现，不引入新的用户可观察能力。

### Modified Capabilities

无。本变更不改变现有需求，只改善组合根的模块边界和可测试性。

## Impact

- 主要影响 `src/codeagent/app/container.py`，并新增 `src/codeagent/app/composition/` 下的装配模块。
- 需要更新 `tests/test_container.py`、`tests/test_decoupling.py` 以及相关 TUI、会话、MCP 回归测试的导入和覆盖范围。
- 保留 `codeagent.app.container` 作为稳定导入入口，避免 CLI、TUI 和外部集成发生破坏性变化。
- 不新增运行时依赖，不改变配置文件、会话文件或 MCP/Skill 数据格式。
- 该变更属于纯重构，因此通过 `.openspec.yaml` 的 `skip_specs: true` 明确不创建规格增量。
