# Skills 技能系统

## Why

v0.3 阶段 1(F-18,对齐 Claude Code / OpenAI Codex / Pi 的 Skills 体系)需要把"技能"作为生态扩展的第一块落地:模型在对话中按需使用可复用操作流程,用户也可手动加载。当前 `resources/skills/` 仅为空占位(DR-7),无格式、无加载器、无注入、无入口。技能是生态护城河(G12)最轻的一块,先落地可以验证"渐进式披露"模式,为插件(F-19)、MCP(F-20)铺路。

## What Changes

- **SKILL.md 格式与目录约定**:一技能一目录,`SKILL.md` 含 YAML frontmatter(`name` 缺省=目录名,`description` 缺省=正文第一段,对齐 Claude Code);目录布局 `.codeagent/skills/<name>/SKILL.md`(项目级 `<cwd>/`、个人级 `<config_dir>/`)+ 内建 `resources/skills/`;生态 SKILL.md 文件复制即用
- **新增依赖 pyyaml**:frontmatter 稳健解析(生态文件含块标量/引号,手写子集解析会静默误读);解析失败 → 诊断 + 跳过该技能,不中断加载
- **加载器与注册表**:`load_skills(cwd, config_dir)` 纯函数(镜像 `app/agents.py`),多源发现、绝对路径去重、**同名遮蔽**(个人 > 项目 > 内建,Claude 式优先级,与信任方向同向)、诊断收集(缺字段/解析失败/被遮蔽)、按 name 排序
- **渐进式披露注入**:技能名 + 描述 + 来源路径注入 system prompt(组合根 `_build_system_prompt` 扩展,追加在 project_context 之后);正文不预载
- **技能工具(新工具,替代"模型 read 技能文件")**:`skill` 工具以 name 寻址,返回渲染后的技能正文块(`<skill name=... location=...>...</skill>`,对齐 Pi `formatSkillInvocation`);不经过文件工具,无工作区越界语义,安全分类器零改动
- **`/skills` TUI 命令**:无参列出可用技能(同 `/tools`);`/skills <name>` 用户手动加载——渲染正文经 `steer()` 注入会话并立即触发一轮回复,不依赖模型自主想起(解决"用户想要的技能提示词表达不出");输入框 `/skills ␣` 模糊补全候选
- **可见性**:`/status` 展示已加载技能列表 + 遮蔽诊断;加载结果可查询可断言(`skills_sources` 等)

## Capabilities

### New Capabilities

- `skills`: 技能系统——SKILL.md 格式与发现、加载与注册(来源/遮蔽/诊断)、渐进式披露注入、技能工具、加载结果可见、用户手动加载

### Modified Capabilities

- `core`: 「系统提示词注入」需求扩展——system 内容除基础提示词与分层上下文文件外,追加技能描述段(名称/描述/来源,按 name 排序)
- `tools`: 「工具注册与装配」需求变更——`make_tools` 产出工具由七个扩展为八个,新增 `skill` 工具(名称固定,以技能名为参数)
- `tui`: 「斜杠命令体系」需求变更——新增 `/skills` 命令(无参列表 + 带参手动加载,含技能名补全候选);「状态含指令来源」扩展技能列表与诊断展示

## Impact

- **依赖**:新增 `pyyaml`(运行时依赖;插件阶段 T-53 manifest 解析复用)
- **新增文件**:`app/skills.py`(Skill 数据类 + frontmatter 解析 + 加载器 + 渲染,纯函数,镜像 `app/agents.py`);`tools/atomic/skill.py`(技能工具);`resources/skills/` 内置示例技能(1~2 个)
- **修改文件**:`app/container.py`(`_build_system_prompt` 追加技能段、`skills_sources()`、技能注册表注入工具与 TUI);`app/tui/commands.py`(`/skills` 注册);`app/tui/view.py`(`/skills` handler + 列表/加载 + 补全候选);`app/tui/components.py`(状态/技能展示,如需)
- **测试**:新增 `tests/test_skills.py`(镜像 `tests/test_agents.py`);`tests/test_container.py` / `tests/tui/` 增补;`tests/test_decoupling.py` 覆盖新文件
- **不改动**:core 循环、session 层、安全策略(技能工具不触发文件边界分类)
