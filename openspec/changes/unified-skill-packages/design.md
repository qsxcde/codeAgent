## Context

当前 `src/codeagent/app/skills.py` 负责解析 `SKILL.md`、从个人/项目/内建目录发现技能，并由组合根把技能描述注入 system prompt、把正文注册到 `skill` 工具。技能发现目前只扫描一层目录，没有 Package 注册表、版本锁定或 Harness Adapter。`container.py` 在装配端口时生成一次 system prompt 和技能工具；TUI 保存技能列表快照，现有会话生命周期没有独立的 Skill Bootstrap 状态。

本变更需要保留现有直接目录的兼容行为，同时引入可复现的 Git/本地 Package 安装，并让 Superpowers 的通用 Skill 内容能够使用 CodeAgent 的实际工具和会话生命周期。设计遵循变更规格中的优先级、安全边界和自动触发契约。

## Goals / Non-Goals

**Goals:**

- 将 Git/本地 Skill 集合安装为带来源和 revision 的全局或项目 Package。
- 让 Package Skill 与现有内建、个人级和项目级 Skill 共享同一个注册表、遮蔽和 `skill` 工具语义。
- 提供 CodeAgent 原生 Adapter，注入 `using-superpowers` Bootstrap 和实际工具映射。
- 在新会话、恢复、端口重建和上下文压缩后正确管理 Bootstrap，普通轮次不重复注入。
- 使安装、更新、删除、重新加载和诊断可从 CLI/TUI 使用。
- 默认把 Package 视为静态内容，避免安装时执行第三方代码。

**Non-Goals:**

- 不兼容执行 Pi、OpenCode、Claude 或其它 Harness 的插件代码。
- 不在本变更中实现任意第三方 Python/JavaScript 插件沙箱。
- 不改变普通 Skill 的 `SKILL.md` 语法、`skill` 工具参数或现有手动加载语义。
- 不自动把所有 Skill 正文预载进 system prompt。

## Decisions

### 1. 采用“Package Store + Registry + Skill Registry”三层结构

Package Store 只负责保存已安装内容；Package Registry 负责记录来源、作用域、revision 和清单；Skill Registry 负责将直接目录、Package 和内建来源合并成最终可用 Skill 表。这样更新/删除不会直接改写 Skill 解析逻辑，也能保留现有目录安装。

用户级 Package 存放在 `~/.codeagent/packages/<id>`，项目级 Package 存放在 `<cwd>/.codeagent/packages/<id>`。注册记录按作用域分别保存，锁定信息至少包含源地址和解析后的 Git commit。安装先写入临时目录并完成校验，成功后再原子替换 Package 目录和注册记录。

选择该结构而不是把文件复制到 `~/.codeagent/skills`，是为了保留包边界、版本信息、来源透明度和可删除性；直接目录继续作为向后兼容层。

### 2. Package 只提供静态 Skill，CodeAgent Adapter 提供运行时适配

Package 解析器只识别清单和 `skills/**/SKILL.md`。Superpowers 仓库中的 `.pi`、`.opencode`、`.codex-plugin` 等目录不作为 CodeAgent 插件执行。Package 可以通过可选 `codeagent-package.json` 声明 `skills` 根目录、Bootstrap Skill 和工具映射文件。

为了兼容当前 Superpowers 仓库，在没有清单时使用约定回退：若包内存在 `skills/using-superpowers/SKILL.md`，Adapter Resolver 将其识别为候选 Bootstrap，并记录“约定推断”诊断；其它包只有普通 Skill 时仍可正常安装，但不宣称具备自动触发保证。显式清单优先于约定推断。

选择 Adapter 而不是修改上游 Skill 正文，是为了遵循 Superpowers 的跨 Harness 约定：Skill 描述抽象动作，工具名和 Bootstrap 属于宿主适配层。

### 3. 首版使用内置 CodeAgent Adapter，不执行第三方运行时代码

CodeAgent Adapter 由应用自身实现，负责：

- 将 `using-superpowers` 正文和 `codeagent-tools.md` 组合为 Bootstrap；
- 将“读取、编辑、写入、运行命令、搜索、调用 Skill”等抽象动作映射到 `read`、`edit`、`write`、`bash`、`grep`、`find`、`skill`；
- 声明 subagent、todo、web 等未提供能力，并要求模型使用 Skill 中已有的降级路径；
- 输出稳定的 Adapter 版本，便于以后变更映射时诊断兼容性。

