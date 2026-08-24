## MODIFIED Requirements

### Requirement: SKILL.md 格式与发现

技能 SHALL 以"一技能一目录"组织,技能定义文件名为 `SKILL.md`;`SKILL.md` SHALL 由 YAML frontmatter 与 Markdown 正文组成;frontmatter 的 `name` SHALL 缺省取所在目录名;`description` SHALL 缺省取正文第一段;frontmatter 解析失败或解析后缺少可用 name/description 时 SHALL 产生诊断且不加载该技能;技能发现 SHALL 覆盖内建来源、个人级直接目录(`<config_dir>/skills/`)、项目级直接目录(`<cwd>/.codeagent/skills/`)以及已安装用户级和项目级 Package 的 Skill 根目录;Package Skill 根目录 SHALL 递归发现 `skills/**/SKILL.md`;来源目录不存在 SHALL 静默跳过。

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

- **WHEN** 内建、个人级、项目级直接目录以及用户级或项目级 Package 均存在技能
- **THEN** 全部进入加载流程,Package 根目录按递归约定发现,来源目录不存在或为空时静默跳过

### Requirement: 加载与同名遮蔽

技能注册 SHALL 以名称唯一标识;同名技能 SHALL 按 个人级直接目录 > 个人级 Package > 项目级直接目录 > 项目级 Package > 内建 的优先级遮蔽,仅最高优先级者进入注册表;被遮蔽技能 SHALL 产生诊断并标注遮蔽关系(谁遮蔽了谁);注册表 SHALL 按名称排序输出;同一绝对路径 SHALL 只加载一次。

#### Scenario: 个人遮蔽项目

- **WHEN** 个人级直接目录与其它来源存在同名技能
- **THEN** 个人级直接目录技能进入注册表,其它来源的同名技能被遮蔽并产生诊断

#### Scenario: Package 参与同名遮蔽

- **WHEN** 用户级或项目级 Package 与其它来源存在同名技能
- **THEN** 按定义的作用域和来源优先级选择一个技能,被遮蔽来源产生诊断

#### Scenario: 任意级遮蔽内建

- **WHEN** 项目级或个人级直接目录/Package 存在与内建同名的技能
- **THEN** 该技能进入注册表,内建技能被遮蔽并产生诊断

#### Scenario: 注册表排序

- **WHEN** 加载完成
- **THEN** 注册表按技能名称排序(字典序)

#### Scenario: 路径去重

- **WHEN** 同一 `SKILL.md` 被多个来源指向同一绝对路径
- **THEN** 只加载一次,不重复注入

### Requirement: 渐进式披露注入

system 提示词 SHALL 追加技能段:每个已注册的普通技能 SHALL 以一行呈现(名称、描述、来源路径),按名称排序;技能段 SHALL 位于分层上下文段之后;普通技能正文 SHALL 不进入 system 提示词,按需经技能工具获取。已声明为 Bootstrap 的 Skill 可以作为自动会话指令注入，但 SHALL 与普通 Skill 列表区分并避免重复注入。

#### Scenario: 描述行注入

- **WHEN** 注册表存在技能
- **THEN** system 提示词包含技能段,每个普通技能一行(名称/描述/来源路径),按名称排序,位于分层上下文之后

#### Scenario: 正文不预载

- **WHEN** system 提示词注入技能段
- **THEN** 普通技能正文不进入提示词

#### Scenario: Bootstrap 作为例外注入

- **WHEN** 已安装 Package 声明一个会话 Bootstrap Skill
- **THEN** 系统可以注入该 Bootstrap 的正文和 CodeAgent 工具映射,并不得把其它普通 Skill 正文全部预载

#### Scenario: 无技能不产生空段

- **WHEN** 注册表为空
- **THEN** system 提示词不产生技能段

### Requirement: 技能工具

系统 SHALL 提供名为 `skill` 的工具,以技能名为唯一参数;命中已注册技能时 SHALL 返回渲染后的技能正文块(含技能名、来源路径标注与正文,标注技能内相对路径以技能目录为基准);未命中 SHALL 返回明确错误并列出可用技能名。工具 SHALL 能服务于 Package 提供的 Skill，与直接目录和内建 Skill 使用相同的调用语义。

