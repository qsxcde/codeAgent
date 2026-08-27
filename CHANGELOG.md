# Changelog

本文件记录面向使用者的版本变化。完整的任务拆分、设计决策与验收证据见
[`docs/iteration/`](docs/iteration/) 下的迭代记录。

## [Unreleased]

### Planned

- Hooks 与任务完成前的验证门禁

### Engineering updates

- 测试按行为域拆分并集中公共契约，当前全量验证为 `944 passed`；补齐会话 `last_activity_at` 跨层契约。
- CI 增加快速质量检查、Ubuntu/Windows/macOS 离线测试矩阵、wheel 安装冒烟和 TUI 性能 artifact。
- 增加 pytest-cov、Ruff 正确性检查、安装后 fake provider CLI 验证和性能相对变化报告。
- 性能和覆盖率暂不设置高强度硬门槛，等待稳定 CI 数据后再评估。

## [0.3.0] - 2026-08-22

### Added

- Skills 技能系统：内建、个人、项目三源发现与同名遮蔽诊断
- `skill` 工具与 TUI `/skills` 手动加载
- MCP 客户端最小协议面：`tools/list`、`tools/call`
- MCP 工具命名空间化、分组预算与权限规则
- 输入、输出、推理和缓存命中 token 的归一、落库与展示
- 会话树数据视图、TUI `/tree` 导航和树形 `/sessions list`
- TUI `/mcp`、`/quit` 等命令支持

### Changed

- 会话恢复入口统一为 `/sessions`，支持最近会话继续和交互式切换
- v0.3 以离线可测为验收基线，避免网络和密钥依赖

### Deferred

- 费用估算：当前只统计 token，不维护单价和费用模型
- Web/HTTP API：待出现真实的平台或多端消费者后重估
- 轻量记忆、插件系统、多智能体和自动化任务：保留为远期方向

### Verification

- `uv run pytest -q`: 666 collected, 665 passed, 1 skipped（Windows 无符号链接权限；无失败）
- `openspec validate --specs`: 9 passed
- `git diff --check`: passed

## [0.2.0] - 2026-08-15

### Added

- 自研 ReAct 编排循环和消息归约，移除 LangGraph/LangChain 编排依赖
- JSONL 树形会话持久化、恢复、切换、分叉和上下文压缩
- bash/write 敏感操作确认环与文件访问边界控制
- 全局、项目和子目录级 `AGENTS.md` 指令加载
- TUI 斜杠命令、模糊补全、选择器、Markdown 渲染和滚动交互

### Changed

- `/fork` 取代 `/undo`，以分支会话实现可回退语义
- 事件流继续作为 CLI、TUI 和测试之间的统一运行时接口

## [0.1.0] - 2026-08-14

### Added

- Headless CLI 与交互式 TUI
- 多模型 provider 配置和离线 `fake` provider
- `read`、`write`、`edit`、`bash` 等原子工具
- 异步 ReAct 对话、工具调用和事件流订阅
- 危险命令黑名单、Windows bash 探测和离线测试基线

[Unreleased]: https://github.com/qsxcde/codeAgent/compare/v0.3.0...HEAD
