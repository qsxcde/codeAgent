# CodeAgent 修复与优化计划

> 制定日期：2026-08-24  
> 适用版本：v0.3.0 当前代码树  
> 文档性质：问题清单、实施顺序和验收标准，不代表所有任务都已开始实施。  
> 实现核查：2026-08-25 对照当前代码树逐项核查（`pytest` 基线 771 项收集），状态标记：✅ 已完成 / ⚠️ 部分完成 / ❌ 未实施。

## 0. 实现状态总览（2026-08-25 核查）

| 任务 | 状态 | 核查要点 |
| --- | --- | --- |
| P0-1 统一工具参数解析和错误恢复 | ✅ 已完成 | `core/messages.py::parse_tool_arguments` 唯一实现，非法 JSON/非对象不再静默执行，`INVALID_ARGUMENTS` 结构化错误回灌模型 |
| P0-2 完善工具超时、取消和进程清理 | ✅ 已完成 | `core/execution.py::ToolExecutionRuntime`（并发上限/超时/取消/清理确认）+ bash 树级击杀 + MCP 取消（单工具级并发上限未单独实现） |
| P0-3 管理模型客户端和 MCP 资源生命周期 | ✅ 已完成 | `AgentRuntime.close()` 幂等；热切换关闭旧客户端；TUI/会话退出显式关闭；atexit 兜底 |
| P0-4 增加任务级验证闭环 | ❌ 未实施 | 无任务状态机/任务执行器；CHANGELOG Unreleased 仍列 Planned |
| P0-5 修复测试和文档基线漂移 | ⚠️ 部分完成 | CI 已加版本一致性检查；文档仍写 666（实际 771）、`.env.example` 与模板仍双份维护 |
| P1-1 会话存储流式读取和索引 | ✅ 已完成 | 逐行读取 + `store_index.py`（fingerprint 校验/原子写）+ fork 流式复制 |
| P1-2 Skill 和 Package 发现缓存 | ❌ 未实施 | 端口重建/热切换仍重新扫描技能目录 |
| P1-3 增加结构化 Git 工作流 | ❌ 未实施 | 无 git 工具、无 `/git` 命令 |
| P1-4 增加仓库理解能力 | ❌ 未实施 | 仍为 8 个基础工具，无符号级搜索/索引 |
| P1-5 完善 TUI 运行状态和大输出体验 | ⚠️ 大部分完成 | runtime/rendering/output/md_renderer 已拆出；`view.py` 仍 1313 行未拆细 |
| P1-6 增加 Skill Package 信任和更新诊断 | ⚠️ 部分完成 | revision 记录/失败回滚/路径穿越与符号链接防护已有；更新前变更摘要与首次安装确认缺失 |

> 工程质量门禁（第 6 节）：仅 CI 骨架（测试/版本一致性/补丁格式/OpenSpec）已有；pytest-cov、Ruff、mypy、Black、构建后安装冒烟、平台矩阵、夜间真实任务评测均未配置。

## 1. 目标

本计划的目标不是继续堆叠功能，而是把当前“可用的 Coding Agent Beta”提升为更稳定、更高效、更容易维护的单用户代码智能助手。

核心目标闭环：

```text
理解任务 → 制定计划 → 检索仓库 → 修改代码 → 运行验证 → 失败修复 → 检查 diff → 汇报结果
```

本计划优先修复会影响数据安全、资源释放、任务正确性和长期性能的问题；多智能体、Web、记忆和自动化等平台级能力暂不列为近期修复项。

## 2. 优先级定义

| 优先级 | 含义 |
| --- | --- |
| P0 | 影响正确性、安全性、资源泄漏或长时间运行稳定性，建议优先修复 |
| P1 | 影响日常体验、性能和可维护性，完成后再进入稳定发布阶段 |
| P2 | 面向大型仓库、平台化和生态扩展，按真实需求实施 |

## 3. P0：必须优先修复

### ✅ P0-1 统一工具参数解析和错误恢复（已完成）

**现状**

工具参数解析逻辑分别存在于：

- `src/codeagent/core/loop.py`
- `src/codeagent/app/container.py`

