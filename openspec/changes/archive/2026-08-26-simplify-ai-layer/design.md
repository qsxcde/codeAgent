## Context

当前 AI 实现已经具备四个相对稳定的基础能力：模型消息与响应协议、各 provider 的认证与客户端构造、OpenAI-compatible HTTP/SSE 传输、以及内置目录和用户 `models.json` 的合并。但这些能力之外，`ai/factory.py` 还承担应用配置读取和模型选择，provider 与目录存储又直接导入 `app.config`，使 AI 层无法作为独立基础设施使用。

本设计遵循两个约束：`core/` 不能依赖 AI，AI 不能反向依赖 `app`、`session`、`tools`；应用配置、ReAct 所需的核心消息和工具实现都只能在组合根或适配层完成转换。现有 `ChatModelPort` 保留在 `app/composition/model_factory.py`，它是 AI 客户端到 `core.ModelPort` 的边界适配器，不属于 AI 基础设施。

## Goals / Non-Goals

**Goals:**

- 让 `ai/` 只保留模型契约、provider、transport、catalog 四类职责。
- 将 AI 层依赖收敛为标准库、第三方 HTTP/配置库和 AI 层内部模块；路径、凭据、应用配置和工具 schema 均通过参数或中立类型注入。
- 把“模型目录描述”和“可执行模型客户端”保持为两个概念，避免目录层持有 provider 运行时状态。
- 让新增 provider 主要局部于 `ai/providers/`、对应 catalog 和显式注册集合，不要求修改 ReAct、session 或工具层。
- 在不改变现有运行时行为的前提下，允许分阶段迁移并保留必要的短期兼容导出。

**Non-Goals:**

- 不在本变更中实现动态模型发现、远程模型目录刷新、OAuth 或新的 provider。
- 不把 ReAct 循环、session、memory、MCP、skill 或工具权限移动到 AI 层。
- 不把 `core.messages.Message`、`core.events.StreamEvent` 或实际工具类复用为 AI 层公共类型；两层之间继续通过组合根适配。
- 不要求一次性引入完整的 Pi 风格运行时 `Models` 对象；先完成边界和依赖治理，后续再按需要增加 provider 集合抽象。

## Decisions

### 1. 采用四个 AI 子包，而不是按应用流程拆分

目标结构为：

```text
ai/
├── model/
│   ├── __init__.py
│   ├── types.py          # ChatMessage、ToolCall、ChatResponse、ModelEvent、工具定义
│   └── protocols.py      # ChatClient、Provider、Transport 等协议
├── providers/
│   ├── __init__.py       # 轻量公共导出
│   ├── base.py           # provider 抽象及构造参数
│   ├── all.py            # 显式内置 provider 集合
│   ├── deepseek.py
│   ├── fake.py
│   ├── glm.py
│   ├── kimi.py
│   ├── minimax.py
│   ├── openai.py
│   └── qwen.py
├── transport/
│   ├── __init__.py
│   ├── base.py           # HTTP/流式传输协议
│   ├── openai_compat.py
│   └── sse.py
└── catalog/
    ├── __init__.py
    ├── spec.py
    ├── builtin.py
    ├── registry.py
    └── store.py
```

`ai/model/` 是 provider、transport 和组合根共享的最小契约层；`providers/` 负责供应商差异；`transport/` 负责线协议和网络生命周期；`catalog/` 负责静态模型元数据、别名和用户覆盖。`ai/` 根包不再导出应用装配函数，也不在导入时读取配置或创建客户端。

备选方案是保留当前 `protocol/` 命名，仅将 `factory.py` 移出。该方案改动较小，但无法清楚区分“模型领域类型”和“具体协议/线协议”，并会继续诱导调用方把 SSE 事件和模型事件混在一起，因此不采用。

### 2. 模型契约与应用核心契约分离

`ai/model/types.py` 保留当前 AI 侧的 `ChatMessage`、AI `ToolCall` 和 `ChatResponse`，并增加不依赖具体 HTTP 实现的模型流事件与工具定义。`ai/model/protocols.py` 提供最小的 `ChatClient`、`Provider` 和必要的 `Transport` Protocol。

`app/composition/model_factory.py` 继续负责：

- `core.messages.Message` ↔ `ai.model.ChatMessage` 的转换；
- AI 模型事件 ↔ `core.ports.StreamEvent` 的转换；
- AI 响应中的工具参数解析为 core 工具调用；
- system prompt 注入和 `ChatModelPort` 的构造。

这样可以避免为了复用类型而让 `core` 依赖 `ai`，也避免 transport 直接接收 `tools` 包中的真实工具对象。工具适配器只需向 AI 层提供中立的名称、描述和 JSON Schema。

### 3. 将模型装配和模型选择留在组合根

当前 `ai/factory.py` 中的 `create_llm`、provider 可用性并集、默认 `ModelRegistry` 缓存以及 `Settings` 读取属于应用装配，不属于 AI 运行时。迁移后在 `app/composition/model_factory.py` 或同目录的新 `model_selection.py` 中完成：

1. 读取 `Settings` 和应用级路径；
2. 解析 `model:effort` 这种 CLI/产品输入语法；
3. 创建 `ModelStore` / `ModelRegistry`；
4. 从显式 provider 集合选择 provider；
5. 注入凭据、base URL、模型规格和 reasoning effort，创建 AI `ChatClient`；
6. 包装成 `ChatModelPort` 交给 core。

`ai/model_pattern.py` 随选择逻辑移出 AI 层。AI provider 只接收已经解析的模型 id 和 effort，不感知命令行字符串语法。

备选方案是继续把 `create_llm` 放在 `ai` 并通过回调读取配置。这样表面上减少迁移，但 AI 仍然隐式知道应用装配流程，测试和复用边界不清，因此不采用。

