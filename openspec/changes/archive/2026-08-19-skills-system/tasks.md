# Skills 技能系统 — 任务分解

> 对应 v0.3 阶段 1(T-49~T-52,扩展技能工具与 `/skills` 命令两项)。设计见 `design.md`,行为契约见 `specs/`。

## 1. 依赖与目录

- [x] 1.1 新增运行时依赖 `pyyaml`(`pyproject.toml`,`uv sync` 后离线测试不受影响)
- [x] 1.2 建立内置技能目录约定 `resources/skills/<name>/SKILL.md`,落地 1~2 个示例技能(如 `commit-message`、`refactor-review`,证明机制,对标 Pi `.pi/skills/add-llm-provider`)

## 2. 格式与加载器(T-49、T-50)

- [x] 2.1 `app/skills.py`:`Skill(name, description, path)` 数据类与 `parse_skill_frontmatter(text)` 纯函数——YAML frontmatter 解析(仅消费 name/description,其余字段忽略),`name` 缺省取目录名、`description` 缺省取正文第一段,解析失败返回失败态
- [x] 2.2 `load_skills(cwd, config_dir)` 纯函数:内建(importlib.resources)/ 个人级(`<config_dir>/skills/`)/ 项目级(`<cwd>/.codeagent/skills/`)三源发现,目录不存在静默跳过
- [x] 2.3 去重与遮蔽:绝对路径去重;同名按 个人 > 项目 > 内建 遮蔽;诊断收集(解析失败/缺少可用名与描述/遮蔽关系),输出按 name 排序
- [x] 2.4 `format_skill_invocation(skill)` 渲染块(对齐 Pi:`<skill name=... location=...>` + 相对路径基准说明 + 正文)与 `build_skills_prompt(skills)` 注入段(每技能一行,位于分层上下文之后,空集不产生空段)

## 3. 注入与装配(T-51)

- [x] 3.1 组合根扩展:`_build_system_prompt` 追加技能段(container.py:30,在 AGENTS.md 合并结果之后);`skills_sources(cfg)` / `skills_registry(cfg)`(镜像 `agents_sources`,container.py:47),装配时调用一次,热切换重读幂等
- [x] 3.2 技能工具 `tools/atomic/skill.py`:name 参数,命中返回渲染块、未命中报错并列出可用技能名;注册表经 `make_tools` 注入(未注入返回不可用提示);工具层不跨层、不读配置;安全分类器零改动(工具不走文件边界分类)

## 4. TUI 命令与可见性(T-52 扩展)

- [x] 4.1 `/skills` 命令注册(`app/tui/commands.py`):`CommandSpec("skills", ..., args=("name",))`
- [x] 4.2 `app/tui/view.py` `_cmd_skills`:无参 → 聊天区列表(名称/描述/来源,按名称排序,无技能明确说明);带参 → 手动加载
- [x] 4.3 手动加载实现:渲染块经 `session.steer()` 注入(`[用户手动加载技能: <name>]` 标注)+ 立即触发一轮回复;未注册名反馈错误并列出可用技能
- [x] 4.4 补全候选:输入框 `/skills ␣` 弹出技能名模糊候选(接入既有 `_picker_candidates` 机制,commands.py picker 同款)
- [x] 4.5 `/status` 扩展:展示已加载技能列表 + 遮蔽诊断(接入 `_cmd_status`,view.py:431,与 agents_sources 并列)

## 5. 测试与收尾(T-52)

- [x] 5.1 `tests/test_skills.py`(镜像 `tests/test_agents.py`):三源临时目录树发现、name/description 缺省语义、解析失败跳过、路径去重、同名遮蔽(个人>项目>内建)+ 遮蔽诊断、排序、注入格式与顺序、空集无空段、渲染块格式
- [x] 5.2 技能工具测试:命中/未命中/未注入注册表;`skill` 不被安全分类器拦截(无越界语义);FakeClient 脚本化多轮断言工具结果进入消息历史
- [x] 5.3 TUI 测试:`/skills` 无参列表、带参加载(steer 注入 + 触发回复)、未注册错误、补全候选、`/status` 技能区(FakeClient / 内存注册表,离线)
- [x] 5.4 全量回归:`uv run pytest` 全绿(基线 512/512,零网络零密钥);`tests/test_decoupling.py` 覆盖新文件(app/skills.py 不 import core/session/ai/tools)
