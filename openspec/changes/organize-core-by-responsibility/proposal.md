## Why

`src/codeagent/core` 已完成职责拆分，但模块仍平铺在同一目录，导致契约、上下文、模型请求、工具执行和 ReAct 编排之间的边界不够直观。现在按职责归并为子包，可以降低 import 认知成本，并让后续模块扩展有稳定落点；本变更不改变运行时行为和公共 `codeagent.core` API。

## What Changes

- 将 core 文件归并到 `contracts`、`context`、`model`、`execution`、`orchestration` 和 `support` 子包。
- 从原 `ports.py` 中拆出上下文契约与编排配置，避免契约层反向依赖上下文实现。
- 将 `Agent` 放在运行时外壳位置，保留 `core/__init__.py` 作为公共 re-export façade。
- 更新仓内生产代码、测试和文档中的内部 import，消除旧平铺路径依赖。
- 增加包结构、公共导出、循环依赖和分层边界回归检查。
- **BREAKING** 不保留内部模块的旧平铺 import 兼容别名；公共 `codeagent.core` 导出保持不变。

## Capabilities

### New Capabilities

无。本变更是纯结构重构，行为由现有 core、contract 和 integration 测试保护。

### Modified Capabilities

无。不会改变工具协议、上下文预算、事件语义、会话持久化或模型接口。

## Impact

- 影响 `src/codeagent/core/` 全部模块的物理路径和内部 import；仅保留 `agent.py` 与 `__init__.py` 作为根级入口。
- 影响直接导入 `codeagent.core.<module>` 的仓内测试、session、app composition 和文档示例。
- 不新增依赖，不改变 `codeagent.core` 公共导出，不改变 JSONL、消息和事件格式。
- 由于是纯重构，OpenSpec 使用 `skip_specs: true`，不新增行为规格。