当模型返回非法 JSON 或非对象参数时，当前逻辑可能降级为空字典 `{}`。这会让错误被静默隐藏，模型无法准确知道参数为什么失败。

**修复内容**

- 抽取统一的 `parse_tool_arguments()`；
- 保留原始参数、工具名称和 tool call id；
- 解析失败时生成结构化工具错误；
- 将错误回灌模型，允许模型重新生成参数；
- 对缺少必需字段的参数区分“模型参数错误”和“工具执行错误”。

**涉及文件**

- `src/codeagent/core/loop.py`
- `src/codeagent/app/container.py`
- `src/codeagent/core/events.py`
- `tests/core/test_loop.py`

**验收标准**

- 非法 JSON 不会被静默转换为空参数并执行；
- 模型可以看到明确的参数解析错误；
- 合法空对象参数仍保持兼容；
- 单个工具参数错误不会破坏同一轮其它工具调用；
- 增加非法 JSON、数组参数、截断参数和缺字段参数测试。

### ✅ P0-2 完善工具超时、取消和进程清理（已完成；单工具级并发上限未单独实现）

**现状**

`asyncio.wait_for(asyncio.to_thread(...))` 可以取消等待，但不能保证终止已经在线程中运行的同步函数。对于 bash、MCP 或未来的阻塞工具，可能出现后台任务继续运行的情况。

**修复内容**

- 将 bash 超时和 Agent 层超时统一为一套语义；
- bash 超时必须终止进程树，而不仅是父进程；
- MCP 调用超时后主动取消对应 coroutine；
- 为同步工具增加取消状态或明确标记为不可抢占；
- 在事件中记录 timeout、cancelled 和 process cleanup 状态；
- 为并发工具增加全局和单工具并发上限。

**涉及文件**

- `src/codeagent/core/loop.py`
- `src/codeagent/tools/atomic/bash.py`
- `src/codeagent/tools/mcp/client.py`
- `src/codeagent/session/session.py`
- `tests/core/test_loop.py`
- `tests/tools/test_tools.py`
- `tests/mcp/test_mcp.py`

**验收标准**

- 超时后不会遗留可继续修改工作区的后台进程；
- `Esc` 或 `abort()` 后，当前工具调用能在规定时间内停止或明确报告不可抢占；
- 并发工具数量受控；
- 取消、超时和失败都不会把未完成消息写入持久化会话；
- Windows、Linux、macOS 的进程清理行为有独立测试或明确降级说明。

### ✅ P0-3 管理模型客户端和 MCP 资源生命周期（已完成）

**现状**

`OpenAICompatClient` 已提供 `aclose()`，但 `container.py` 的 `/provider`、`/model`、`/login` 热切换会构造新的端口，没有明确关闭旧模型客户端。MCP 主要依靠 `atexit` 收尾。

**修复内容**

- 增加统一的 `Runtime.close()` 或 `Ports.close()`；
- 热切换前关闭旧模型客户端和旧 MCP server；
- TUI 退出时显式关闭所有外部资源；
- `atexit` 作为兜底，不作为唯一释放机制；
- 防止重复关闭和关闭过程中异常泄漏。

**涉及文件**

- `src/codeagent/app/container.py`
- `src/codeagent/ai/transport/openai_compat.py`
- `src/codeagent/tools/mcp/client.py`
- `src/codeagent/tools/mcp/loader.py`
- `src/codeagent/app/tui/main.py`

**验收标准**

- 连续多次切换 provider/model 不会持续增加 AsyncClient、线程或 MCP 子进程；
- TUI 正常退出、异常退出和切换会话时资源都能释放；
- 重复调用 close 不报错；
- 有资源生命周期回归测试。

### ❌ P0-4 增加任务级验证闭环（未实施）

**现状**

当前核心循环主要是“模型 → 工具 → 模型”。它可以执行步骤，但没有强制要求 Agent 在修改后运行测试、分析失败并检查 diff。

**修复内容**

