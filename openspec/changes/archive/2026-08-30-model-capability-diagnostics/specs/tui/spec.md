## ADDED Requirements

### Requirement: 模型能力诊断展示

TUI SHALL 在 `/status` 中展示当前 provider/model 的上下文窗口及来源、思考、工具调用和 prompt cache 能力；每项 SHALL 显示支持、不支持或未知，且不得把未知渲染为不支持。缓存能力声明与实际观测到的缓存命中 SHALL 分开显示。模型热切换成功后，后续 `/status` SHALL 展示新模型快照。

#### Scenario: 查看当前模型能力

- **WHEN** 用户执行 `/status`
- **THEN** 输出包含模型能力分组、上下文窗口及来源、思考、工具调用和缓存状态，同时保留现有运行、工具、上下文和用量诊断

#### Scenario: 未知能力保持诚实

- **WHEN** 模型目录没有工具调用或缓存能力声明
- **THEN** 对应字段显示未知，不显示为不可用，也不阻断模型请求

#### Scenario: 模型切换刷新诊断

- **WHEN** 用户通过 `/model` 或 `/provider` 热切换成功
- **THEN** 状态栏诊断状态和下一次 `/status` 使用新模型的能力、窗口及来源

#### Scenario: 缓存声明与观测分离

- **WHEN** 当前模型声明支持缓存但会话尚未收到缓存 usage，或已收到 cached tokens
- **THEN** 输出分别显示能力声明和未观测/实际命中信息，不用累计用量伪造模型能力

#### Scenario: 状态读取无副作用

- **WHEN** 用户查看模型能力诊断
- **THEN** TUI 不发起网络或模型请求，不执行工具，不修改会话历史或 JSONL
