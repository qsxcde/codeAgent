# skills Delta Specification

## Purpose

定义技能(Skills)系统的对外行为契约:SKILL.md 格式与多源发现、加载与同名遮蔽、渐进式披露注入、技能工具获取正文、用户手动加载,以及加载结果的可见性。技能是可复用的操作规程,模型按需调用,用户可手动指定。

## ADDED Requirements

### Requirement: SKILL.md 格式与发现

技能 SHALL 以"一技能一目录"组织,技能定义文件名为 `SKILL.md`;`SKILL.md` SHALL 由 YAML frontmatter 与 Markdown 正文组成;frontmatter 的 `name` SHALL 缺省取所在目录名;`description` SHALL 缺省取正文第一段;frontmatter 解析失败或解析后缺少可用 name/description 时 SHALL 产生诊断且不加载该技能;技能发现 SHALL 覆盖三类来源:内建(包内 `resources/skills/`)、个人级(`<config_dir>/skills/`)、项目级(`<cwd>/.codeagent/skills/`);来源目录不存在 SHALL 静默跳过。

#### Scenario: 合法技能被加载

- **WHEN** 技能目录包含 frontmatter 完整的 `SKILL.md`
- **THEN** 该技能进入注册表,名称与描述取自 frontmatter

#### Scenario: name 缺省为目录名

- **WHEN** `SKILL.md` frontmatter 未声明 `name`
- **THEN** 技能名取所在目录名

#### Scenario: description 缺省为正文第一段

- **WHEN** `SKILL.md` frontmatter 未声明 `description`
- **THEN** 技能描述取正文第一段,不产生诊断

#### Scenario: 解析失败跳过

- **WHEN** `SKILL.md` 的 frontmatter 无法解析(YAML 语法错误)
- **THEN** 该技能不加载,产生诊断;其它技能照常加载

#### Scenario: 缺少可用名称与描述

- **WHEN** `SKILL.md` 既无 `name`/`description` 也无可用正文
- **THEN** 该技能不加载,产生诊断

#### Scenario: 三类来源发现

- **WHEN** 内建、个人级、项目级来源均存在技能
- **THEN** 全部进入加载流程,来源目录不存在或为空时静默跳过

### Requirement: 加载与同名遮蔽

技能注册 SHALL 以名称唯一标识;同名技能 SHALL 按 个人级 > 项目级 > 内建 的优先级遮蔽,仅最高优先级者进入注册表;被遮蔽技能 SHALL 产生诊断并标注遮蔽关系(谁遮蔽了谁);注册表 SHALL 按名称排序输出;同一绝对路径 SHALL 只加载一次。

#### Scenario: 个人遮蔽项目

- **WHEN** 个人级与项目级存在同名技能
- **THEN** 个人级技能进入注册表,项目级技能被遮蔽并产生诊断

#### Scenario: 任意级遮蔽内建

- **WHEN** 项目级或个人级存在与内建同名的技能
- **THEN** 该技能进入注册表,内建技能被遮蔽并产生诊断

#### Scenario: 注册表排序

- **WHEN** 加载完成
- **THEN** 注册表按技能名称排序(字典序)

#### Scenario: 路径去重

- **WHEN** 同一 `SKILL.md` 被多个来源指向同一绝对路径
- **THEN** 只加载一次,不重复注入

### Requirement: 渐进式披露注入

system 提示词 SHALL 追加技能段:每个已注册技能 SHALL 以一行呈现(名称、描述、来源路径),按名称排序;技能段 SHALL 位于分层上下文段之后;技能正文 SHALL 不进入 system 提示词,按需经技能工具获取。

#### Scenario: 描述行注入

- **WHEN** 注册表存在技能
- **THEN** system 提示词包含技能段,每个技能一行(名称/描述/来源路径),按名称排序,位于分层上下文之后

#### Scenario: 正文不预载

- **WHEN** system 提示词注入技能段
- **THEN** 技能正文不进入提示词

#### Scenario: 无技能不产生空段

- **WHEN** 注册表为空
- **THEN** system 提示词不产生技能段

### Requirement: 技能工具

系统 SHALL 提供名为 `skill` 的工具,以技能名为唯一参数;命中已注册技能时 SHALL 返回渲染后的技能正文块(含技能名、来源路径标注与正文,标注技能内相对路径以技能目录为基准);未命中 SHALL 返回明确错误并列出可用技能名。

#### Scenario: 命中返回渲染块

- **WHEN** 模型调用 `skill` 工具且技能名已注册
- **THEN** 返回渲染后的技能正文块,包含技能名、来源路径与正文

#### Scenario: 未命中报错并列出

- **WHEN** 模型调用 `skill` 工具且技能名未注册
- **THEN** 返回明确错误,并列出全部可用技能名

#### Scenario: 正文含来源标注

- **WHEN** 技能正文被渲染
- **THEN** 渲染块标注技能来源路径,并说明正文内相对引用以技能目录为基准

### Requirement: 技能可被用户手动加载

用户显式加载技能时,技能正文 SHALL 以一条注入消息进入会话并立即触发一轮回复;注入消息 SHALL 标注技能名与来源路径;该机制 SHALL 不依赖模型自主调用技能工具;加载不存在的技能 SHALL 反馈明确错误。

#### Scenario: 手动加载注入正文

- **WHEN** 用户显式加载一个已注册技能
- **THEN** 技能正文以一条标注了技能名与来源的注入消息进入会话

#### Scenario: 立即触发回复

- **WHEN** 用户显式加载技能
- **THEN** 会话立即触发一轮回复,模型在收到注入消息后继续执行

#### Scenario: 不依赖模型调用

- **WHEN** 用户显式加载技能
- **THEN** 技能正文直接注入,无需模型先调用技能工具

#### Scenario: 加载不存在的技能

- **WHEN** 用户显式加载未注册的技能名
- **THEN** 反馈明确错误,列出可用技能名,不注入任何内容

### Requirement: 加载结果可见

技能加载结果 SHALL 可查询:已加载技能列表(名称/描述/来源路径)与加载诊断(解析失败、被遮蔽及其遮蔽关系)SHALL 对用户可见。

#### Scenario: 查询技能列表

- **WHEN** 用户查询已加载技能
- **THEN** 返回技能列表,含名称、描述与来源路径

#### Scenario: 诊断可见

- **WHEN** 加载过程产生诊断(解析失败或遮蔽)
- **THEN** 诊断对用户可见,遮蔽诊断标注遮蔽关系
