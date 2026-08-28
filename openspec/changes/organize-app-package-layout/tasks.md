## 1. 契约与包骨架

- [x] 1.1 增加 `context/`、`errors/`、`skills/`、`tasks/` 以及 composition/TUI 目标子包的空 `__init__.py`，确保包初始化不产生跨层副作用。
- [x] 1.2 增加应用包布局契约测试，要求规范路径可导入关键公开符号，并要求具体 Textual 依赖只出现在 `tui/adapters/textual/`。
- [x] 1.3 运行新契约测试确认迁移前按预期失败，并把迁移期外观与规范实现路径加入规模扫描和架构测试的明确规则。

## 2. 根层职责归并

- [x] 2.1 将 `agents.py`、`error_reporting.py` 的实现迁移到 `context/agents.py`、`errors/reporting.py`，迁移期旧路径使用薄 re-export，随后删除并更新内部导入。
- [x] 2.2 将技能发现、模型、运行时和包管理实现迁移到 `skills/` 与 `skills/packages/`，迁移期保留旧路径后完成删除。
- [x] 2.3 将任务模式、生命周期、结果、监督和验证实现迁移到 `tasks/` 与 `tasks/verification/`，迁移期保留旧路径后完成删除。
- [x] 2.4 运行 skills、task、verification 相关单元/契约测试，确认符号身份、异常和输入输出行为不变。

## 3. composition 子包归并

- [x] 3.1 将模型端口、预算、选择和工厂迁移到 `composition/model/`，迁移期保留旧入口后删除并更新组合根导入。
- [x] 3.2 将运行时和会话工厂迁移到 `composition/runtime/`、`composition/session/`，保持 runtime owner、关闭顺序和惰性适配行为不变。
- [x] 3.3 将工具工厂/定义、策略和提示词装配迁移到 `composition/tools/`、`composition/policy.py`、`composition/prompts.py`，保留原组合模块外观。
- [x] 3.4 将 TUI 工厂和配置迁移到 `composition/tui/`，更新 `container.py`、CLI/TUI 装配测试和所有内部导入。

## 4. TUI 子包归并

- [x] 4.1 将 `backend.py` 迁移到 `tui/ports/`，将四个具体 Textual 模块迁移到 `tui/adapters/textual/`，迁移期保留旧外观后删除并扩展 Textual 边界测试。
- [x] 4.2 将模型、事件、历史、运行时状态/迁移、Transcript 状态迁移到 `tui/state/`，迁移期保留旧入口后删除。
- [x] 4.3 将 block、组件、终端 primitives、Markdown、输出、状态和主题迁移到 `tui/presentation/`，保持纯终端模块不依赖 Textual。
- [x] 4.4 将命令解析/分派/协调、会话动作/恢复、对话协调和渲染协调迁移到 `tui/commands/`、`tui/session/`、`tui/rendering/`，保留旧 coordinator 入口。
- [x] 4.5 将性能基准迁移到 `tui/benchmark/`，更新 TUI 测试、基准导入和 `tui/main.py`/应用壳引用。

## 5. 文档与验证

- [x] 5.1 更新架构、测试和 OpenSpec 相关文档，明确规范导入路径、临时外观删除策略和 Textual 适配边界。
- [x] 5.2 扫描并迁移生产代码中的旧路径引用，删除所有迁移期旧模块并为规范路径添加测试覆盖。
- [x] 5.3 运行导入契约、unit/contract、完整离线测试、Ruff、规模扫描、`git diff --check`、OpenSpec 验证和构建检查。

## 6. 删除迁移期兼容入口

- [x] 6.1 删除根层、composition 和 TUI 下已迁移模块的兼容 re-export；保留 `main.py`、`container.py`、`config.py` 与真实入口所需的包初始化文件。
- [x] 6.2 将仓库内生产代码、测试和文档中的旧平铺导入切换到规范实现路径，清理 `__init__.py` 中面向旧入口的导出。
- [x] 6.3 扩展包布局契约，确认旧模块路径不存在、规范路径可导入，并继续禁止非 Textual 适配包引用具体 Textual 类型。
- [x] 6.4 运行完整测试、Ruff、规模扫描、OpenSpec 验证和构建检查，更新架构/测试文档中的兼容策略。
