## 1. 基础提示词与加载器(纯函数,先行)

- [x] 1.1 `resources/prompts/system.md`:基础系统提示词(工具使用说明 / 行为规范 / 安全约束概览;中文,与项目文档同语言)
- [x] 1.2 `app/agents.py`(新):`AGENTS_CANDIDATES = ("AGENTS.override.md", "AGENTS.md", "AGENTS.MD", "CLAUDE.md", "CLAUDE.MD")`;`load_agents_files(cwd, config_dir) -> list[tuple[str, str]]`——全局先、cwd 向上到根、每级候选表取第一个、绝对路径去重、读失败跳过;`build_system_prompt(base, agents_files) -> str`(Pi 式 `<project_context><project_instructions path=...>` 合并);`read_base_prompt() -> str`(importlib.resources 读 system.md,延迟到调用)
- [x] 1.3 测试(`tests/test_agents.py` 新):临时目录树(全局/项目/两级子目录)、候选名优先级(AGENTS.override > AGENTS > CLAUDE)、去重、顺序(全局最前、近者靠后)、读失败容忍、合并格式含 path 标注

## 2. 组合根注入与热切换

- [x] 2.1 `app/container.py`:`ChatModelPort` 增 `system_prompt: str | None`——`_to_chat_message` 前首条非 system 则前置插入;`create_agent_ports` 装配时解析(load_agents_files + build_system_prompt + read_base_prompt)→ 传入;产出 `agents_sources` 供 TUI
- [x] 2.2 `rebuild_ports`(/provider /model /effort 热切换)重新解析 system prompt(cwd 不变幂等)
- [x] 2.3 测试(`tests/test_container.py` 增量):FakeClient 捕获消息首条为 system、内容含基础提示词 + AGENTS 标注与合并顺序;`create_agent_ports` 返回 sources 列表;热切换后 system 保持

## 3. `/status` 加载结果可见

- [x] 3.1 `create_tui_app` 注入 `agents_sources`;`TuiApp` 增字段;`/status` 命令追加「上下文文件」行(无加载显示 (无))
- [x] 3.2 测试(`tests/tui/test_view.py` 增量):注入来源列表后 /status 展示;无加载时提示

## 4. 收尾

- [x] 4.1 全量离线测试全绿;`openspec validate --change agents-md-hierarchy` 通过
- [x] 4.2 文档同步:v0.2.md T-43 状态与 E 记录
