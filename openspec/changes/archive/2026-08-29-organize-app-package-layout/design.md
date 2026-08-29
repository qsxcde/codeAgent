## Context

当前 `app/` 已完成一次按职责拆分，但实现仍分布在根目录、`composition/` 和 `tui/` 的扁平模块中。现有导入边界测试要求组合根集中装配，TUI 的具体 Textual 类型只能停留在适配边缘；前一变更还为多个旧路径保留了兼容外观。详见 [proposal.md](proposal.md) 和当前架构文档。

## Goals / Non-Goals

**Goals:**

- 让目录层级直接表达技能、任务/验证、组合装配和 TUI 子职责。
- 让新包路径成为内部实现和仓库调用方的唯一规范导入路径；迁移期兼容外观在最终收口阶段删除。
- 保持模块依赖单向，`container.py`/`main.py` 仍是跨层组合入口，Textual 仍只存在于适配包。
- 让每个迁移批次都能通过导入契约、行为测试和架构检查验证。

**Non-Goals:**

- 不改变 CLI/TUI 行为、命令集合、模型或工具协议、会话 JSONL 格式和运行时事件语义。
- 不引入第三方依赖、依赖注入容器或模块级服务注册表。
- 不为目录整齐而继续拆分已经内聚且符合规模约束的函数或类。
- 接受旧导入路径失效；本变更明确要求仓库内所有消费者完成迁移，外部消费者需按规范路径更新。

## Decisions

### 保留少量根入口，职责子包承载规范实现

`app/main.py`、`app/container.py` 和 `app/config.py` 留在根目录，分别作为 CLI 入口、组合根和全局配置入口。其余根层职责按以下方式归并：`context/agents.py`、`errors/reporting.py`、`skills/`、`tasks/`。相比把所有文件机械地搬进一个 `services/`，这些目录对应稳定的业务边界，也能保持现有架构测试的语义。

### composition 按装配对象分包

`composition/model/` 收纳模型选择、端口、预算和工厂；`runtime/`、`session/`、`tools/`、`tui/` 分别收纳对应的装配逻辑；单文件的策略和提示词装配收纳为 `policy.py` 与 `prompts.py`。迁移期曾使用旧模块作为临时 re-export，最终实现删除 `model_factory.py`、`runtime_factory.py`、`tool_factory.py` 等旧路径，避免继续掩盖错误职责依赖。

### TUI 按边缘、状态、展示和工作流分包

TUI 采用以下职责边界：

```text
tui/ports/backend.py          # Textual-free 后端协议
tui/adapters/textual/         # 唯一具体 Textual 依赖
tui/state/                    # TuiModel、runtime、transcript 状态与归约
tui/presentation/             # blocks、组件、终端文本与主题
tui/commands/                 # 解析、模糊匹配、分派和命令协调
tui/session/                  # 会话动作、命令和恢复
tui/rendering/                # 帧调度与渲染协调
tui/benchmark/                # 离线性能夹具和指标
```

`view.py` 的应用壳迁移为 `application.py`，`tui/main.py` 保持为 TUI 入口；已迁移的 TUI 平铺模块全部删除。包的 `__init__.py` 不做全量 eager import，避免状态模块形成循环导入。

### 先迁移实现，再逐步切换内部导入

每个批次先建立新路径的导入契约并确认失败，再移动实现、补齐新包初始化文件，最后把生产代码与测试改用规范路径。迁移期间可使用临时 re-export 降低批次风险，但最终收口必须删除这些外观，并由静态架构测试阻止旧路径回流；同时检查新路径的依赖方向和 Textual 边界。

### 以规范导入路径作为回滚边界

物理移动不改符号签名和模块初始化副作用，但删除旧入口会使错误导入立即暴露。任一批次失败时回退整个收口提交；不需要数据迁移或运行时配置迁移。

## Risks / Trade-offs

- [相对导入和测试路径产生循环或遗漏] → 先迁移无状态模型/协议，再迁移协调器；每批运行导入契约和相关窄测试。
- [删除旧入口导致外部消费者导入失败] → 在仓库内完成全量导入迁移，增加旧路径不存在和规范路径可导入的契约测试，并在变更说明中明确这是破坏性导入变更。
- [TUI 具体类型越过适配边界] → 将 Textual 模块集中在 `tui/adapters/textual/`，并扩展 AST 检查禁止其他 TUI 子包导入 Textual。
- [大规模重命名导致 diff 难以审查] → 按 context/errors、skills、tasks、composition、TUI 的顺序分批移动，每批保持行为不变。
- [当前工作区已有未提交修改] → 不回退或覆盖既有改动；只在已有拆分结果上移动文件，并在最终差异中区分本变更新增内容。

## Migration Plan

1. 为新目录和规范导入路径增加契约测试，运行失败测试确认测试能捕获尚未迁移的状态。
2. 迁移 `context/`、`errors/`、`skills/` 和 `tasks/`，在批次切换期间临时使用旧根模块外观。
3. 迁移 `composition/` 的模型、运行时、会话、工具和 TUI 装配子包，更新 `container.py` 及内部导入。
4. 迁移 TUI 的端口/适配器、状态、展示、命令、会话、渲染和基准模块，更新旧 TUI 外观。
5. 删除迁移期兼容外观，更新所有仓库内导入、架构文档和规模/依赖规则；规范路径成为唯一入口。
6. 执行导入契约、相关单元/契约测试、完整离线测试、Ruff、规模扫描、`git diff --check` 和 OpenSpec 验证。

## Open Questions

无。旧兼容路径的删除是本次变更的最终收口，不另设后续弃用阶段。
