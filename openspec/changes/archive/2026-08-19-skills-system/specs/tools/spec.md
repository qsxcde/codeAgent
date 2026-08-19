# tools Delta Specification

## MODIFIED Requirements

### Requirement: 工具注册与装配

系统 SHALL 通过 `make_tools` 工厂装配八个原子工具,名称固定为 `read`、`write`、`edit`、`bash`、`grep`、`find`、`ls`、`skill`。每个工具 SHALL 对外暴露稳定的名称、描述与输入参数 schema,供编排层绑定;`skill` 工具 SHALL 在装配时注入技能注册表(组合根提供),不读取配置、不跨层。

#### Scenario: 工厂产出全部工具

- **WHEN** 调用 `make_tools` 装配工具集
- **THEN** 返回的工具列表中包含全部八个名称:read、write、edit、bash、grep、find、ls、skill

#### Scenario: 装配时注入工作目录

- **WHEN** `make_tools` 收到的配置含 `cwd`
- **THEN** 全部八个工具都以该 `cwd` 为相对路径解析基准

#### Scenario: 技能工具注入注册表

- **WHEN** 装配 `skill` 工具
- **THEN** 技能注册表由组合根注入,工具按名称查找技能;未注入注册表时工具返回不可用提示
