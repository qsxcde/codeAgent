## 1. 建立 AI 层契约与模块骨架

- [x] 1.1 新增 `ai/model/`，将 `ChatMessage`、AI `ToolCall`、`ChatResponse` 和模型流事件整理到 `types.py`，保持现有字段、事件顺序和序列化语义不变
- [x] 1.2 在 `ai/model/protocols.py` 定义最小的 `ChatClient`、`Provider` 与必要的 `Transport` Protocol，并让旧 `ai.protocol` 入口通过兼容导出指向新契约
- [x] 1.3 新增 `ai/providers/base.py` 与 `ai/providers/all.py`，把内置 provider 集合从 `ai/__init__.py` 和目录解析逻辑中分离，同时保持现有 provider id 集合不变
- [x] 1.4 新增 `ai/transport/base.py`，明确传输层接收的请求、工具定义和流事件边界，不引入 `core` 或具体工具类依赖

## 2. 迁移传输、provider 与目录边界

- [x] 2.1 将 SSE 帧解析实现归入 `ai/transport/sse.py`，将 provider 无关事件映射到 `ai.model` 类型，并保留多行 data、DONE、usage、thinking 和 tool-call delta 行为
- [x] 2.2 更新 `ai/transport/openai_compat.py` 使用 AI 层中立消息、工具定义和事件协议，移除对 `codeagent.core`、`codeagent.tools` 或应用层类型的直接依赖
- [x] 2.3 更新各 provider 配置和构造函数，使环境文件路径、凭据、base URL、模型规格和 reasoning effort 由调用方显式注入；移除 provider 对 `codeagent.app.config` 的导入
- [x] 2.4 修改 `ModelStore` 接收显式模型目录路径，不在 AI 层默认读取 `app.config` 常量；保留文件缺失、损坏文件和坏记录跳过的现有行为
- [x] 2.5 保持 `catalog` 只依赖模型类型和自身存储逻辑，移除 `ModelRegistry` 对 provider 工厂注册表的反向依赖，并补充目录与 provider 可用性分离的测试

## 3. 将应用装配移出 AI 层

- [x] 3.1 将 `ai/factory.py` 的模型选择与客户端构造实际实现迁移到 `app/composition/`，由组合根读取 `Settings`、创建 `ModelRegistry`、选择 provider 并注入配置
- [x] 3.2 将 `ai/model_pattern.py` 的 `model:effort` 解析迁移到应用组合/选择模块，使 provider 只接收已解析的模型 id 与 effort
- [x] 3.3 保持 `ChatModelPort` 在 `app/composition/model_factory.py`，集中完成 core 消息、AI 消息、core 流事件和 AI 流事件之间的适配，以及 system prompt 注入
- [x] 3.4 更新 container、TUI、CLI 和测试的内部导入路径；为旧 `ai.factory`、`ai.model_pattern`、`ai.protocol` 路径保留短期 re-export，并标明迁移边界
- [x] 3.5 确认 `ai/__init__.py` 不再导出应用级 `create_llm` 或在导入时读取设置、构造默认 registry 和加载全部 provider

## 4. 工具定义与跨层适配回归

- [x] 4.1 增加中立 `ToolDefinition` 或等价协议，并在组合根完成内置工具、MCP 工具和其他工具对象到模型 schema 的转换
- [x] 4.2 保留并更新 provider、transport、SSE、FakeClient、模型目录和工具 schema 测试，覆盖请求体、流事件、工具调用、usage、重试和参数错误语义
- [x] 4.3 增加 AI 层依赖方向测试，确保 `src/codeagent/ai/` 不导入 `codeagent.app`、`codeagent.core`、`codeagent.session` 或 `codeagent.tools`
- [x] 4.4 增加组合根装配测试，覆盖默认配置、显式环境文件、用户模型目录、provider/model/effort 选择和 FakeClient 离线路径

## 5. 清理兼容层并完成验证

- [x] 5.1 使用仓库搜索确认所有内部调用方已迁移到新模块路径，只有明确列入兼容范围的旧入口仍被引用
- [x] 5.2 根据兼容策略删除不再需要的旧实现文件或保留仅含弃用 re-export 的模块，并更新 AI 层文档和模块说明
- [x] 5.3 运行 AI 相关测试、完整测试、依赖方向检查、`openspec validate --specs`、构建和编译检查，确认行为未发生变化
