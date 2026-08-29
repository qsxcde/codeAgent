## ADDED Requirements

### Requirement: 外部检索器可选加速与回退

`grep` SHALL 在 `rg` 可用且调用成功时允许使用 `rg` 加速，`find` SHALL 在 `fd` 可用且调用成功时允许使用 `fd` 加速；外部检索器不可用、平台不支持、超时、启动失败、返回执行错误或输出无法解析时 SHALL 回退到现有纯 Python 实现。外部命令 SHALL 使用不经过 shell 的参数列表调用，用户输入不得拼接为 shell 命令；加速路径输出 SHALL 继续遵守既有 pattern/glob、上下文、二进制跳过、噪声目录、相对路径、limit 和输出治理语义。

#### Scenario: rg 加速 grep

- **WHEN** 当前环境存在可执行 `rg` 且其搜索成功
- **THEN** `grep` 使用外部结果并按既有格式返回匹配、行号和上下文，不启动 shell

#### Scenario: fd 加速 find

- **WHEN** 当前环境存在可执行 `fd` 且其枚举成功
- **THEN** `find` 使用外部枚举结果，再应用现有 glob、噪声目录、相对路径和 limit 语义

#### Scenario: 可选依赖缺失

- **WHEN** `rg` 或 `fd` 不在 PATH 或不可执行
- **THEN** 对应工具直接使用纯 Python 实现，用户看到的搜索结果和错误语义不因缺失依赖改变

#### Scenario: 外部检索器失败

- **WHEN** 外部命令启动失败、超时、参数不支持、返回执行错误或输出无法解析
- **THEN** 对应工具放弃外部结果并回退纯 Python 实现，不把可选加速器故障升级为工具故障

#### Scenario: 外部调用安全

- **WHEN** pattern、path、glob 或其它搜索参数包含 shell 元字符
- **THEN** 外部调用仍以独立参数执行，不经过 shell，不执行参数中的命令替换或管道

#### Scenario: 外部输出受限

- **WHEN** 外部检索器产生超过工具资源上限的输出
- **THEN** 读取保持有界并遵守现有输出截断/limit 语义；若无法形成可靠结果则回退纯 Python
