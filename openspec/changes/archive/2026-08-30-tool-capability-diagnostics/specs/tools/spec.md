## MODIFIED Requirements

### Requirement: 工具注册与装配

系统 SHALL 通过 `make_tools` 工厂装配八个原子工具,名称固定为 `read`、`write`、`edit`、`bash`、`grep`、`find`、`ls`、`skill`。每个工具 SHALL 对外暴露稳定的名称、描述与输入参数 schema,供编排层绑定;`skill` 工具 SHALL 在装配时注入技能注册表(组合根提供),工具 SHALL 同时提供只读的运行环境能力快照供诊断和后续能力选择使用;MCP 工具 SHALL 经组合根加载后追加到工具列表(内建工具恒保留),命名含 `mcp__<server>__<tool>` 前缀。

#### Scenario: 工厂产出全部工具

- **WHEN** 调用 `make_tools` 装配工具集
- **THEN** 返回的工具列表中包含全部八个名称:read、write、edit、bash、grep、find、ls、skill

#### Scenario: 装配时注入工作目录

- **WHEN** `make_tools` 收到的配置含 `cwd`
- **THEN** 全部八个工具都以该 `cwd` 为相对路径解析基准

#### Scenario: 技能工具注入注册表

- **WHEN** 装配 `skill` 工具
- **THEN** 技能注册表由组合根注入,工具按名称查找技能;未注入注册表时工具返回不可用提示

#### Scenario: MCP 工具追加

- **WHEN** 用户级 MCP 配置存在且 server 加载成功
- **THEN** 工具列表在八个内建工具之后追加 MCP 工具(`mcp__<server>__<tool>` 命名),内建工具不受影响

#### Scenario: 能力快照可用于诊断

- **WHEN** 工具工厂或运行时请求当前环境能力
- **THEN** 系统返回稳定的只读能力快照,至少列出 shell、平台、外部检索器和权限策略,每项包含可用性及缺失原因,且不执行工具调用或修改会话状态

## ADDED Requirements

### Requirement: 工具环境能力探测

工具层 SHALL 提供平台无关的只读能力探测。探测结果 SHALL 至少覆盖真实 shell、操作系统平台、可选外部检索器(`rg`、`fd`)和文件/命令权限策略;每项 SHALL 包含稳定名称、`available` 状态以及面向用户的诊断代码和消息。探测 SHALL 使用当前注入的环境和工作目录,不可用依赖 SHALL 被明确标记而不是抛出未处理异常或静默降级为可用。探测 SHALL 不执行任意用户命令、不读取工具结果、不写入文件,且同一环境下结果可重复。

#### Scenario: 完整能力探测

- **WHEN** 当前环境提供 shell、平台信息、`rg`/`fd` 中的一项或多项以及安全策略
- **THEN** 返回所有能力项及其可用状态、解析路径或策略说明,而不是只返回成功项

#### Scenario: 缺少 shell

- **WHEN** 当前平台没有可解析的真实 shell
- **THEN** shell 能力为不可用,诊断包含稳定的缺失代码和安装或配置指引,其它能力仍正常返回

#### Scenario: 可选检索器缺失

- **WHEN** `rg` 或 `fd` 不在 PATH 或不可执行
- **THEN** 对应能力标记为不可用并说明将使用纯 Python 路径,不把缺失可选依赖报告为工具故障

#### Scenario: 平台能力可识别

- **WHEN** 在 Windows、macOS 或 Linux 环境执行探测
- **THEN** 平台项使用稳定的标准标识,并说明 shell 解析和进程清理等平台相关能力是否可用

#### Scenario: 权限策略可识别

- **WHEN** 工具安全分类器已装配
- **THEN** 权限策略能力标记为可用并说明读写边界、确认和拒绝策略;未装配时标记为不可用并给出诊断,不执行越权探测

#### Scenario: 探测无副作用

- **WHEN** 用户查看能力快照或 TUI `/status` 读取能力
- **THEN** 不启动 shell/检索命令、不触发确认、不修改文件或会话 JSONL,重复读取返回等价结果

#### Scenario: 状态输出暴露诊断

- **WHEN** 用户查看 TUI `/status`
- **THEN** 状态输出包含能力分组及每项的可用/不可用状态和必要诊断,并保留现有运行、上下文和用量信息
