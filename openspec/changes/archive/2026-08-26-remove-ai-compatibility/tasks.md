## 1. 迁移并清理仓库内部引用

- [x] 1.1 全仓搜索 `codeagent.ai.factory`、`codeagent.ai.model_pattern` 和 `codeagent.ai.protocol`，区分生产代码、测试、当前文档与历史记录中的引用
- [x] 1.2 将仍存在的生产代码和测试导入迁移到 `codeagent.app.composition.model_selection`、`codeagent.ai.model` 或 `codeagent.ai.transport.sse`，保持现有行为断言不变
- [x] 1.3 更新 README、CLAUDE.md、`docs/design/architecture.md` 和 `docs/design/requirements-analysis.md` 中的当前 AI 结构与导入说明；历史 iteration/review 文档保留历史事实，不作为现行架构说明

## 2. 删除旧 AI 兼容入口

- [x] 2.1 删除 `src/codeagent/ai/factory.py`，确认客户端创建、provider 列表和模型模式解析的实际实现仍只位于应用组合根
- [x] 2.2 删除 `src/codeagent/ai/model_pattern.py`，确认 `KNOWN_EFFORTS` 和 `split_model_pattern` 的 canonical 入口可用
- [x] 2.3 删除 `src/codeagent/ai/protocol/__init__.py`、`messages.py` 和 `sse.py`，确认模型契约和 SSE 解析实现未被误删
- [x] 2.4 更新 `src/codeagent/ai/__init__.py` 的模块说明，移除“旧 ai.factory 兼容入口”描述，不增加任何新的应用级导出

## 3. 增加删除边界回归

- [x] 3.1 增加 AI 导入边界测试，验证 `codeagent.ai.model`、`codeagent.ai.transport.sse` 和 `codeagent.app.composition.model_selection` 的 canonical 导出可用
- [x] 3.2 增加旧路径失败测试，验证五个旧模块路径无法导入且不会隐式加载应用组合根；移除旧 façade 专用兼容 smoke test
- [x] 3.3 增加或更新静态引用检查，确保源码、测试和当前架构文档不再引用被删除入口，同时保持 AI 层禁止反向依赖 `codeagent.app`

## 4. 窄范围验证与交付

- [x] 4.1 运行 AI、组合根和依赖方向相关的窄范围 pytest，以及编译检查，确认 canonical 路径和现有 provider/transport 行为通过
- [x] 4.2 运行 `openspec validate "remove-ai-compatibility" --type change` 和必要的规格校验，修复变更工件问题
- [x] 4.3 汇总未执行全量测试的事实、窄范围验证结果和外部调用方迁移映射，交由用户执行全量测试并反馈结果
