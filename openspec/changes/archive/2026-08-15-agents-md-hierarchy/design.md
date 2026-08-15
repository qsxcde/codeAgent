## Context

- 现状:项目**无 system prompt 基础设施**(模型只收 user/assistant/tool 消息;`resources/prompts/` 为空占位)。`app/` 层可新增纯函数模块(不跨层 import 即合规);组合根是唯一跨层装配点;`ChatModelPort` 在组合根把 core Message 转 ai 层 ChatMessage——system 首插的天然位置;`replace_ports` 热切换已实现(rebuild_ports 回调)。
- 约束:分层(加载器不 import core/session/ai/tools,纯标准库 + 文件系统);离线可测(临时目录树 + FakeClient 捕获消息);来源标注(FR-8.4 prompt 注入防护:上下文文件按数据注入,标注出处)。
- 语义对齐 Pi(2026-08-15 源码实查 `resource-loader.ts`):`loadProjectContextFiles(cwd, agentDir)`——全局先、cwd 向上到文件系统根、候选名表、去重、近者靠后;拼接为 `<project_context><project_instructions path="...">` 段。动机见 proposal.md;行为契约见 specs(core / tui delta)。

## Goals / Non-Goals

**Goals:**
- 建立基础 system prompt 管线(基础提示词 + 分层 AGENTS.md 合并注入)。
- 加载结果可见可断言(来源列表可查询;/status 展示;离线测试)。

**Non-Goals:**
- 用户级 SYSTEM.md / APPEND_SYSTEM.md 文件(Pi 有,本迭代不做——基础提示词内置即可)。
- project trust 交互(`/trust` 信任决策——Pi 的 SYSTEM.md/扩展 gate;本迭代 AGENTS.md 无条件加载 + 来源标注,MVP 足够)。
- git worktree 嵌套 shadow 处理(Pi 高级特性,注释记录即可)。
- 会话切换时按新 cwd 重载(本项目会话 cwd 固定;热切换仅重解析幂等)。

## Decisions

1. **加载器语义(照搬 Pi)**:`load_agents_files(cwd, config_dir) -> list[tuple[str, str]]`(绝对路径, 内容):
   - 全局: `<config_dir>/AGENTS.md`(候选表优先);
   - 从 `cwd` 向上到文件系统根(`Path.parents`),每级按候选表取第一个存在的文件;
   - 候选表:`AGENTS.override.md > AGENTS.md > AGENTS.MD > CLAUDE.md > CLAUDE.MD`(兼容 Claude 生态,项目自身有 CLAUDE.md);
   - 顺序:全局最前,根 → … → cwd 依次靠后(越近优先级越高,对齐 Pi 的 unshift 行为);按绝对路径去重;
   - 失败容忍:单个文件读失败跳过并记录(不中断加载)。
2. **合并格式(照搬 Pi)**:`build_system_prompt(base, agents_files)`:
   ```
   <基础提示词>
   <project_context>
   Project-specific instructions and guidelines:
   <project_instructions path="/abs/AGENTS.md">内容</project_instructions>
   ...
   </project_context>
   ```
   来源 path 为绝对路径标注(FR-8.4 来源透明)。
3. **注入点(组合根)**:`create_agent_ports` 内解析一次:`agents = load_agents_files(cwd, CONFIG_DIR)` → `system_prompt = build_system_prompt(base_prompt, agents)` → `ChatModelPort(client, system_prompt=...)`;`_to_chat_message` 转换时若消息列表首条非 system 则前置插入(适配层单点);`rebuild_ports` 热切换时重新解析(cwd 不变幂等)。
   - 基础提示词:包内资源 `resources/prompts/system.md`(importlib.resources 读取;模块顶层零副作用,读取延迟到装配)。
4. **加载结果可见**:`create_agent_ports` 同时产出 `agents_sources: list[str]`(来源绝对路径)供 `create_tui_app` 注入 `TuiApp`;`/status` 命令追加「上下文文件」行;无加载显示「(无)」。
5. **测试面**:加载器/合并器为纯函数(临时目录树:全局/项目/多级子目录/候选名冲突/去重/顺序);注入断言(FakeClient 经 ChatModelPort 捕获的消息首条为 system,内容含标注与合并顺序);`/status` 展示(注入 stub 来源列表)。

## Risks / Trade-offs

- [项目 AGENTS.md 不可信源] → 无条件加载但 path 标注来源(FR-8.4);trust 交互留待后续(与 Pi /trust 对齐)。
- [system 首插破坏既有测试] → 既有测试直接构造 AgentPorts(不经组合根)不受影响;组合根级断言只加不改;FakeClient 类测试适配新增断言。
- [长 AGENTS.md 膨胀 context] → 与 Pi 一致全量注入;文件截断/摘要留待 compaction(T-37)统一处理。
- [cwd 向上遍历到根的开销] → 每级仅 stat 5 个候选名,深度有限,装配期一次;可接受。

## Migration Plan

纯增量,无部署;无既有数据迁移(不触 store/事件契约)。实现顺序:基础提示词资源 → 加载器/合并器纯函数 + 测试 → 组合根注入 + 热切换 → /status 展示 → 收尾。

## Open Questions

无(照搬 Pi 语义定案;SYSTEM.md/trust/git worktree 高级特性明确移出)。
