## Why

`app/` 的导入方向已通过边界检查，但仍有 15 个生产文件超过 300 行，TUI、组合工厂、技能和任务相关模块混合了协调、展示、配置转换与基础设施错误处理等多种职责。局部修改需要理解过大的状态面，也难以持续满足仓库的文件/函数规模与可观测性规范。

## What Changes

- 按职责重构 `app/`：将 TUI 的展示、交互命令、会话协调、运行时调度拆为内聚模块；顶层对象只保留装配和生命周期外观。
- 拆分组合工厂、技能包管理与任务监督/验证模块，确保依赖组装留在 composition root，领域规则和基础设施细节不泄漏到入口层。
- 为应用层失败路径建立一致的安全错误报告方式：保留用户可理解的提示，并记录带上下文的诊断信息，避免静默吞没异常。
- 通过行为回归、AST 导入边界和规模检查约束重构结果；保留现有 CLI/TUI 入口、命令、会话格式和用户可见行为。

## Capabilities

### New Capabilities

无。该变更仅调整内部职责边界，不增加用户可见能力。

### Modified Capabilities

无。既有 CLI、TUI、会话和模型行为契约保持不变；`.openspec.yaml` 以 `skip_specs: true` 声明这是纯内部重构。

## Impact

- `src/codeagent/app/tui/`、`src/codeagent/app/composition/`、`src/codeagent/app/skills.py`、`skill_packages.py`、`task_supervisor.py`、`task_verification.py` 与相关入口模块。
- `tests/app/`、`tests/tui/`、`tests/test_decoupling.py` 及必要的架构文档。
- 不新增运行时依赖、不改变公共 CLI/TUI 入口或持久化格式。
