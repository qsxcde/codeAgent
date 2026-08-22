# mcp Delta Specification

## Purpose

定义 MCP(Model Context Protocol)客户端能力的对外行为契约:MCP server 配置与信任边界、后台线程桥接、外部工具接入(命名/适配/分组预算)、失败语义与加载结果可见性。MCP 是工具扩展的唯一通道(插件系统已移出),server 由用户显式配置 = 信任。

## ADDED Requirements

### Requirement: MCP server 配置与信任边界

MCP server SHALL 通过用户级配置文件(`<config_dir>/mcp.json`)声明:每个 server SHALL 含名称、启动命令与参数(stdio 形态);配置文件缺失/为空 SHALL 视为无 MCP 工具,不报错;项目级配置(仓库内 `.mcp.json`)SHALL 不被加载(仓库引导启动外部进程是恶意向量)。

#### Scenario: 用户配置 server

- **WHEN** `<config_dir>/mcp.json` 声明一个 server
- **THEN** 装配时按命令启动该 server 并接入其工具

#### Scenario: 无配置文件

- **WHEN** `<config_dir>/mcp.json` 不存在或为空
- **THEN** 不产生任何 MCP 工具,装配正常继续

#### Scenario: 项目级配置被忽略

- **WHEN** 仓库内存在 `.mcp.json` 或项目级 MCP 配置
- **THEN** 该配置不被加载,不启动任何进程

### Requirement: 外部工具接入

MCP server 的工具 SHALL 以 `mcp__<server>__<tool>` 命名接入工具列表,与内建工具(名称不含 `:` 前缀)不冲突;工具参数 SHALL 透传 server 声明的 JSON Schema 语义(server 自行校验);工具结果 SHALL 以文本回填,server 标记的错误 SHALL 以错误结果回填;MCP 工具调用 SHALL 复用既有执行超时保护。

#### Scenario: 工具命名带前缀

- **WHEN** server "github" 声明工具 "list_issues"
- **THEN** 接入的工具名为 `mcp__github__list_issues`,与内建工具名不冲突

#### Scenario: 调用成功回填文本

- **WHEN** 模型调用 MCP 工具且 server 正常返回
- **THEN** 工具结果以文本形式回填消息历史

#### Scenario: 调用错误回填错误

- **WHEN** server 返回错误或调用超时/崩溃
- **THEN** 该调用以错误结果回填,不中断本轮其余工具

### Requirement: MCP 权限规则

MCP 工具调用 SHALL 受权限规则约束:规则 SHALL 支持三级动作 deny / ask / allow 与三种粒度(全部 `mcp__*`、server 级 `mcp__<server>`、工具级 `mcp__<server>__<tool>`),命中优先级 SHALL 为 deny > ask > allow;未命中 SHALL 默认放行(用户级配置即信任);headless 形态下 ask SHALL 降级 deny(未确认不得执行);无权限配置 SHALL 视为全部放行。

#### Scenario: deny 拒绝

- **WHEN** 调用命中 deny 规则
- **THEN** 该调用被拒绝,拒绝原因回填模型

#### Scenario: ask 确认

- **WHEN** 调用命中 ask 规则
- **THEN** 交互形态发出确认请求,确认后执行;headless 形态降级拒绝

#### Scenario: 优先级 deny > ask > allow

- **WHEN** 同一工具同时命中多条规则
- **THEN** 按 deny > ask > allow 顺序取最高优先级动作

#### Scenario: 未命中默认放行

- **WHEN** 调用未命中任何规则或无权限配置
- **THEN** 该调用正常执行

### Requirement: 分组预算

MCP 工具接入 SHALL 受分组预算约束:全局工具数上限与每 server 工具数上限(可配置默认值),超限工具 SHALL 被裁剪且产生可见诊断(不静默丢弃);工具描述 SHALL 按长度截断以控制提示词膨胀;内建工具 SHALL 恒保留。

#### Scenario: 超限裁剪出诊断

- **WHEN** 某 server 工具数超过每 server 上限或总量超过全局上限
- **THEN** 超出部分被裁剪,诊断列出被裁剪工具与原因

#### Scenario: 内建工具恒保留

- **WHEN** MCP 工具与内建工具合计超限
- **THEN** 内建工具优先保留,MCP 工具按确定性顺序裁剪

#### Scenario: 描述截断

- **WHEN** 工具描述超过长度上限
- **THEN** 描述被截断并标记,工具仍可用

### Requirement: 装配失败语义与可见性

server 启动失败 / 初始化失败 / 工具列表获取失败时,该 server SHALL 被跳过并产生诊断,不中断整体装配;已加载的 MCP 工具 SHALL 出现在工具列表中(与内建工具并列);加载诊断 SHALL 对用户可见(与技能诊断并列展示)。

#### Scenario: server 失败跳过

- **WHEN** 某 server 启动或初始化失败
- **THEN** 该 server 不接入任何工具,产生诊断,其余 server 与内建工具照常

#### Scenario: 诊断可见

- **WHEN** 装配产生 MCP 诊断(失败或裁剪)
- **THEN** 诊断对用户可见,可展示可断言

## MODIFIED Requirements

### Requirement: 工具注册与装配

系统 SHALL 通过 `make_tools` 工厂装配八个原子工具,名称固定为 `read`、`write`、`edit`、`bash`、`grep`、`find`、`ls`、`skill`。每个工具 SHALL 对外暴露稳定的名称、描述与输入参数 schema,供编排层绑定;`skill` 工具 SHALL 在装配时注入技能注册表(组合根提供),不读取配置、不跨层;MCP 工具 SHALL 经组合根加载后追加到工具列表(内建工具恒保留),命名含 `{server}:{tool}` 前缀。

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
- **THEN** 工具列表在八个内建工具之后追加 MCP 工具(`{server}:{tool}` 命名),内建工具不受影响
