## Why

V4-38 需要让用户在真正发起请求前知道当前模型的上下文窗口、思考、工具调用和缓存能力。现有实现只分散保存窗口/思考元数据，工具调用是传输层的隐式行为，缓存只有收到 usage 后才显示，无法形成可信且可解释的模型诊断。

## What Changes

- 增加模型能力快照，统一记录上下文窗口及来源、思考、工具调用和 prompt cache 能力。
- 使用“支持 / 不支持 / 未知”三态，缺失目录或适配器事实时明确展示未知，不把未知误报为不支持。
- 在组合根生成快照并注入模型端口和 TUI；`/status` 展示当前模型的完整能力，模型热切换后同步刷新。
- 区分目录声明的缓存能力与实际 usage 命中的缓存事实；诊断读取不发起网络探测、不改变会话持久化。
- 保持 `ModelSpec` 旧字段和 `models.json` 既有记录兼容，新增字段可选，不引入依赖。

## Capabilities

### New Capabilities

- `model-capabilities`: 定义模型能力快照、来源和未知状态的诊断契约。

### Modified Capabilities

- `tui`: `/status` 增加当前模型能力诊断，并在模型热切换后刷新。

## Impact

- 影响 `src/codeagent/ai/catalog`、`src/codeagent/app/composition/model`、运行时配置和 TUI 状态/命令展示。
- 增加模型目录字段的严格解析和组合根注入，不改变 core 依赖方向、Provider 请求格式或 JSONL 会话格式。
- 增加目录解析、组合根、模型切换、状态文本和未知/缓存观测边界的离线回归测试。