#### Scenario: 命中返回渲染块

- **WHEN** 模型调用 `skill` 工具且技能名已注册
- **THEN** 返回渲染后的技能正文块,包含技能名、来源路径与正文

#### Scenario: Package Skill 命中

- **WHEN** 模型调用 `skill` 工具且命中 Package 提供的技能
- **THEN** 返回与其它来源相同格式的正文块,并保留 Package 来源路径

#### Scenario: 未命中报错并列出

- **WHEN** 模型调用 `skill` 工具且技能名未注册
- **THEN** 返回明确错误,并列出全部可用技能名

#### Scenario: 正文含来源标注

- **WHEN** 技能正文被渲染
- **THEN** 渲染块标注技能来源路径,并说明正文内相对引用以技能目录为基准

### Requirement: CodeAgent Bootstrap 自动触发

当已安装 Package 提供 CodeAgent Bootstrap 时,系统 SHALL 在每个新会话开始时向模型上下文注入一次 Bootstrap 和工具映射;普通用户轮次 SHALL 不重复注入相同 Bootstrap。会话恢复、端口重建或上下文压缩完成后,系统 SHALL 在新上下文中重新注入 Bootstrap;Bootstrap SHALL 指示模型在开始任务前检查可用 Skill,但具体 Skill 调用 SHALL 仅在模型判断任务相关时发生。

#### Scenario: 新会话自动注入

- **WHEN** 用户创建或启动一个新会话且存在可用 Bootstrap
- **THEN** 首轮模型上下文包含 Bootstrap、工具映射和可用 Skill 列表,无需用户手动粘贴指令

#### Scenario: 普通轮次不重复注入

- **WHEN** 同一会话继续处理普通用户消息且上下文未被重建
- **THEN** 系统不重复追加相同 Bootstrap,模型可以继续使用已经加载的 Skill

#### Scenario: 压缩后重新注入

- **WHEN** 会话完成上下文压缩并开始下一轮
- **THEN** 新上下文重新包含 Bootstrap 和工具映射,必要时允许模型重新加载当前任务所需 Skill

#### Scenario: 无 Bootstrap Package 的兼容模式

- **WHEN** Package 只有普通 `SKILL.md` 且未声明 CodeAgent Bootstrap
- **THEN** Skill 仍可被列出、手动加载和经 `skill` 工具调用,但系统不声称其具备自动触发保证

### Requirement: 工具映射与能力降级

Bootstrap 或 Package Adapter SHALL 将 Skill 使用的抽象动作映射到 CodeAgent 当前可用工具;当 subagent、todo、web 等能力不存在时,系统 SHALL 将缺失能力明确告知模型并使用 Skill 已定义的降级语义,不得注册或伪造不存在的工具。

#### Scenario: 已有工具被映射

- **WHEN** Bootstrap 注入 CodeAgent 工具映射
- **THEN** 模型能够将读写、编辑、命令执行、搜索和 Skill 调用映射到实际可用工具名

#### Scenario: 缺失能力可见

- **WHEN** 当前配置未提供某项可选能力
- **THEN** 工具映射声明该能力不可用,模型不发起对应的未知工具调用

### Requirement: 加载结果可见

技能加载结果 SHALL 可查询:已加载技能列表(名称、描述、来源路径;Package Skill 还包括 Package id、版本或 revision)与加载诊断(解析失败、被遮蔽、Package 安装或路径错误及其关系)SHALL 对用户可见。

#### Scenario: 查询技能列表

- **WHEN** 用户查询已加载技能
- **THEN** 返回技能名称、描述和来源路径;Package Skill 同时显示 Package 来源和版本或 revision

#### Scenario: 诊断可见

- **WHEN** 加载过程产生诊断(解析失败、被遮蔽、Package 错误或路径安全错误)
- **THEN** 诊断对用户可见,遮蔽诊断标注遮蔽关系
