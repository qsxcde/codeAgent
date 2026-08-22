## ADDED Requirements

### Requirement: /status 显示用量

TUI `/status` 命令输出 SHALL 包含会话累计用量行:输入 token、输出 token(推理 token 并入输出)、缓存命中率;缓存命中率 SHALL 按「约 cached/input」估算并钳制在 0~100%,标注为估算值;无用量记录时 SHALL 显示空态提示。

#### Scenario: 显示累计用量

- **WHEN** 会话存在已落库的用量记录且用户执行 `/status`
- **THEN** 输出包含用量行,展示输入 token、输出 token(含推理)与缓存命中率(约 X%,含原始命中/输入计数)

#### Scenario: 无用量空态

- **WHEN** 会话尚无任何用量记录且用户执行 `/status`
- **THEN** 用量区块显示空态提示(如「用量: (无)」),不展示误导性数值

#### Scenario: 缓存命中率边界

- **WHEN** 缓存命中 token 大于输入 token 或输入为 0
- **THEN** 命中率钳制在 0~100%(有命中显示 100%,无命中显示 0%),原始计数仍如实展示