### 4. Provider 只处理 provider 差异，配置来源由外部注入

每个 provider 模块保留其配置模型、默认模型、API 端点和 provider 特有请求参数，并实现统一的 provider 构造协议。provider 可以依赖 `catalog` 和 `transport`，但不得导入 `codeagent.app.config`。

环境文件路径、配置目录、API key 和用户覆盖文件路径由组合根显式传入。对于现有 Pydantic Settings 配置，优先让构造函数接收 `_env_file` 或已经解析的配置对象；不要在 provider 模块顶层导入 `CONFIG_ENV_FILE`。`ModelStore` 同样不再使用 app 配置常量作为默认参数，而是要求组合根传入路径，必要时由组合根提供默认路径。

`providers/all.py` 作为内置 provider 的显式集合，避免 `ai/catalog` 反向导入 `providers`，也避免 `ai/__init__.py` 通过副作用加载所有 provider。第一阶段可以继续使用字典分发以保持行为兼容；provider 对象化和真正惰性加载不是本变更的强制条件。

### 5. Transport 只负责线协议和网络生命周期

`transport/openai_compat.py` 保留 HTTP 请求、重试、超时、响应解析、工具 schema 序列化和关闭客户端等职责；`transport/sse.py` 解析 SSE 帧并产出 AI 层中立流事件。transport 不读取应用配置、不解析 `model:effort`、不依赖 `core`，也不直接依赖具体的 `AtomicTool` / MCP 工具类。

如果当前工具 schema 序列化依赖工具对象的 duck typing，则先在 transport 边界收敛为中立的 `ToolDefinition`，由组合根或工具适配层完成转换。这样 MCP、Skill 和内置工具可以共享模型调用入口，但不需要把它们的生命周期或权限逻辑放进 AI。

`StreamEvent` 若表达的是 provider 无关的模型增量，应放在 `ai/model/types.py`；SSE 的 data 行、DONE 标记和 JSON 拼接逻辑留在 `transport/sse.py`。这避免把 OpenAI SSE 的内部格式泄漏为上层契约。

### 6. Catalog 保持静态描述，不持有运行时客户端

`ModelSpec`、内置目录、`ModelRegistry` 和 `ModelStore` 继续留在 `ai/catalog/`。目录负责 provider/model id、别名、reasoning 能力、上下文窗口和 token 上限等元数据，并保持坏记录跳过、文件缺失可启动、用户覆盖合并等现有行为。

`ModelRegistry` 不直接导入 provider 工厂；provider 可用性并集和模型客户端构造由组合根或 provider 集合负责。这样“目录中存在模型”和“当前环境能够构造客户端”仍是两个独立事实。

暂不将 `ModelSpec` 重命名为 Pi 风格的 `Model`，也不把 `ModelSpec` 与运行时 client 合并。当前项目的静态目录场景不需要引入更重的对象生命周期。

### 7. 依赖方向和公共入口

目标依赖关系为：

```text
ai.model  ←  catalog
    ↑      ←  transport
    ↑      ←  providers ← catalog / transport
    ↑
app.composition → ai.model / catalog / providers / transport
       ↓
    core.ModelPort 适配
```

`ai` 内部不得导入 `codeagent.app`、`codeagent.core`、`codeagent.session` 或 `codeagent.tools`。`app.composition` 可以依赖这些层并负责适配。`ai/__init__.py` 只导出稳定的模型契约、目录类型或明确的公共 API；应用级 `create_llm` 和 provider 选择入口不再从这里导出。

### 8. 采用分阶段迁移并保留兼容导出

迁移按“先建立边界、再移动实现、最后收紧依赖”进行：

- 先新增 `model/` 类型与协议、`providers/base.py`、`transport/base.py`，用 re-export 保持旧导入暂时可用。
- 再把 `factory.py` 和 `model_pattern.py` 的实际实现迁移到 `app/composition/`，更新 container、TUI 和测试调用方。
- 再迁移 `protocol/messages.py` 与 SSE 事件，统一 import 路径并删除或保留标记为 deprecated 的兼容层。
- 最后移除 provider/catalog 对 `app.config` 的导入，加入依赖扫描测试，确认 AI 子树成为独立边界。

回滚策略是每一步保持行为测试通过；若某一步出现兼容问题，暂时恢复旧模块的 re-export 和组合根调用路径，不需要恢复已完成的 core/session/tools 改动，因为这些层不在本次变更中修改。

## Risks / Trade-offs

- [Risk] 旧代码或外部调用方直接导入 `codeagent.ai.factory` / `codeagent.ai.protocol`。→ 分阶段保留 re-export，并为兼容入口增加弃用说明；在所有内部调用方迁移后再删除。
- [Risk] provider 配置初始化依赖隐式环境文件路径，迁移后可能出现默认值变化。→ 先为组合根建立等价的默认路径，再用 FakeClient 与 provider 配置测试覆盖显式路径和默认路径。
- [Risk] AI 工具定义与 core/tool 实例转换不完整，导致 tool schema 或调用参数行为变化。→ 引入中立 `ToolDefinition`，保留现有请求快照、工具调用和参数错误测试，逐 provider 验证 schema。
- [Risk] SSE 事件从具体解析器迁移到中立模型事件时字段语义漂移。→ 先保持字段和事件顺序不变，再将解析实现替换到新路径；现有 SSE/transport 测试作为回归门槛。
- [Risk] provider 显式集合仍然需要导入全部内置模块，暂时没有获得完整惰性加载收益。→ 把惰性加载作为后续独立优化；本变更先保证依赖方向和可维护性。
- [Risk] 兼容 re-export 延长旧边界的生命周期。→ 在任务清单中记录最终删除条件，并用依赖扫描阻止新代码继续引用旧路径。
