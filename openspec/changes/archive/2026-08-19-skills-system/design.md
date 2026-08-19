# Skills 技能系统 — 设计

> 对应 v0.3 阶段 1(T-49~T-52)与 F-18;对齐参考:Claude Code Skills 官方文档(2026-08-19 实查)、Pi `packages/agent/src/harness/skills.ts`(2026-08-15 实查)。

## 1. 目标与非目标

**目标**:技能"渐进式披露"闭环——发现(描述一行进 system prompt)→ 获取(模型按需经技能工具读正文)→ 用户手动加载(`/skills <name>`)。`resources/skills/` 从占位变为可用生态(DR-7 落地)。

**非目标**:技能创作工具、技能市场、`user-invocable`/`disable-model-invocation` frontmatter 语义(解析忽略但保留字段)、嵌套子目录发现(monorepo)、描述预算截断机制(Claude 有,量小不做)。

## 2. 关键决策(D1~D4,探索期定案)

### D1 来源与同名遮蔽(Claude 式,信任同向)

```
来源(布局统一为 <root>/skills/<name>/SKILL.md,一技能一目录):
  内建    resources/skills/            (包内资源,importlib.resources)
  个人级  <config_dir>/skills/         (= ~/.codeagent/skills/,与 ~/.claude/skills/ 同构)
  项目级  <cwd>/.codeagent/skills/     (用户定案;不兼容 .claude/skills,但文件本身复制即用)

同名优先级:个人 > 项目 > 内建(Claude 官方语义:personal overrides project;任意级覆盖 bundled)
```

- 遮蔽方向与信任方向同向:**不可信的仓库技能永远压不过个人技能**——恶意 repo 只能新增技能名,不能冒名覆盖;被遮蔽者产生诊断并标注遮蔽关系(谁遮蔽谁);
- 去重:绝对路径去重(同文件只加载一次);name 冲突走遮蔽(不是共存——广告集 name 必须唯一,否则模型面对同名技能无法选择);
- 注册表排序:按 name 字典序(注入与展示顺序确定)。

### D2 frontmatter 解析(新增 pyyaml)

- 生态 SKILL.md 是真实 YAML(块标量 `|`、引号、注释、多字段),手写子集解析会静默误读(诊断抓不到"解析错"),故新增运行时依赖 `pyyaml`(轻量、纯 Python 回退;插件阶段 T-53 manifest 复用);
- 只消费 `name` / `description` 两个字段,其余字段忽略不报错;
- 缺省语义(Claude 官方):`name` 缺省 = 目录名;`description` 缺省 = 正文第一段;
- 失败语义:frontmatter 解析失败 → 诊断(`parse_failed`)+ 跳过该技能,不中断加载(镜像 `app/agents.py:67` 读失败跳过风格)。

### D3 技能工具(替代"模型 read 技能文件")

- 新原子工具 `skill`,参数 = 技能名;命中返回渲染块,未命中报错并列出可用名;
- 渲染块对齐 Pi `formatSkillInvocation`:

  ```
  <skill name="<name>" location="<绝对路径>">
  引用相对路径以技能目录为基准。

  <正文>
  </skill>
  ```

- **不走文件工具** → 无工作区越界语义 → 安全分类器(`tools/security.py`)零改动;技能正文是"系统加载结果"而非"工作区外文件",信任语义正确;name 寻址杜绝模型拼路径出错;
- 注册表经组合根注入(`make_tools(cfg, skills=...)` 或容器内构造),工具层不跨层、不读配置。

### D4 注入与可见性

- system prompt 追加技能段(位于 project_context 之后),每技能一行:

  ```
  <available_skills>
  技能按需使用:调用 skill 工具获取正文;未列出即未加载。
  - <name>: <description> (来源: <绝对路径>)
  ...
  </available_skills>
  ```

- 加载结果可见:`skills_sources(cfg)`(镜像 `agents_sources`,container.py:47)注入 TUI;
- `/status` 展示技能列表 + 遮蔽诊断(需求级变更见 tui delta「状态含指令来源」)。

## 3. 用户手动加载(新增,探索期扩 T-52)

