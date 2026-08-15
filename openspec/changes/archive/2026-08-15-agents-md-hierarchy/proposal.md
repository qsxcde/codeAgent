## Why

T-43 AGENTS.md 分层指令(FR-16):全局 → 项目 → 子目录分层加载并注入系统提示词,越近优先级越高。现状是**空地基**——项目没有任何 system prompt 基础设施(模型只收 user/assistant/tool 消息,`resources/prompts/` 为空占位)。本 change 照搬 Pi(earendil-works/pi)的 `loadProjectContextFiles` 语义(2026-08-15 源码实查):cwd 向上遍历 + 候选文件名表 + `<project_instructions path="...">` 来源标注,并同步建立基础 system prompt 注入管线。

## What Changes

- **基础系统提示词**:新建 `resources/prompts/system.md`(工具使用说明 / 行为规范等基础指令),经资源打包注入。
- **分层加载器**:`load_agents_files(cwd, config_dir)` 纯函数——全局(`~/.codeagent/AGENTS.md`)优先,随后从 **cwd 向上遍历到文件系统根**(非 git 根,自包含可离线测),每级目录按候选表取第一个存在的文件:`AGENTS.override.md > AGENTS.md > AGENTS.MD > CLAUDE.md > CLAUDE.MD`(兼容 Claude 生态);去重;顺序 = 全局最前、越近 cwd 越靠后(优先级越高)。
- **合并注入**:system prompt = 基础提示词 + `<project_context>` 段(每个文件包 `<project_instructions path="<绝对路径>">` 内容 + 来源标注——FR-8.4 来源透明);组合根解析一次 → `ChatModelPort` 首插 system 消息;`replace_ports` 热切换时重解析(cwd 不变幂等)。
- **加载结果可见可断言**:`/status` 命令扩展显示本次会话加载的 AGENTS.md 文件列表;离线测试构造临时目录树断言顺序/优先级/注入内容(FakeClient 捕获消息)。
- 无 **BREAKING**:消息列表首插 system 属模型端口内部行为,既有事件契约/工具/会话零改动。

## Capabilities

### New Capabilities

无(均为既有能力的扩展)。

### Modified Capabilities

- `core`:新增「系统提示词注入」requirement(模型端口收到的消息首条为 system;分层合并与来源标注契约)。
- `tui`:「斜杠命令体系」requirement 扩展(`/status` 展示 AGENTS.md 加载列表场景)。

## Impact

- `resources/prompts/system.md`(新):基础系统提示词;
- `app/agents.py`(新):`load_agents_files(cwd, config_dir) -> list[tuple[path, content]]` + `build_system_prompt(base, agents_files) -> str` 纯函数(标准库 + 文件系统,不跨层 import);
- `app/container.py`:`create_agent_ports` 解析 AGENTS.md 并组装 system prompt → `ChatModelPort(system_prompt=...)`;`rebuild_ports` 热切换重解析;
- `app/container.py` 的 `ChatModelPort`:`_to_chat_message` 前首插 system 消息(仅一次,消息列表首条);
- `app/tui/commands.py` / `view.py`:`/status` 扩展展示加载列表(经组合根注入的 `agents_sources: list[str]`);
- `tests/`:`test_agents.py`(新,加载器/合并纯函数:临时目录树、候选名、顺序、去重、来源标注)、`test_container.py`(注入断言:FakeClient 捕获首条 system)、`test_view.py`(/status 展示)。

无 **BREAKING** 变更。