不采用执行包内脚本的方案，因为这会让一次 Skill 安装同时获得任意代码执行能力，并把 Windows shell、Node/Python 版本和第三方依赖带入核心运行时。未来如需插件能力，应单独设计信任、权限和隔离协议。

### 4. Bootstrap 作为会话上下文状态管理

Bootstrap 不作为每轮用户消息的前缀，而由 Skill Runtime 按上下文生命周期管理：

1. 新会话或恢复会话时，将 Bootstrap、工具映射和 `available_skills` 加入模型上下文。
2. 普通轮次只保留已建立的上下文，不重复追加 Bootstrap。
3. 端口重建时重新生成 Runtime，但使用会话级去重标识避免同一上下文重复。
4. 上下文压缩完成后，在新上下文首部重新注入 Bootstrap；当前任务所需的普通 Skill 由模型按需重新调用。

Runtime 需要保存 Bootstrap 标识、Adapter 版本和当前会话已加载的 Skill 名称，用于去重、诊断和压缩后的恢复。普通 Skill 正文仍只经 `skill` 工具按需返回。

### 5. 保持现有来源优先级，并扩展 Package 来源

最终优先级固定为：

```text
个人级直接目录
> 个人级 Package
> 项目级直接目录
> 项目级 Package
> 内建
```

同名 Skill 仍只保留最高优先级版本，低优先级版本产生遮蔽诊断。Package 内部递归发现，直接目录保持一层发现，避免改变现有用户目录中非 Skill 子目录的语义。

### 6. 安装操作由 CodeAgent 自己暴露，运行时支持显式 reload

CLI 和 TUI 共享同一 Package Manager，避免出现两套安装状态。安装、更新和删除只修改 Package 状态；`reload` 负责重新构建 Skill Registry、Adapter 和端口。新会话自动读取最新状态，已有会话在显式 reload 或端口重建后更新，避免隐式改变正在运行的上下文。

`/skills` 的无参列表继续显示技能；安装相关子命令显示 Package 状态和诊断，`/status` 显示当前 Adapter、Bootstrap 状态、来源和 revision。

### 7. 错误处理与安全校验前置

安装流程按以下顺序处理：解析来源 → 下载/复制到临时目录 → 校验 Package 根和路径 → 解析清单 → 扫描 Skill → 写入注册/锁定记录 → 刷新运行时。任一步失败都保留旧版本，不产生半安装状态。

Skill frontmatter、Package 清单、路径越界、重复 id、同名遮蔽和 Bootstrap 推断均产生结构化诊断。诊断进入 `/skills`、`/status` 和 CLI 输出，但单个坏 Skill 不阻断其它 Package。

## Risks / Trade-offs

- [Superpowers 的部分工作流依赖 subagent、todo 或 web 工具] → Adapter 明确声明能力并复用 Skill 自带降级语义；后续可逐项增加 CodeAgent 原生工具。
- [约定推断 `using-superpowers` 可能误识别普通包] → 显式 `codeagent-package.json` 优先，约定推断产生可见诊断，并提供禁用 Bootstrap 的包选项。
- [用户级优先于项目级可能与常见项目覆盖直觉不同] → 保持现有规格的兼容优先级，并在列表和遮蔽诊断中显示最终来源。
- [Package 更新后活动会话仍使用旧上下文] → 更新不强制改写活动会话；要求显式 `/skills reload` 或新建会话后生效。
- [只加载 Markdown 无法复现某些 Harness 的完整插件行为] → 明确把 CodeAgent 兼容模式与外部 Harness 插件模式区分，避免静默宣称完全兼容。
- [Git 下载和符号链接带来供应链风险] → 锁定 commit、限制安装根路径、默认不执行代码，并在安装前后保留来源和 revision 诊断。

## Migration Plan

1. 先发布只读兼容层：现有三类 Skill 目录行为保持不变，新增 Package Registry 为空时不改变启动结果。
2. 增加 Package Manager 后，用户通过 `skill install` 安装 Superpowers；安装器识别 `skills/`，不触碰其它 Harness 目录。
3. 启用 CodeAgent Adapter 和 Bootstrap Runtime；没有 Package Bootstrap 的旧 Skill 继续按原有列表、手动加载和 `skill` 工具语义工作。
4. 提供 `list/status/reload` 诊断，验证新旧来源遮蔽、端口重建和上下文压缩后的注入行为。
5. 若需要回滚，删除对应 Package 或禁用 Package 来源即可；直接目录和内建 Skill 不依赖 Package Store，仍可运行。