用户想要的技能"提示词表达不出"时,手动加载是确定性出口(对应 Claude user-invocable 语义,MVP 所有技能均可手动加载)。

```
/skills              → 聊天区列表(同 /tools 先例,view.py:450)
/skills <name>       → 手动加载:渲染块经 steer() 注入 + 立即触发一轮回复
/skills ␣(补全)      → 技能名模糊候选(现成输入框补全机制,commands.py picker 同款)
```

- **注入语义选"直接注入渲染块"(Claude 式),不选"注入指令让模型调工具"**:确定性生效,不依赖模型行为;与技能工具**共用同一渲染函数** `format_skill_invocation`——模型自主路径(工具结果)与用户手动路径(注入消息)产出同一内容形态;
- 注入消息:`[用户手动加载技能: <name>]\n<渲染块>`,以 **`session.run(block)` 直接触发一轮对话**(会话空闲时即用户消息,不产生空消息;运行中注入场景用 `steer()` 的机制保留给后续会话级注入接口);注入消息随会话落盘,压缩照常处理("技能加载后本会话常驻"语义);
- headless 无此入口(斜杠命令归属 TUI),远期 Web/HTTP(F-27)做会话级注入接口。

## 4. 分层与文件落点

```
app/skills.py           新模块,镜像 app/agents.py:纯函数
                         Skill(name, description, path) 数据类
                         parse_skill_frontmatter(text) -> (frontmatter, body) | 失败
                         load_skills(cwd, config_dir) -> (skills, diagnostics)
                         format_skill_invocation(skill) -> str(渲染块)
                         build_skills_prompt(skills) -> str(注入段)
                         约束:不 import core/session/ai/tools(decoupling 对 app/ 生效);
                         允许 import yaml(第三方依赖,非跨层)
app/container.py        _build_system_prompt 追加技能段(在 build_system_prompt 结果之后)
                         skills_sources(cfg) / skills_registry(cfg)
                         make_tools 注入注册表;create_tui_app 注入技能列表 + 手动加载回调
tools/atomic/skill.py   技能工具(AtomicTool;未注入注册表时返回不可用提示)
app/tui/commands.py     CommandSpec("skills", ..., args=("name",))
app/tui/view.py         _cmd_skills(列表/加载);补全候选接入 _picker_candidates
resources/skills/       1~2 个内置示例技能(证明机制,对标 Pi .pi/skills/add-llm-provider)
pyproject.toml          新增 pyyaml
```

装配时序:`load_skills` 在组合根装配时调用一次(与 AGENTS.md 同点);热切换(`rebuild_ports`,container.py:382)重建端口时重读,同 cwd 幂等。

## 5. 测试策略

- `tests/test_skills.py` 镜像 `tests/test_agents.py`:临时目录树(内建/个人/项目三源)、name 缺省目录名、description 缺省正文第一段、解析失败跳过、路径去重、同名遮蔽(个人>项目>内建)+ 遮蔽诊断、排序、注入格式与顺序、空技能集无空段、渲染块格式;
- 技能工具:FakeClient 脚本化多轮(模型调用 `skill` 工具)、未命中错误、未注入注册表提示、与 read 工具无越界语义(安全分类器不拦截 `skill`);
- TUI:`/skills` 无参列表、带参加载(steer 注入 + 触发回复)、未注册名错误、补全候选(FakeClient / 内存注册表);
- 解耦:新文件纳入 `tests/test_decoupling.py` 扫描(现状即全目录 AST 扫描,新文件自动覆盖)。

## 6. 与后续阶段接缝

- **插件(T-53~T-56)**:manifest 解析复用 pyyaml;插件注册工具走 `AgentPorts.tools` 扩展,与技能工具正交;`/skills` 的"已加载视图"模式可复用到插件列表;
- **MCP(T-57~T-59)**:工具数分组预算计数时计入 `skill` 工具(仅 1 个,开销恒定);
- **记忆(T-60~T-62)**、**成本(T-63~T-66)**:无交互;技能正文经注入消息/工具结果进入会话,usage 照常统计;
- **Web/HTTP(F-27)**:`skills_sources` / 手动加载逻辑可被 HTTP 会话入口复用。
