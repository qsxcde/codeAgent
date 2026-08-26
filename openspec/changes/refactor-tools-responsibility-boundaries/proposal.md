## Why

`tools/atomic/bash.py` 已同时承担命令安全分析、Shell 平台探测、进程树生命周期、同步/异步执行、输出处理和原子工具适配，导致单一变更牵动多个无关职责。`tools/security.py` 和 `tools/mcp/config.py` 也存在类似的职责聚合，跨模块复用私有实现，增加了测试耦合、循环依赖和后续扩展成本。同时，文件类原子工具虽然已经避免了 Shell 依赖，但路径、编码、换行、遍历和文件系统差异仍需要形成统一的平台语义。

现在进行边界整理，可以在不改变工具对外行为的前提下，为进程执行、安全策略、MCP 配置和原子工具实现建立清晰的替换缝。

## What Changes

- 将 Bash 的进程执行、超时/取消、进程树清理、临时输出捕获和平台差异从原子工具中抽离为独立的执行基础设施。
- 将危险命令正则、Shell 分词、嵌套命令检测和删除语义分析从 `atomic/bash.py` 抽离到安全规则模块，消除安全模块对 Bash 私有函数的反向依赖。
- 将安全策略按 Bash、文件边界、MCP 和统一分发职责拆分，保留现有 allow/ask/deny 语义。
- 将 MCP Server 配置解析与 MCP 权限配置解析拆分，保持现有 MCP 工具装配和权限行为。
- 明确八个内建原子工具的边界：`read`、`write`、`edit`、`grep`、`find`、`ls`、`bash`、`skill`；MCP 工具归类为外部适配器，不混入内建工具职责。
- 为文件类原子工具补充跨平台路径、编码、换行、大小写、符号链接/junction、权限和遍历语义的统一验证。
- 为 Bash 明确 Linux/macOS 共用 POSIX 后端、Windows 使用 Git Bash 后端的策略；WSL 不作为隐式 fallback，平台差异不泄漏到 `BashTool`。
- 为 MCP server 的命令启动、stdio、环境变量和配置路径补充跨平台边界，但不改变外部 MCP 工具的业务语义。
- 将 `skill` 定义为基于注入注册表的轻量原子工具，不引入平台专用执行逻辑。
- 保持 `BashTool`、内建工具 schema、结果状态、超时/取消语义、MCP 工具命名和组合根装配行为不变。
- 更新相关测试，使测试优先验证行为；仅针对内部实现的测试迁移到新的职责模块。
- 暂不拆分 `grep.py`、`find.py`、`mcp/client.py` 和已具备单一职责的简单原子工具；本变更只为它们补充跨平台行为基线，避免无收益的过度重构。

## Capabilities

### New Capabilities

None. This is an internal responsibility-boundary refactor; no new user-visible capability is introduced.

### Modified Capabilities

None. Existing tool behavior remains unchanged. This change declares `skip_specs: true`.

## Impact

- 受影响代码：全部八个内建原子工具、`src/codeagent/tools/shared/` 文件系统公共能力、`src/codeagent/tools/atomic/bash.py`、`src/codeagent/tools/security.py`、`src/codeagent/tools/mcp/config.py` 及新增的执行、安全和 MCP 配置模块。
- 受影响测试：Bash 安全/进程测试、文件类工具的路径/编码/换行/遍历测试、tools 安全测试、MCP 配置与启动测试，以及仍直接导入 Bash 私有函数的测试。
- 受影响内部导入：`tools/security.py` 对 Bash 私有函数的依赖、MCP loader 和组合根对配置解析器的导入路径需要统一调整。
- 外部行为：原子工具名称、参数 schema、结果格式、结构化执行元数据、确认策略和 MCP 装配行为保持兼容。
- 依赖：不新增第三方依赖；继续遵守 tools 层不依赖 core、session、ai 的分层约束。
