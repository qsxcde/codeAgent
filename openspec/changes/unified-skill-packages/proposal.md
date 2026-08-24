## Why

当前 Skill 系统只能从固定目录读取 `SKILL.md`，缺少统一的安装、版本跟踪、包来源和 Agent 适配机制。这样可以手动加载 Skill，但无法稳定复用 Superpowers 这类同时包含通用 Skill 内容、工具映射和会话 Bootstrap 的跨 Agent 工作流。

现在需要把 Skill 内容、包管理和 CodeAgent 生命周期解耦，使用户可以通过 CodeAgent 自己的安装入口引入 Superpowers 或其它兼容 Skill 包，同时保证未信任的第三方代码不会被自动执行。

## What Changes

- 新增 Skill Package 安装模型，支持 Git URL 和本地目录来源。
- 新增全局/项目级包存储、注册表和锁定信息，记录包版本、来源和解析后的 Skill 根目录。
- 扩展 Skill 发现逻辑，递归发现包内 `skills/**/SKILL.md`，同时保留现有 `~/.codeagent/skills` 与项目 `.codeagent/skills` 兼容入口。
- 新增 CodeAgent Harness Adapter，负责工具映射、能力声明和 `using-superpowers` Bootstrap 生成。
- 在新会话、会话恢复、端口重建和上下文压缩后重新注入 Bootstrap，并避免同一上下文重复注入。
- 扩展 `/skills` 与 CLI 的安装、列表、更新、删除、重新加载和诊断能力。
- 默认只读取 Skill Markdown，不执行包内 JavaScript、TypeScript、Python 或 Shell 扩展；可信插件运行时作为后续能力保留。
- 为缺失的 subagent、todo、web 等工具提供能力声明和降级语义，不伪造不存在的工具调用。

## Capabilities

### New Capabilities

- `skill-packages`: Skill Package 的安装来源、存储、注册表、锁定、更新/删除和安全信任边界。

### Modified Capabilities

- `skills`: 增加包来源与递归发现、包元数据可见性、CodeAgent 工具映射、会话 Bootstrap 自动注入和上下文压缩后的重新注入要求。

## Impact

- 影响 `src/codeagent/app/skills.py`、组合根端口装配、会话生命周期、TUI 命令和 CLI 入口。
- 需要新增包管理、注册表、Adapter 和运行时生命周期模块，以及对应的测试夹具和验收测试。
- 不引入第三方运行时插件依赖；首版只处理 Markdown Skill，现有 `skill` 工具和目录安装保持向后兼容。
- 全局状态写入 `~/.codeagent/packages`、`registry.json` 和锁定文件；项目级安装写入项目 `.codeagent/packages`。
