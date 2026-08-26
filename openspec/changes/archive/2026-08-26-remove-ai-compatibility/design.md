## Context

上一轮变更已将实现迁移到以下规范位置：`ai.model` 承载模型契约，`ai.transport.sse` 承载 SSE 解析，`app.composition.model_selection` 承载 provider/model/effort 选择和客户端装配。当前遗留模块只做延迟转发或 re-export，不再包含独立实现；仓库内部的生产代码和主要测试已经使用新路径。

本变更是一次明确的外部导入 API 断裂。实现必须保持 canonical 模块的行为不变，并避免删除兼容层时把应用装配重新放回 AI 层。

## Goals / Non-Goals

**Goals:**

- 删除三个兼容入口集合：`ai/factory.py`、`ai/model_pattern.py` 和 `ai/protocol/`。
- 固化唯一导入映射：模型契约 → `ai.model`，SSE → `ai.transport.sse`，客户端装配 → `app.composition.model_selection`。
- 清理当前源码、测试和架构文档中的旧路径，保留历史记录中的事实性描述或明确标记其历史性质。
- 用窄范围测试验证 canonical 导入、旧模块缺失、AI 层依赖方向和关键装配入口仍可用。

**Non-Goals:**

- 不改变 provider 工厂、OpenAI-compatible transport、SSE 事件、工具 schema、usage 或模型目录的运行时语义。
- 不删除 `app.container` façade、session 旧格式读取、工具/MCP/skill 兼容逻辑或其他非 AI 兼容机制。
- 不为外部旧调用方保留过渡别名、动态 `__getattr__` 或安装后 shim。
- 不在本变更中执行完整测试套件；完整回归由用户执行。

## Decisions

### 1. 直接删除文件，不继续保留 deprecated façade

旧模块已经没有仓库内部职责，只承担短期路径兼容。直接删除可以让错误尽早暴露，并从目录结构上证明 `ai/` 不负责应用装配。

备选方案是保留一版带 `DeprecationWarning` 的转发模块，但这会继续保留反向概念和维护成本，也无法真正验证外部调用方已迁移，因此不采用。

### 2. 保持职责到规范路径的一对一映射

实现与测试按以下映射迁移：

| 旧入口 | 规范入口 |
| --- | --- |
| `codeagent.ai.factory.create_llm` | `codeagent.app.composition.model_selection.create_llm` |
| `codeagent.ai.factory.get_available_providers` | `codeagent.app.composition.model_selection.get_available_providers` |
| `codeagent.ai.factory._split_pattern` / `split_model_pattern` | `codeagent.app.composition.model_selection.split_model_pattern` |
| `codeagent.ai.model_pattern.KNOWN_EFFORTS` | `codeagent.app.composition.model_selection.KNOWN_EFFORTS` |
| `codeagent.ai.protocol.*` 消息与协议 | `codeagent.ai.model.*` |
| `codeagent.ai.protocol.sse.SSEParser` | `codeagent.ai.transport.sse.SSEParser` |

不会在 `ai/__init__.py` 增加新的应用级导出；顶层只继续暴露 AI 层中立契约。

### 3. 以仓库内部引用清理作为删除前置条件

先将测试和当前文档全部切换到规范路径，再删除兼容文件。实现阶段使用仓库搜索和依赖方向检查确认：生产代码、测试和当前架构文档不再导入或描述这些模块；历史 review/iteration 文档可以保留历史事实，不作为运行时引用。

### 4. 用失败边界测试确认破坏性行为

新增或调整窄范围测试，验证规范入口可导入且旧模块路径无法解析。旧模块测试不再验证其转发结果，而是验证模块不存在；provider、transport、SSE 和组合根既有行为测试继续保留。这样可以区分“路径已删除”和“canonical 实现被误删”两类回归。

### 5. 采用可回滚的发布顺序

该变更应与版本说明或迁移说明一起发布，明确旧路径是 breaking change。若用户发现外部调用方尚未迁移，回滚整个提交即可恢复三个兼容入口；不在运行时偷偷恢复 shim，以免出现部分环境行为不一致。

## Risks / Trade-offs

- **[Risk]** 未在仓库内登记的插件或第三方脚本仍导入旧路径 → **Mitigation:** 在变更说明中列出完整迁移映射，并让旧导入失败尽早暴露；用户执行全量测试和集成验证。
- **[Risk]** 文档清理误改历史记录，破坏迭代审计 → **Mitigation:** 只更新 README、CLAUDE.md、当前架构/需求说明；对 `docs/iteration/` 和 `docs/review/` 的历史描述不做无必要改写。
- **[Risk]** 删除 `ai/protocol/` 时遗漏某个深层导入 → **Mitigation:** 对 `ai.protocol`、`ai.factory`、`ai.model_pattern` 做全仓文本搜索，并增加旧模块不可解析的窄范围测试。
- **[Risk]** 删除 façade 时误删 canonical 实现或改变导出 → **Mitigation:** 删除仅限明确列出的兼容文件，保留 `ai/model/`、`ai/transport/sse.py` 和组合根实现，并运行 AI/组合根相关测试。
