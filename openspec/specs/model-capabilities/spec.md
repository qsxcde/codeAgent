# model-capabilities Specification

## Purpose

定义与具体 UI 和网络探测无关的模型能力诊断契约，让应用能够解释当前模型可以做什么、哪些事实来自目录，以及哪些能力尚未确认。

## Requirements

### Requirement: 模型能力快照

系统 SHALL 为当前模型提供不可变的能力快照。快照 SHALL 至少包含模型标识、provider、上下文窗口及其来源、思考能力、工具调用能力和 prompt cache 能力；能力状态 SHALL 使用支持、不支持或未知三态表示。快照 SHALL 不依赖本轮 provider 请求才能生成。

#### Scenario: 目录提供完整元数据

- **WHEN** 模型目录记录包含上下文窗口、思考、工具调用和缓存能力
- **THEN** 快照保留这些值及目录来源，调用方可以在请求前读取完整能力

#### Scenario: 能力事实缺失

- **WHEN** 目录或适配器没有确认某项能力
- **THEN** 该项为未知而不是不支持，窗口来源同时标记为 fallback 或 unknown，应用仍可继续使用既有兼容默认值

#### Scenario: 模型切换

- **WHEN** 组合根切换 provider、模型或思考强度
- **THEN** 下一次运行使用新模型对应的新快照，不沿用旧模型的能力或窗口来源

### Requirement: 能力元数据兼容解析

模型目录 SHALL 继续接受没有新增能力字段的既有记录；新增能力字段 SHALL 进行严格布尔校验，并支持用户覆盖内置模型。非法字段 SHALL 跳过对应记录并产生诊断，不得把字符串、数字或布尔值混合转换成能力事实。

#### Scenario: 旧目录记录

- **WHEN** 用户模型记录只包含既有 id、reasoning、窗口或别名字段
- **THEN** 记录仍可加载，未声明的工具调用和缓存能力为未知

#### Scenario: 用户覆盖能力

- **WHEN** 用户模型记录声明工具调用或 prompt cache 能力
- **THEN** 解析后的模型规格保留覆盖值，并在最终快照中可见

#### Scenario: 非法能力字段

- **WHEN** 新增能力字段不是严格布尔值
- **THEN** 该模型记录被拒绝并记录明确诊断，不静默强制类型

### Requirement: 观测缓存与声明分离

系统 SHALL 将模型目录声明的 prompt cache 能力与 provider usage 中实际观测的缓存 token 分开表示。没有 usage 时不得推断缓存命中；收到 usage 后 SHALL 只更新运行期观测，不改写能力声明。

#### Scenario: 尚无缓存 usage

- **WHEN** 当前会话还没有 provider 返回的缓存 token
- **THEN** 快照仍显示声明能力的支持/不支持/未知，观测值显示未观测

#### Scenario: 收到缓存 usage

- **WHEN** provider 返回本轮 cached tokens
- **THEN** `/status` 可以同时显示声明能力和实际观测值，二者不互相覆盖

### Requirement: 诊断读取无副作用

能力快照的构建和读取 SHALL 是只读操作，不得发起 `/models` 或其它网络探测，不得执行 shell/工具，不得修改会话历史、JSONL 或模型请求配置。相同输入的快照 SHALL 可重复比较。

#### Scenario: 离线查看能力

- **WHEN** TUI 或其它应用层读取当前模型能力
- **THEN** 只消费组合根已装配的快照，不产生外部进程、网络请求或持久化写入
