## Why

当前 `ai/` 同时承担模型协议、供应商实现、HTTP/SSE 传输、模型目录、应用配置读取、模型选择语法和模型客户端装配，导致 AI 层反向依赖 `app`，组合根职责被分散，新增供应商或调整应用配置时需要跨越多个层次。现在先收敛 AI 层边界，可以让 ReAct 核心、会话、工具、MCP 和 Skill 作为上层能力组合，而不被模型基础设施反向耦合。

## What Changes

- 将 `ai/` 收敛为四类职责：模型契约与数据类型、供应商、传输、模型目录。
- 将模型客户端构造、应用配置读取、provider/model/effort 选择和 `model:effort` 解析移至 `app/composition/`。
- 将现有消息协议归入模型契约，将 SSE 解析归入传输层；补充明确的 Provider/Transport 基础协议，保持模型目录与运行时客户端解耦。
- 移除 AI 层对 `app.config`、`core`、`session` 和 `tools` 的反向依赖；配置路径、凭据和工具定义由组合根以中立对象或显式参数注入。
- 将供应商注册从 `ai/__init__.py` 的隐式装配中分离，保留显式的内置 provider 集合，并为后续惰性加载和扩展供应商预留边界。
- 保持现有 provider、FakeClient、OpenAI 兼容传输、模型目录合并和 `ChatModelPort` 的外部行为兼容；本变更是内部架构重构，不新增对外业务能力。

## Capabilities

### New Capabilities

无。本变更不新增用户可观察能力。

### Modified Capabilities

无。本变更不改变现有 OpenSpec 规格中的运行时行为，仅调整内部模块边界和依赖方向，因此本变更启用 `skip_specs: true`。

## Impact

- 主要影响 `src/codeagent/ai/`、`src/codeagent/app/composition/` 及其对应测试导入路径。
- 可能需要为旧导入保留短期兼容 re-export，或同步更新内部调用方与测试。
- provider 配置类仍属于 AI 层，但环境文件路径和应用配置对象不再由 AI 层自行取得。
- 模型目录仍支持内置目录与用户 `models.json` 合并；目录文件路径改由组合根显式传入。
- ReAct、session、tools、MCP、Skill 的行为和规格不在本变更范围内。