- 增加任务级状态：planning、editing、verifying、repairing、reviewing、completed；
- 修改后自动识别项目测试命令或使用用户指定命令；
- 测试失败后把失败输出和变更范围交给模型；
- 限制自动修复重试次数；
- 最终输出区分已验证、未验证和失败三种结果；
- 提供工作区 diff 摘要。

**涉及文件**

- `src/codeagent/core/loop.py`
- `src/codeagent/session/session.py`
- `src/codeagent/tools/atomic/bash.py`
- 新增任务执行器模块（建议放在 `src/codeagent/app/` 或独立 runtime 层）

**验收标准**

- “修改代码”任务默认包含验证步骤或明确说明未验证原因；
- 测试失败时 Agent 不会直接宣称完成；
- 自动修复次数可配置并有上限；
- 最终结果包含测试命令、退出码和 diff 摘要。

### ⚠️ P0-5 修复测试和文档基线漂移（部分完成）

**现状**

README、CLAUDE 和部分设计文档仍写着 666 项测试，而最近代码已经增加到约 703 项。`.env.example` 与 `config.py` 中的配置模板也存在重复维护。

**修复内容**

- 统一测试数量和日期口径；
- 不在多个文档中手工维护易变的测试数量；
- 将配置模板设为单一来源；
- 修正架构文档中“`.env.example` 不入库”等与仓库状态不一致的描述；
- 在 CI 中增加文档状态检查或生成脚本。

**涉及文件**

- `README.md`
- `CLAUDE.md`
- `docs/design/architecture.md`
- `docs/design/requirements-analysis.md`
- `docs/iteration/v0.3.md`
- `.env.example`
- `src/codeagent/app/config.py`

**验收标准**

- 所有当前状态文档使用同一版本和测试基线；
- `.env.example` 与运行时模板不存在冲突；
- 文档不再描述已删除的运行时架构；
- CI 能阻止版本号或关键状态明显漂移。

## 4. P1：稳定发布前应完成

### ✅ P1-1 会话存储改为流式读取并增加索引（已完成）

**现状**

`JsonFileStore` 目前通过 `read_text().splitlines()` 读取整个 JSONL 文件。长会话或大量历史会造成不必要的内存和 I/O 消耗。

**修复内容**

- `_iter_entries()` 改为逐行读取；
- 会话列表只读取 header 和必要的 meta；
- 为标题、最后更新时间、用量和压缩切点维护轻量索引；
- `switch` 时再加载完整消息；
- `fork` 改为流式复制，不把整个历史一次性读入内存。

**验收标准**

- 读取 100MB 以上会话文件时内存不随文件大小线性增长；
- `/sessions` 不需要加载完整消息正文；
- 压缩和 fork 的恢复语义不变；
- JSONL 损坏行容错行为保持不变。

### ❌ P1-2 Skill 和 Package 发现缓存（未实施）

**现状**

端口重建和 Package 操作会重新扫描 Skill 目录、读取正文和构建 system prompt。

**修复内容**

- 按 `cwd`、配置目录、Package registry revision 和文件 mtime 缓存；
- 仅在 Skill/Package 发生变化时失效；
- `/skills list` 使用已解析的 skill_count；
- 把显式 reload 和自动 mtime 检测分开。

**验收标准**

- 普通 provider/model 切换不会重复扫描未变化的 Skill；
- Skill 内容变化后能被发现；
- `/skills reload` 仍然强制刷新；
- 缓存不会造成个人、项目和内建 Skill 优先级错误。

### ❌ P1-3 增加结构化 Git 工作流（未实施）

**修复内容**

- 增加 status、diff、changed-files、checkpoint、undo 能力；
- 为破坏性 Git 操作复用安全确认环；
- 最终回复显示变更文件、增删行和验证结果；
- 先支持当前仓库，再考虑 worktree 隔离。

**验收标准**

- 用户可以在不手写 shell 命令的情况下查看和回滚 Agent 修改；
- Agent 不会把未相关文件的修改混入结果摘要；
- 破坏性操作仍需要确认。

### ❌ P1-4 增加仓库理解能力（未实施）

**修复内容**

- 增加仓库文件清单和语言识别缓存；
- 增加符号级搜索；
- 优先实现 Python AST，再评估 LSP；
- 搜索结果提供文件、行号、符号和上下文摘要。

