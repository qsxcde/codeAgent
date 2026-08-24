## Purpose

为用户提供统一、安全且可复现的 Skill Package 安装方式，使来自 Git 或本地目录的 Skill 集合能够被全局或项目范围注册、更新、删除和重新加载。

## ADDED Requirements

### Requirement: Package 来源与布局

系统 SHALL 支持从 Git URL 和本地目录安装 Skill Package。Package SHALL 通过清单声明或默认约定提供一个 Skill 根目录；根目录下的 `skills/**/SKILL.md` SHALL 被视为可发现的 Skill，包内其它 Harness 的插件目录 SHALL 不被 CodeAgent 自动执行或作为 Skill 入口加载。

#### Scenario: 从 Git URL 安装

- **WHEN** 用户提供有效的 Git URL 安装 Package
- **THEN** 系统下载或更新 Package 到对应作用域的包存储，并发现其 `skills/**/SKILL.md`

#### Scenario: 从本地目录安装

- **WHEN** 用户提供包含 `skills/` 的本地目录安装 Package
- **THEN** 系统注册该目录并发现其中的 Skill，不要求用户手动复制到散落的 Skill 目录

#### Scenario: 缺少 Skill 根目录

- **WHEN** Package 没有清单声明的 Skill 根目录且默认 `skills/` 目录不存在
- **THEN** 安装失败并给出可定位到 Package 的诊断，不改变现有注册表

### Requirement: 安装记录与版本锁定

每个已安装 Package SHALL 持久化唯一 id、名称、来源、作用域、解析后的版本或 Git revision、Skill 根目录和安装状态。Git Package SHALL 记录可复现的 revision；更新 SHALL 先更新记录，再在下一次重新加载或新会话中生效。

#### Scenario: 安装记录可恢复

- **WHEN** CodeAgent 重新启动
- **THEN** 系统从安装记录恢复已安装 Package，并按记录重新发现 Skill

#### Scenario: Git revision 被锁定

- **WHEN** Package 从 Git URL 安装成功
- **THEN** 锁定记录包含解析后的 commit/revision，而不是只有未固定的分支地址

#### Scenario: 更新 Package

- **WHEN** 用户更新一个已安装 Package
- **THEN** 系统解析新的版本或 revision、更新锁定记录并报告更新前后的来源信息

### Requirement: Package 生命周期命令

系统 SHALL 提供安装、列表、更新、删除和重新加载操作；操作失败 SHALL 返回明确诊断且不得破坏已存在的有效 Package 记录。删除 Package SHALL 只移除该 Package 的注册与安装内容，不删除其它作用域或其它 Package 提供的同名 Skill。

#### Scenario: 列出已安装 Package

- **WHEN** 用户请求 Package 列表
- **THEN** 系统返回 Package id、作用域、来源、版本或 revision、Skill 数量和当前状态

#### Scenario: 删除 Package

- **WHEN** 用户删除一个已安装 Package
- **THEN** 系统移除其注册信息和安装内容，并在重新加载后不再提供该 Package 的 Skill

#### Scenario: 删除未知 Package

- **WHEN** 用户删除不存在的 Package id
- **THEN** 系统返回明确错误，不修改任何已有 Package

### Requirement: Package 作用域与安全边界

Package SHALL 支持用户级和项目级作用域。默认安装 SHALL 不执行 Package 中的 JavaScript、TypeScript、Python、Shell 或其它可执行扩展；首版只读取清单、Markdown Skill 和必要的静态引用。Package 目录中的路径 SHALL 被限制在其安装根目录内，路径穿越或非法链接 SHALL 产生诊断并拒绝加载相关文件。

#### Scenario: 用户级 Package 可跨项目使用

- **WHEN** Package 安装到用户级作用域
- **THEN** 该 Package 的 Skill 在用户启动的其它项目中可被发现，除非被更高优先级规则遮蔽

#### Scenario: 项目级 Package 仅在当前项目使用

- **WHEN** Package 安装到项目级作用域
- **THEN** 该 Package 的 Skill 只在该项目上下文中可用

#### Scenario: 可执行扩展保持惰性

- **WHEN** Package 包含插件脚本或 Harness 专用扩展目录
- **THEN** CodeAgent 将其视为非执行资源，不在安装、加载或普通会话中运行

#### Scenario: 路径越界被拒绝

- **WHEN** Package 清单或 Skill 引用解析到安装根目录之外
- **THEN** 系统拒绝该路径并产生可见诊断