**验收标准**

- Agent 可以回答定义位置、引用位置和基本调用关系；
- 重复查询不需要反复扫描整个仓库；
- 索引失败时退回现有 grep/find，不阻塞对话。

### ⚠️ P1-5 完善 TUI 运行状态和大输出体验（大部分完成）

**修复内容**

- 将 `view.py` 拆分为命令、会话、状态和渲染职责；
- 长输出采用增量渲染；
- 增加运行中、取消、超时、重试、恢复的状态反馈；
- 优化终端 resize、滚动和大规模历史恢复；
- 增加键盘快捷键帮助和诊断入口。

**验收标准**

- 长输出不会明显阻塞输入；
- 终端调整大小后布局保持正确；
- 会话切换过程中有明确的加载状态；
- 运行失败后用户可以直接重试或继续会话。

### ⚠️ P1-6 增加 Skill Package 信任和更新诊断（部分完成）

**修复内容**

- 安装和更新时显示来源、revision、Skill 数量；
- 增加 revision/hash 记录；
- 更新前提供变更摘要；
- 对来源变化、包 ID 变化和异常文件给出诊断；
- 对未知 Git 来源提供首次安装确认。

**验收标准**

- 用户可以知道当前 Skill 来自哪里、对应哪个 revision；
- 更新失败可以恢复旧版本；
- 包路径穿越、符号链接和重复 ID 继续被拒绝；
- Skill 内容仍然不会在用户手动加载时直接展示原始 Markdown。

## 5. P2：按需求实施

以下能力不应阻塞当前单用户版本：

- 记忆系统；
- Web/HTTP/SDK 入口；
- subagent 和多智能体；
- 后台任务和自动化；
- IDE 集成；
- 完整插件执行运行时；
- 费用估算和复杂计费系统。

只有出现明确用户场景、性能瓶颈或平台消费者后，才进入设计和实现。

## 6. 工程质量门禁

在 P0/P1 修复过程中同步补齐以下 CI 能力：

1. `pytest-cov` 覆盖率测量和最低阈值；
2. Ruff lint；
3. mypy 或 pyright 类型检查；
4. Black 或统一格式化检查；
5. `uv build` 后安装和 `codeagent --help` 冒烟测试；
6. Windows/Linux/macOS 基础矩阵；
7. 真实任务评测集的夜间运行；
8. 长会话、MCP 启停和工具取消测试。

## 7. 推荐实施顺序

```text
第一批：工具参数错误 + 超时取消 + 资源关闭 + 文档基线
       ↓
第二批：会话流式读取 + Skill 缓存 + Git diff/checkpoint
       ↓
第三批：任务级验证闭环 + 仓库索引 + TUI 大输出优化
       ↓
第四批：静态检查、覆盖率、安装冒烟、多平台和真实任务评测
       ↓
按需求：记忆、Web、subagent、多智能体、自动化、IDE
```

## 8. 暂不建议的优化

当前不建议优先做以下事情：

- 在可靠性闭环完成前增加更多 Skill 数量；
- 在没有真实消费者前实现完整 Web/HTTP 平台；
- 在单用户任务还未稳定前引入多智能体调度；
- 过早引入重量级框架替换现有自研循环；
- 只做 TUI 视觉调整而不修复工具取消和验证闭环；
- 为了拆文件而拆文件，破坏现有端口边界。

## 9. 完成定义

当以下条件全部满足时，可以认为项目达到“稳定单用户代码助手”阶段：

- 常见代码修改任务能自动执行测试；
- 测试失败后不会直接声称完成；
- 工具超时和取消不会遗留后台进程；
- 模型热切换不会泄漏客户端、线程或 MCP 子进程；
- 长会话恢复不会一次性占用过多内存；
- Skill/Package 未变化时不会反复扫描和重建；
- 用户可以查看 diff、验证结果并安全回滚；
- P0/P1 场景有回归测试和真实任务评测；
- CI 覆盖测试、类型、格式、构建安装和至少一个 Windows/Linux 矩阵；
- README、架构文档和迭代记录与代码状态一致。
