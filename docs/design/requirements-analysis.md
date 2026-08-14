# codeagent 需求分析文档(完整版)

> 版本: v0.2(完整版)
> 更新日期: 2026-08-13
> 编制口径: 以 `docs/design/` 下四份文档(需求分析报告 v0.1、架构设计、功能表 GAP 分析、编排自研蓝图)为需求来源综合而成,并对照 **2026-08-13 代码库实测状态**校准(校准明细见附录 B)。
> 本版本与 `requirements-analysis.md`(v0.1)的关系:本文为完整合并版,新增架构需求(AR)、数据需求(DR)、接口需求(IR)、验收标准、需求追踪矩阵等章节,并吸收功能表 GAP 分析的修订功能清单(F-01~F-28)与编排自研蓝图的演进路线。v0.1 报告已由本文完全取代并于 2026-08-13 归档删除(原文可从 git 历史提交 5b137b4 恢复)。

---

## 0. 文档概览

| 章节 | 内容 | 主要来源 |
|---|---|---|
| 1 引言 | 目的 / 范围 / 术语 / 参考 | — |
| 2 项目概述与产品定位 | 背景、愿景、设计哲学、定位、目标用户 | 需求分析 §1、§6 |
| 3 市场与竞品分析 | 竞品画像、2026 年中动态、功能矩阵、机会空间 | 需求分析 §2、GAP 分析 §2~3、§6 |
| 4 功能需求(FR) | FR-1~FR-8 分域清单 + 修订功能清单 F-01~F-28 | 需求分析 §3、GAP 分析 §5 |
| 5 架构需求(AR) | 分层依赖、核心契约、解耦判据、自研演进蓝图 | 架构文档 §2/§5/§8/§9、自研蓝图 |
| 6 非功能需求(NFR) | 性能/安全/可用性/可靠性/可维护性/可扩展性/兼容性/可观测性 | 需求分析 §4 |
| 7 数据需求(DR) | 会话状态、事件模型、配置数据、存储规划 | 架构文档、自研蓝图 |
| 8 接口需求(IR) | 端口契约、会话接口、事件接口、CLI、平台入口 | 架构文档 §5~§7 |
| 9 可行性分析 | 技术 / 市场 / 资源三维度 | 需求分析 §5 |
| 10 版本规划与里程碑 | v0.1~v0.3 路线图、节奏建议、现状校准 | GAP 分析 §7、架构文档 §11 |
| 11 风险分析 | 技术/市场/进度/质量风险汇总与对策 | 需求分析 §5、自研蓝图 §5 |
| 12 验收标准 | 分版本验收 + 全局验收基线 | 综合 |
| 附录 A | 需求追踪矩阵(需求 → 出处 → 状态) | 综合 |
| 附录 B | 文档与代码一致性校准说明 | 2026-08-13 实测 |

**优先级约定**(全文档统一):

| 级别 | 含义 | 对应版本 |
|---|---|---|
| P0 | 必须,打通最小可跑闭环 | v0.1 |
| P1 | 上线前刚需,决定"好不好用" | v0.2 |
| P2 | 生态与差异化 | v0.3 |
| P3 | 远期 | 远期 |

**状态图例**:✅ 已落地 / 🔲 待实现 / 📝 规划中 / ⚠️ 已移除或口径已变化(详见说明列与附录 B)。

---

## 1. 引言

### 1.1 编写目的

本文档是 codeagent 项目的**唯一完整需求基线**,目的:

1. 合并 `docs/design/` 下四份文档(需求分析报告、架构设计、功能表 GAP 分析、编排自研蓝图)中的需求信息,消除文档间的不一致(如测试数 219 vs 304、provider 数 3 vs 6、TUI 状态等,见附录 B);
2. 为 v0.2(会话完善)及后续版本提供可追踪、可验收的需求依据;
3. 为设计评审、测试用例编写与迭代排期提供单一事实来源。

### 1.2 范围

- **在范围内**:模型配置层、工具系统、编排引擎、会话层、终端交互(TUI / headless CLI)、可观测性事件、安全权限、扩展与部署,以及对应的非功能指标。
- **不在范围内**(明确不做,详见 §2.6):自研大模型、IDE 插件形态、Agent Teams 级多智能体(远期再看)、语音交互。

### 1.3 读者对象

项目维护者 / 贡献者、二次开发团队、技术决策者、教学使用者。

### 1.4 术语与缩略语

| 术语 | 含义 |
|---|---|
| 端口-适配器(hexagonal) | 横切解耦架构:编排层只认识端口(`AgentPorts`),具体实现由组合根装配 |
| 三层协作 / 双层 loop | Pi-Agent 设计哲学:Factory(装配)/ Session(单对话)/ Runtime(会话生命周期)三层;无状态循环(LangGraph 图)与有状态外壳(`session/`)双层 |
| 会话即状态 | 会话上下文以 thread 维度累积在图中,状态即会话 |
| 组合根 | `container.py`(现 `app/container.py`),全项目唯一允许跨层 import 的地方 |
| ModelRuntime | 自研模型客户端层(自研蓝图第一步):`protocol/` + `transport/` + `providers/`,替代 langchain 模型客户端 |
| ReAct | 推理-行动循环:模型 ↔ 工具交替直至模型不再请求工具 |
| provider | 模型供应商(deepseek / openai / qwen / glm / kimi / minimax / fake) |
| effort | 运行时思考强度(`model:effort` 内联语法) |

### 1.5 参考文档

| 文档 | 说明 |
|---|---|
| `requirements-analysis.md`(v0.1,已归档) | 需求分析报告 v0.1(2026-08-10),内容已并入本文档;原文可从 git 历史(提交 5b137b4)恢复 |
| [architecture.md](architecture.md) | 架构设计文档 v0.1(2026-08-11) |
| [feature-gap-analysis.md](feature-gap-analysis.md) | 功能表全面分析 / 竞品对标 GAP(2026-08-10) |
| [self-built-orchestration-blueprint.md](self-built-orchestration-blueprint.md) | 编排引擎自研蓝图(第二步,暂缓)(2026-08-10) |
| README.md / pyproject.toml / src/codeagent/ | 项目现状(2026-08-13 实测校准) |

---

## 2. 项目概述与产品定位

### 2.1 项目背景

`codeagent` 是基于 **LangGraph** 的编程 Agent,采用 Pi-Agent 设计哲学(三层协作 / 双层 loop / 事件驱动 / 会话即状态)+ 端口-适配器(hexagonal)横切解耦。v0.1 已打通"可对话 + 可调用工具 + 事件流可订阅"的最小闭环。

### 2.2 产品愿景

目标不是"复刻一个 Claude Code",而是构建一个**可演进、可替换、可感知、可测试**的编程 Agent **工程底座**:

| 特性 | 含义 | 落地形态 |
|---|---|---|
| 可演进 | 从单工具调用型 Agent 平滑演进到多 Agent / 多会话 / 平台部署 | 分层结构 + 演进路线(§10) |
| 可替换 | 更换模型供应商、工具集、存储,均不触碰 Agent 编排代码 | 端口-适配器 + 组合根唯一交汇 |
| 可感知 | 会话运行过程以事件流对外暴露,CLI / Web / 测试都能订阅 | `EventBus` + `AgentEvent` 全生命周期 |
| 可测试 | 核心编排层零网络、零密钥即可运行 | `FakeClient` 离线假模型注入 |

### 2.3 设计哲学:两条正交轴(架构需求 AR 的总纲)

| 轴 | 分的是什么 | 来源 |
|---|---|---|
| **横切轴:依赖方向** | config / 工具 / 编排 / 调用之间谁认识谁 | 端口-适配器(hexagonal) |
| **纵切轴:生命周期** | 装配(Factory)/ 单个对话(Session)/ 会话生命周期(Runtime) | Pi-Agent 三层协作 |

Loop 双层(无状态循环 / 有状态 Agent)是另一条正交结构:LangGraph 提供无状态循环(编译后的图),有状态外壳由 `session/` 层补齐。

### 2.4 差异化定位

**一句话定位**:

> codeagent —— 一个可替换、可测试、可嵌入的编程 Agent 工程底座。

不正面竞争"谁的 Agent 更强",而是竞争"**谁的 Agent 更工程化、更可嵌入、更不锁死**"。战场:国内 DeepSeek 生态、企业私有化/自研底座、教育/教学/二次开发。

### 2.5 目标用户与典型场景

| 用户 | 典型场景 |
|---|---|
| 国内开发者 | 以 DeepSeek 等国产模型驱动终端编程助手,无网络/支付门槛 |
| 企业自研团队 | 以事件流架构将 Agent 嵌入 CI / 内部平台;私有化部署、供应商中立选型 |
| 教育与开源社区 | 学习 Agent 编排、离线跑通全部测试、二次开发定制工具/provider |
| 技术决策者 | 评估"可测试、可替换、可审计"的工程化 Agent 底座 |

### 2.6 不做的事(聚焦边界)

1. 不拼模型能力(无自研模型,核心能力受第三方 API 制约);
2. 初期不做 IDE 插件 / 全形态覆盖;
3. 不追求 Agent Teams 级多智能体(远期再看);
4. 不做语音听写。

---

## 3. 市场与竞品分析

### 3.1 竞品画像总览

| 维度 | **codeagent** | **CodeBuddy CLI** | **Claude Code** | **Codex CLI / App** |
|---|---|---|---|---|
| 出品方 | 个人/开源项目 | 腾讯云 | Anthropic | OpenAI |
| 主要形态 | 终端(headless CLI 当前形态) | 插件 / IDE / CLI | 终端 CLI | 终端 CLI(开源)+ macOS App |
| 底层模型 | DeepSeek / OpenAI / Qwen / GLM / Kimi / MiniMax / fake | 腾讯混元系 + 多云多栈 | Claude 系列 | GPT-5.2-Codex、o3/o4-mini |
| 模型开放性 | **多供应商中立,可自接** | 以云厂商模型为主 | 绑定 Claude | 绑定 OpenAI |
| 技术栈 | Python + LangGraph(+ 自研模型客户端) | Node.js | TypeScript(闭源) | TypeScript(开源) |
| 核心能力 | 事件驱动 Agent 编排 + 供应商中立 | AST / RAG / Agent 全流程 | Sub-agents + Skills + Agent Teams | 多智能体并行 + 工作树隔离 + Skills + Automations |
| 开源程度 | 开源 | 客户端开源 | 闭源(生态开放) | CLI 完全开源 |
| 国内使用 | **原生适配** | 国内云原生 | 需中转/网络/支付门槛 | 需中转/网络 |
| 目标用户 | 开发者 / 团队自研 / 教学 | 企业级研发团队 | 全球开发者,偏高端 | 全球开发者,偏高端 |

### 3.2 竞品最新动态(2026-06 ~ 07 检索,GAP 分析 §2)

**Claude Code(v2.1.x)**:客户端瘦身 7MB、降低冷启动;`.claude/skills` 本地插件免市集加载;权限向 Manual 手动挡收紧、`classifyAllShell` 安全分类器;Sub-agents 多轮迭代。社区痛点:Opus 4.8 推理退化指控、静默升级导致 $506 意外扣费(模型信任赤字)。

**OpenAI Codex**:CLI 完全开源,四种形态;六大进阶能力(Skills / Memories / AGENTS.md / MCP / Automations / SDK);AGENTS.md 全局→项目→子目录多层覆盖;macOS App 多智能体并行 + 工作树隔离;`/undo` 回滚(297 👍)为社区高优需求;服务器端配额计费 bug(信任赤字)。

**CodeBuddy Code 2.0(腾讯云)**:1.0 于 2025-09 发布,2026 升级 2.0(99.9% 代码自生成);腾讯内部超 1.2 万名工程师;ACP 协议集成;强在国内生态与企业级落地。

**其他竞品**:Gemini CLI 三线日更;OpenCode 核心突破=**会话快照 + 回滚控制**;Qwen Code 中文支持、低成本;Copilot CLI 企业托管 + 认证管控 + OpenTelemetry;Pi 引入 `pi-orchestrator` 守护进程(IPC 多实例);DeepSeek TUI 更名 CodeWhale、品牌混乱(对 codeagent 反而是入局机会)。

### 3.3 行业共性趋势(agents-radar 2026-06-26)

1. **模型信任赤字**:可靠性、成本可预测性取代功能迭代速度,成为社区最关心的问题;
2. **多智能体编排**成为新方向(Pi orchestrator / Claude mesh / Codex Apps);
3. **MCP 生态规模化阵痛**:128~212 个工具时出现 400 错误/超时,需工具优先级分组与预算;
4. **Windows 仍是"二等公民"**:几乎所有工具都有 Windows 专属 bug;
5. **会话持久性与恢复**:`/undo` 命令需求(Codex 297 👍)、恢复会话认证失效、历史丢失;
6. **AGENTS.md 标准化**:行业正朝"智能体配置文件"标准化演进;
7. **成本透明度/配额控制**成为三款工具共同需求;
8. **无障碍/本地化**:Claude Code 日语本地化、Codex VoiceOver。

### 3.4 竞品功能矩阵 vs codeagent

> ✅=已有/已设计;🔲=待实现(规划);⬜=未规划/差距

| 功能域 | Claude Code | Codex | CodeBuddy | OpenCode | codeagent 现状 | 差距 |
|---|---|---|---|---|---|---|
| 多供应商中立 | ⬜ | ⬜ | ⬜ | ✅ | ✅ deepseek/openai/qwen/glm/kimi/minimax/fake | ✅ 领先 |
| 离线可测(fake 模型) | ⬜ | ⬜ | ⬜ | ⬜ | ✅ | ✅ 领先 |
| 终端 TUI | ✅ | ✅ | ✅ | ✅ | ⚠️ 曾落地,当前代码树为 headless(附录 B) | P1 差距 |
| 工具集 read/write/edit/bash | ✅ | ✅ | ✅ | ✅ | ✅ 已落地 | 齐平 |
| ReAct 编排(LangGraph) | ✅ | ✅ | ✅ | ✅ | ✅ 已落地(全异步,工具并行+错误归属精确) | 齐平 |
| 事件流/可感知 | 部分 | 部分 | 部分 | 部分 | ✅ AgentEvent 10 类全生命周期 | 领先 |
| 会话持久化/恢复 | ✅ | ✅ | ✅ | ✅ | 🔲 v0.2 | **P1 差距** |
| 会话回滚 /undo | 部分 | 需求中(297👍) | 部分 | ✅ 快照回滚 | 🔲 v0.2 规划 | **P1 差距** |
| 分层指令 AGENTS.md | ✅ | ✅ | 部分 | 提案被关 | 🔲 v0.2 规划 | **P1 差距** |
| 记忆系统 Memories | ✅ | ✅ | 部分 | ⬜ | 📝 P2 | P2 差距 |
| MCP 工具扩展 | ✅ | ✅ | ✅ | ✅ | 📝 P2(注意工具数分组预算) | **P2 差距** |
| Skills 技能系统 | ✅ 成熟 | ✅ | ✅ | 部分 | 🔲 resources 目录已建 | P2/P3 |
| 插件系统 | ✅ 本地免市集 | ✅ | ✅ | 部分 | 🔲 extensions 占位 | P2/P3 |
| 安全权限模型 | ✅ 手动挡/分类器 | 审批机制 | ✅ | 部分 | 🔲 危险命令黑名单已兜底,确认环待 v0.2 | **P1 差距** |
| 成本透明/配额控制 | ⬜ 出问题 | ⬜ 出问题 | 部分 | ⬜ | 📝 P2(竞品痛点=机会) | P2 机会 |
| 多智能体/Teams | ✅ | ✅ | 部分 | ⬜ | 📝 P3 | P3 |
| 定时任务 Automations | 部分 | ✅ | 部分 | ⬜ | 📝 P3 | P3 |
| SDK 编程接入 | ✅ | ✅ | ✅ | 部分 | ✅ 事件流天然适配 | P2/P3 |
| 平台部署 langgraph.json | ✅ | ✅ | ✅ | 部分 | 📝 架构已设计 | P2/P3 |

### 3.5 codeagent 的机会空间与劣势

**机会空间**(市场切点):

| 市场切点 | 依据 | 强度 |
|---|---|---|
| 国内 DeepSeek 生态 | 内置 deepseek provider,0 网络障碍;CodeWhale 品牌混乱留下窗口 | ★★★★ |
| 企业私有化/自研底座 | 供应商中立 + 事件流架构,可嵌入 CI/内部平台 | ★★★★ |
| 教育与开源社区 | 架构清晰、离线可测,天然适合教学/二次开发 | ★★★ |
| 工程化 Agent 底座 | 可测试/可替换/可感知三特性直接回应企业选型痛点 | ★★★★ |

**劣势与风险**:

- 无自研模型,核心能力受第三方 API 制约;
- 功能完整度仍落后头部,初期体验无法对标;
- 无品牌与社区积累,冷启动困难;
- 若头部产品放开多供应商支持(Codex 已开源 CLI),差异化空间被压缩。

**结论**:正面竞争不可行;**差异化定位可行**——做"可替换、可测试、可嵌入"的编程 Agent 底座。

---

## 4. 功能需求(FR)

### 4.1 需求组织说明

- FR-1~FR-7 沿用需求分析报告 v0.1 的编号体系;FR-8(安全与权限)由 GAP 分析 F-14 独立成章(升格为上线前刚需);
- 每条需求给出:**优先级 / 状态 / 验收要点**;
- 状态以 2026-08-13 代码实测为准,与 v0.1 报告不一致处见附录 B。

### 4.2 FR-1 终端交互与对话

| ID | 需求 | 说明 | 优先级 | 状态 |
|---|---|---|---|---|
| FR-1.1 | 自然语言对话 | 普通文本发送给 Agent,回复渲染到聊天区 | P0 | ✅ MVP TUI 已恢复(restore-tui,`--tui`);headless 保留(FR-1.9) |
| FR-1.2 | 流式回复渲染 | `respond_stream` 增量渲染(text/tool_call/tool_result) | P0 | ✅ MVP 流式渲染(text_delta/thinking/tool_call/tool_result → 组件树)+ 样式区分(tui-styling:思维灰不折叠 / 工具默认折叠点击展开) |
| FR-1.3 | 斜杠命令体系 | `/help /clear /quit /status /provider /model /effort /tools /session` | P0 | 🔲 下一迭代(restore-tui 拆出;Editor 留扩展缝) |
| FR-1.4 | 模糊命令补全 | 输入 `/` 弹出建议,↑/↓ 选择,回车填入输入框 | P0 | 🔲 下一迭代 |
| FR-1.5 | 命令选择器 | provider / model / effort 三项,支持筛选与直接输入 | P0 | 🔲 下一迭代 |
| FR-1.6 | `//` 转义 | 发送以 `/` 开头的字面量内容 | P0 | 🔲 下一迭代 |
| FR-1.7 | 打断/取消 | 运行中可中断 agent 运行 | P0 | ✅ 会话层 `AgentSession.abort` + MVP TUI `Esc` 打断入口(运行中 Esc → abort) |
| FR-1.8 | 键盘导航 | `Ctrl+L` 聚焦、`Ctrl+Q` 退出、Tab 补全、Esc 收起浮层 | P0 | ⚠️ 部分:Esc 打断/退出已落地;Ctrl+L/Tab/浮层导航下一迭代 |
| FR-1.9 | Headless 模式 | 一次性 `--prompt` 与 stdin 逐行两种输入 | P0 | ✅ 当前唯一保留形态(`app/main.py`) |
| FR-1.10 | 多轮上下文 | 同一会话内多轮对话携带上下文(会话维度 thread 累积) | P0 | ✅ |

> **FR-1 状态说明**:TUI 在 2026-08 曾完成重设计(内容块树 + TranscriptView + 增量渲染,提交 d21ba41~e4deca2),但于 2026-08-13 在提交 876d106 中随模型层自研重构整体移除(`src/codeagent/tui/` 与 `tests/tui/` 全部删除,pyproject 同步移除 textual)。当前入口为 headless(`app/main.py`,`--prompt` / stdin 双路径),事件聚合语义为:text_delta 增量累积 → tool_call 前文本清零 → agent_message 兜底去重。**TUI 恢复于 2026-08-13 由 restore-tui 落地 MVP**(`app/tui/`:纯组件 render + TuiBackend 端口 + textual 后端,`--tui` 进入):对话/流式渲染/Esc 打断/状态栏/alt 屏/退出完整文档;斜杠命令体系、模糊补全、选择器、`//` 转义、Tab 补全、Ctrl+L 导航拆下一迭代(FR-1.3~1.6/1.8 部分)。

### 4.3 FR-2 模型配置与管理

| ID | 需求 | 说明 | 优先级 | 状态 |
|---|---|---|---|---|
| FR-2.1 | 多 provider 支持 | deepseek / openai / qwen / glm / kimi / minimax / fake,每 provider 一个自包含文件(配置+工厂) | P0 | ✅(7 个,`ai/providers/`) |
| FR-2.2 | 统一模型创建入口 | `factory.create_llm()` 按 provider+model 解析并构造未绑定工具的模型 | P0 | ✅ |
| FR-2.3 | 内置模型目录 | 模型元数据(id/别名/reasoning/maxTokens)静态登记(`catalog/builtin.py`) | P0 | ✅ |
| FR-2.4 | 用户模型覆盖 | `~/.codeagent/models.json` 按 id **upsert 合并**(同 id 覆盖、新 id 追加、内置保留) | P1 | ✅ |
| FR-2.5 | 运行时思考强度切换 | `model:effort` 内联 / `/effort` 命令,优先级:内联>参数>配置默认 | P0 | ✅(`model_pattern.py` 单一解析实现) |
| FR-2.6 | 缺失密钥可操作报错 | 缺 API Key 报"请配置 DEEPSEEK_API_KEY"而非 SDK 原始错误 | P0 | ✅ |
| FR-2.7 | 模型列表探测 | 调用供应商 `/models` 自动发现模型(当前目录静态兜底) | P2 | 📝 |
| FR-2.8 | 模型客户端自研(ModelRuntime) | 框架无关协议层 + OpenAI 兼容传输层,替代 langchain 模型客户端(自研蓝图第一步) | P0 | ✅ 已落地:`protocol/`(ChatClient 协议/SSE 解析)+ `transport/openai_compat.py`(httpx);`bridge/langchain.py` 仅作编排桥接 |
| FR-2.9 | 默认注册表缓存 | `create_llm` 不每次重建/重读 models.json(性能优化 M11) | P0 | ✅ |

### 4.4 FR-3 工具系统

| ID | 需求 | 说明 | 优先级 | 状态 |
|---|---|---|---|---|
| FR-3.1 | 原子工具集 | `read / write / edit / bash` 四个原子工具 | P0 | ✅ 已落地 |
| FR-3.2 | 工具注册表 | 工具登记、元数据、按需枚举(`make_tools`) | P0 | ✅ 已落地 |
| FR-3.3 | 工具绑定 | 组合根 `llm.bind_tools(tools)`,core 零感知具体工具 | P0 | ✅(`app/container.py` 唯一交汇行) |
| FR-3.4 | 拦截管道 | ~~pipeline 包住 ToolNode,支持拦截/审计~~ | P1 | ❌ 已删除(死代码,危险命令由 bash 黑名单承担) |
| FR-3.5 | 工具执行确认 | bash / write 等敏感操作默认需确认 | P1 | 🔲 v0.2(见 FR-8) |
| FR-3.6 | 工具结果事件化 | 工具调用/结果以事件流对外暴露 | P0 | ✅(tool_call / tool_result 事件) |
| FR-3.7 | 上下文检索工具 | grep / search / 文件树等辅助工具 | P1 | ✅ 已落地(atomic-tools-refactor:grep / find / ls 纯 Python 实现,2026-08-13) |
| FR-3.8 | bash Windows 适配 | `_resolve_bash()` 探测链(Git for Windows / WSL),无 bash 时给可操作错误 | P0 | ✅(⚠️ 2026-08-13 实测:Windows Git Bash 下 4 项 bash 测试失败,疑为路径显示/`PIPESTATUS` 环境差异,见附录 B) |

### 4.5 FR-4 编排引擎

| ID | 需求 | 说明 | 优先级 | 状态 |
|---|---|---|---|---|
| FR-4.1 | AgentPorts 端口 | 编排认识的唯一外部世界:`bound_model / tool_executor / checkpointer` | P0 | ✅ |
| FR-4.2 | AgentState | 对话状态结构(基于 MessagesState) | P0 | ✅ |
| FR-4.3 | ReAct 循环 | agent →(有 tool_calls)→ tools → agent;否则 END;全异步 | P0 | ✅ |
| FR-4.4 | agent / tools 节点 | 异步节点 + 工具异常兜底 | P0 | ✅ |
| FR-4.5 | 循环条件 | `should_continue` 只看 state 形状,不 import 具体工具 | P0 | ✅ |
| FR-4.6 | Checkpointer | 图级持久化(thread_id);默认内存 InMemorySaver,会话维度累积 | P0 | ✅ |
| FR-4.7 | 多智能体协作 | 多 Agent 编排(远期) | P2 | 📝 |
| FR-4.8 | 编排自研(第二步) | ReAct 主循环 / 消息归约 / 持久化 / 工具调度 / 控制流自研,替代 langgraph 编排层 | P3 | 📝 蓝图已存档,**暂缓**,启动前须回答三个未决问题(§5.5) |

### 4.6 FR-5 会话层

| ID | 需求 | 说明 | 优先级 | 状态 |
|---|---|---|---|---|
| FR-5.1 | AgentSession | 全异步 `run` + `subscribe` + `run_sync`;会话维度 thread 累积 | P0 | ✅ |
| FR-5.2 | 事件总线 | `EventBus.subscribe / emit`,CLI / Web / 测试统一订阅 | P0 | ✅ |
| FR-5.3 | 事件流翻译 | `graph.astream(thread_id, [messages, updates])` → `AgentEvent` 序列 | P0 | ✅ |
| FR-5.4 | 会话持久化 | SessionStore 线性存储,重启可恢复 | P1 | 🔲 v0.2 |
| FR-5.5 | SessionManager | create / fork / switch / dispose | P1 | 🔲 v0.2 |
| FR-5.6 | 上下文压缩 | 手动 + 阈值触发 compaction | P1 | 🔲 v0.2 |
| FR-5.7 | 会话树/分叉 | 分支会话、对比探索 | P2 | 📝 |
| FR-5.8 | 运行中断 abort | `abort()` 中断当前运行并广播 `run_cancelled` | P0 | ✅ 已落地 |
| FR-5.9 | 图形热替换 | `replace_graph()` 切换 provider/model/effort 时重建图并保留 thread 上下文 | P0 | ✅ 已落地 |
| FR-5.10 | steer / followup | 运行中注入消息 / 结束后追问一轮 | P1 | 🔲 v0.2(自研蓝图"收益 2"指出:自研编排后此两项从规划变几行代码) |

### 4.7 FR-6 可观测性与事件

| ID | 需求 | 说明 | 优先级 | 状态 |
|---|---|---|---|---|
| FR-6.1 | AgentEvent 类型 | 10 类:`session_started / text_delta / thinking_delta / agent_message / tool_call / tool_result / turn_end / error / run_cancelled / usage` | P0 | ✅(比 v0.1 报告多出 thinking_delta / run_cancelled / usage) |
| FR-6.2 | 事件订阅接口 | 对外暴露可编程订阅(`EventBus.subscribe`,订阅方异常隔离) | P0 | ✅ |
| FR-6.3 | 状态栏实时反馈 | TUI 运行态/错误态/取消态可视化 | P0 | ✅(随 TUI 恢复:E9~E11 状态栏 + 状态色,运行/错误/取消可见) |
| FR-6.4 | token 用量事件 | `usage` 事件透传模型 usage_metadata | P0 | ✅ 已落地 |
| FR-6.5 | 思考过程事件 | `thinking_delta` 透传推理模型 reasoning_content | P0 | ✅ 已落地(自研蓝图"收益 1"的 thinking 缺口已闭合) |

### 4.8 FR-7 扩展与部署

| ID | 需求 | 说明 | 优先级 | 状态 |
|---|---|---|---|---|
| FR-7.1 | Skills 按需加载 | `resources/skills/` 技能文件渐进式披露 | P2 | 🔲 目录已建 |
| FR-7.2 | 插件系统 | `extensions/` 两阶段(注册→绑定)扩展机制 | P2 | 🔲 占位 |
| FR-7.3 | 平台部署 | `langgraph.json` 与 CLI 共享同一份图定义 | P2 | 📝(自研蓝图"代价 4":若自研编排落地,平台入口需重设计,启动前须决策) |
| FR-7.4 | Web / API 暴露 | 事件流天然适配 Web 订阅 | P2 | 📝 |

### 4.9 FR-8 安全与权限(上线前刚需,GAP F-14)

| ID | 需求 | 说明 | 优先级 | 状态 |
|---|---|---|---|---|
| FR-8.1 | 危险命令黑名单 | `rm -rf /` 等价写法拦截,拒绝带审计信息(命中原因) | P0 | ✅ 已落地 |
| FR-8.2 | bash 确认环 | 敏感/未确认命令默认拒绝或需用户确认 | P1 | 🔲 v0.2(对标 Claude Code 手动挡) |
| FR-8.3 | 文件访问边界 | read/write/edit 默认限定工作区,跨工作区访问需显式确认 | P1 | 🔲 v0.2 |
| FR-8.4 | Prompt 注入防护 | 工具返回内容按"数据"处理,不拼进 system prompt 当指令执行 | P0 | ✅ 设计约束,持续保持 |

### 4.10 修订版功能实现清单(合并 GAP 分析 §5,F-01~F-28)

> 与 FR 编号的映射见附录 A;`[竞品对标]` 表示由竞品最新动态催生的新增项。

**P0 — v0.1:最小可跑闭环**

| ID | 功能 | 状态(2026-08-13) |
|---|---|---|
| F-01 | `tools/` 原子工具 read/write/edit/bash + 注册表 | ✅ 已落地(08-09) |
| F-02 | ~~`tools/pipeline.py` 拦截管道~~ | ❌ 已删除(危险命令由 bash 黑名单承担) |
| F-03 | `core/ports.py` AgentPorts | ✅ 已落地 |
| F-04 | `core/state.py` AgentState + `core/loop.py` build_graph | ✅ 已落地(全异步 ReAct) |
| F-05 | `core/nodes/` agent & tools 节点 | ✅ 已落地(并行执行 + 单失败错误归属) |
| F-06 | `core/events.py` AgentEvent 类型 | ✅ 已落地(10 类事件) |
| F-07 | `session/bus.py` 事件总线 | ✅ 已落地 |
| F-08 | `session/session.py` AgentSession | ✅ 已落地(含 abort / replace_graph) |
| F-09 | `container.py` 接线(现 `app/container.py`) | ✅ 已落地 |
| F-10 | 流式回复渲染 | ⚠️ 事件→StreamChunk 渲染层随 TUI 移除;headless 事件聚合保留 |

**P1 — v0.2:好用的刚需(1–2 周)**

| ID | 功能 | 说明 | 依据 |
|---|---|---|---|
| F-11 | `session/store.py` 会话持久化 | 线性存储,重启恢复 | 竞品标配 |
| F-12 | `session/manager.py` SessionManager | create/switch/dispose | 竞品标配 |
| F-13 | `session/compaction.py` 上下文压缩 | 手动 + 阈值 | 长会话刚需 |
| F-14 | 安全权限模型 `[竞品对标]` | bash 确认环 + 文件边界白名单(黑名单已兜底) | Claude Code 手动挡 |
| F-15 | 会话回滚 `/undo` `[竞品对标]` | 回滚到指定消息及文件变更 | Codex 297👍 / OpenCode 快照 |
| F-16 | AGENTS.md 分层指令 `[竞品对标]` | 全局→项目→子目录层级加载 | 行业标准化 |
| F-17 | 会话列表与切换 | SessionManager 配套 UI/CLI 命令 | 竞品标配 |
| F-17b | TUI 形态恢复(FR-1.11) | 交互式终端形态重建,复用 AgentSession 事件接口 | 本项目演进 |

**P2 — v0.3:生态与差异化(2–3 周)**

| ID | 功能 | 说明 | 依据 |
|---|---|---|---|
| F-18 | `resources/skills/` 技能系统 | 渐进式披露 | Claude/Codex Skills |
| F-19 | `extensions/` 插件系统 | 两阶段注册→绑定 | Claude 本地插件 |
| F-20 | MCP 客户端适配 `[竞品对标]` | 外部工具接入(注意工具数分组预算) | 竞品标配 |
| F-21 | 轻量记忆 `~/.codeagent/memory` `[竞品对标]` | 跨会话偏好/事实 | Codex Memories |
| F-22 | 成本透明 `[竞品对标]` | token 用量 + 费用估算入状态栏/事件流 | 信任赤字诉求 |
| F-23 | 分支会话 fork | 会话树、对比探索 | Pi fork 语义 |
| F-24 | 平台部署 `langgraph.json` | 与 CLI 共享同一份图 | 架构已设计 |

**P3 — 远期**

| ID | 功能 | 说明 |
|---|---|---|
| F-25 | 多智能体协作 | Teams 级;事件流天然适配 |
| F-26 | Automations 定时任务 | 后台触发 agent |
| F-27 | Web / HTTP API | 事件流订阅暴露 |
| F-28 | Windows 验证 | bash 已通过 Git for Windows 探测链适配;⚠️ 4 项 bash 测试环境差异待回归确认 |

### 4.11 GAP 差距分析结论(合并 GAP 分析 §4)

| 梯队 | 差距项 | 状态 |
|---|---|---|
| P0(能不能用) | G1 工具系统 / G2 编排引擎 / G3 会话层 / G4 容器接线 | ✅ G1~G4 已全部解决,v0.1 闭环打通 |
| P1(好不好用) | G5 会话持久化 / G6 回滚 undo / G7 安全权限模型 / G8 AGENTS.md / G9 上下文压缩 | 🔲 全部进入 v0.2(另有 G-new:TUI 恢复) |
| P2/P3(生态护城河) | G10 MCP / G11 记忆 / G12 Skills / G13 插件 / G14 成本透明 / G15 SDK/Web / G16 平台部署 | 📝 进入 v0.3 及远期 |

**需警惕**(GAP 分析 §6.3):竞品(尤其 OpenCode 开源)迭代快,`/undo`、MCP、AGENTS.md 是**行业公约**,必须跟进;不要试图对标 Sub-agents / 多智能体大工程;架构红利(hexagonal + 事件流)是最大资产,任何新功能都应按端口-适配器模式接入。

---

## 5. 架构需求(AR)

### 5.1 AR-1 分层结构与依赖规则(P0,✅ 已落地)

| 模块(当前) | 一句话职责 | 可以 import | 禁止 import |
|---|---|---|---|
| `app/config.py` | 全局配置(仅 provider 无关字段) | — | core、session、cli |
| `ai/` | 模型配置层(protocol/catalog/transport/bridge/providers + factory) | config | core、session、container 的反向 |
| `tools/` | 工具层:原子工具 + 注册表 | config | 模型、编排 |
| `core/` | 编排层:端口、状态、图、节点、事件 | 只有 `ports.py`(及 langchain/langgraph) | config、ai、tools、session |
| `session/` | 有状态会话 + 事件分发 | core(ports/loop)、bus、store | ai、tools、config |
| `app/container.py` | 组合根,创建图与会话 | 全部(唯一交汇点) | — |
| `app/main.py` | 命令行入口(headless) | container、session、bus | core、ai、tools |
| `resources/` | 技能 / 提示词按需加载 | — | 延后可先空 |
| `extensions/` | 插件:两阶段(注册→绑定) | — | 延后 |

### 5.2 AR-2 核心契约(P0,✅ 已落地)

**AgentPorts(编排认识外部世界的唯一窗口)**:

```python
@dataclass(frozen=True)
class AgentPorts:
    bound_model: BaseChatModel            # 已 bind 工具(由组合根负责 bind)
    tool_executor: Runnable               # 工具执行器,对 loop 是黑盒
    checkpointer: object | None = None    # 持久化,由组合根决定
```

- 设计理由:编排层连"工具"概念都不需要知道——`bind_tools` 是组合根的事,加/换工具时 `core/` 零改动。

**build_graph(纯组装,零副作用)**:

```python
def build_graph(ports: AgentPorts) -> CompiledGraph:
    # START → agent →(有 tool_calls)→ tools → agent;否则 END
    # 模块顶层无任何副作用(不建模型、不发请求、不读 key)
```

- `should_continue` 只看 state 形状(最后一条消息有没有 `tool_calls`),不 import 任何具体工具。

**AgentSession(有状态会话壳)**:

```python
class AgentSession:
    def __init__(self, graph, bus, recursion_limit=50): ...
    async def run(self, text, recursion_limit=None) -> None: ...  # 发布事件,不返回值
    def run_sync(self, text) -> None: ...                         # 同步便捷入口
    def subscribe(self, fn) -> Subscriber: ...                    # 订阅事件
    def abort(self) -> None: ...                                  # 中断运行,广播 run_cancelled
    def replace_graph(self, graph) -> None: ...                   # 切换模型时换图保留 thread
```

- 会话维度 thread 累积:构造时分配稳定 thread_id,同一会话所有 `run()` 打进同一 LangGraph thread;
- v0.1 存储:靠 checkpointer 兜底(InMemorySaver),`SessionStore` 延后 v0.2;
- `steer / followup` 未落地,延后 v0.2(生命周期由 SessionManager 承接)。

### 5.3 AR-3 配置命名空间隔离(P0,✅ 已落地,防回归测试覆盖)

`.env` 是共享文件,但全局 `Settings` 与各 provider `Config` **各自解析、各自只认自己的键**;所有配置类必须 `extra="ignore"`,否则共享 `.env` 中任一命名空间的键都会让其它配置类报 `extra_forbidden`(实现时实际踩过,已修复并补防回归测试)。

### 5.4 AR-4 解耦判据(泄漏检测,P0,✅ 已落地)

分层是否成立,不看文件多整齐,看**改一层要不要动另一层**:

| 变更 | 应动的文件 | 若还动了 | 结论 |
|---|---|---|---|
| 新增一个 provider | `ai/` + 环境变量 | `session.py` / `core/` | ❌ 泄漏 |
| 新增/更换一个工具 | `tools/` | `core/loop.py` / `ai/` | ❌ 泄漏 |
| 改编排形状(加节点/改循环) | `core/` | `ai/` / `tools/` | ❌ 泄漏 |
| 换会话存储 | `store.py` + `container` | `cli.py` / `core/` | ❌ 泄漏 |
| 加会话分叉 | `session/` | `core/` | ❌ 泄漏 |

> ⚠️ 2026-08-13 实测:`tests/test_decoupling.py` 已不在当前代码树(随 TUI 层重构移除)。**AR-4 的自动校验回归列入 v0.2 验收项**(见 §12),需按当前分层(app/ 包结构)重写解耦扫描测试。

### 5.5 AR-5 演进蓝图:自研两阶段(P3,📝 蓝图存档)

「不依赖 langchain 自研统一封装」分两步走:

| 阶段 | 内容 | 状态 |
|---|---|---|
| 第一步:自研 ModelRuntime | 替代 langchain 模型客户端层(`ai/`) | ✅ 已落地(`protocol/` + `transport/` + `providers/`,pyproject 已移除 langchain-openai) |
| 第二步:自研 ReAct 编排 | 替代 langgraph 编排层(`core/` + `session/` 部分) | 📝 **暂缓**,蓝图见 self-built-orchestration-blueprint.md |

**第二步蓝图要点**(启动前必读):

- 现状:langgraph 承担 4 件事——①状态归约 `add_messages` ②图遍历 `astream` ③工具执行 `ToolNode` ④持久化 `InMemorySaver`;
- 需自研 5 组件:R1 ReAct 主循环(100-200 行)/ R2 消息归约(约 30 行,最关键)/ R3 会话持久化(JSONL 树形)/ R4 工具调度(并行 gather + 单 call 错误归属)/ R5 控制流(recursion_limit / abort / 工具超时);
- 5 个真收益:事件流原生化(翻译层消失)/ steer-followup-abort 变几行代码 / 会话树分叉变一个字典 / 工具层解耦加深 / 控制流全是普通代码;
- 4 项代价:消息归约需 spike 验证 / 会话恢复格式自设计 / 编排相关测试(约 80+)重写 / `langgraph.json` 平台部署入口失效;
- **三个未决问题**(第二步启动前必须回答):
  1. 平台部署是不是刚需?(决定是否值得放弃 langgraph 生态)
  2. 消息归约正确性 spike(工具结果按 tool_call_id 归属,写错则工具链断裂);
  3. 会话持久化格式:对齐 Pi 的 JSONL 树形,还是先线性?
- 边界:SSE 流式解析(归模型层,已做)、工具 schema(pydantic 已提供)、平台部署入口均不自研。

---

## 6. 非功能需求(NFR)

### 6.1 性能(NFR-P)

| 编号 | 指标 | 目标值 | 验收口径 | 状态 |
|---|---|---|---|---|
| NFR-P1 | 冷启动 | ≤ 1.5s | 进程启动到可输入(含配置/模型目录加载,不含网络请求) | 🔲 待实测(headless 形态) |
| NFR-P2 | 启动期网络请求 | 0 次 | 配置加载、provider 构造阶段不发起任何网络调用 | ✅ 设计保证 |
| NFR-P3 | LLM 调用附加开销 | < 50ms | codeagent 自身在模型调用外引入的本地开销上限 | 🔲 待实测 |
| NFR-P4 | 首回复感知延迟 | 由供应商决定 | 流式场景下首个 token 到达即开始渲染 | ✅ 事件流支持 |
| NFR-P5 | 流式渲染帧率 | ≥ 30 fps | 增量更新聊天区 UI 不阻塞、不闪烁 | ⚠️ 随 TUI 移除,恢复时生效 |
| NFR-P6 | 模糊命令匹配 | < 10ms(≤ 50 命令) | `fuzzy_match` 纯函数耗时上限 | ⚠️ 随 TUI 移除,恢复时生效 |
| NFR-P7 | 事件吞吐 | ≥ 100 events/s | 事件总线 emit/subscribe 全链路 | 🔲 待实测 |
| NFR-P8 | 空闲内存占用 | < 150MB | 空会话驻留内存 | 🔲 待实测 |
| NFR-P9 | 每会话增量内存 | < 50MB | 活跃会话带来的内存增量 | 🔲 待实测 |
| NFR-P10 | 长会话衰减 | 不超过线性 | 依赖 compaction(FR-5.6)防上下文无限膨胀 | 🔲 v0.2 |

### 6.2 安全(NFR-S)

| 编号 | 指标 | 要求 | 验收口径 | 状态 |
|---|---|---|---|---|
| NFR-S1 | 密钥管理 | API Key 仅存 `.env` / 环境变量 | `.gitignore` 排除;日志、事件流、状态栏不得出现明文密钥 | ✅ 设计保证 |
| NFR-S2 | 配置命名空间隔离 | 全局 Settings 与各 provider Config 各认各的键 | 全部配置类 `extra="ignore"`;测试覆盖 | ✅ |
| NFR-S3 | 危险命令防护 | bash 工具默认需确认/白名单 | 未确认不得执行;白名单外命令默认拒绝 | 🔲 黑名单已落地(FR-8.1),确认环 v0.2(FR-8.2) |
| NFR-S4 | 文件访问边界 | read/write/edit 默认限定工作区 | 跨工作区访问需用户显式确认 | 🔲 v0.2(FR-8.3) |
| NFR-S5 | Prompt 注入 | 工具返回内容按"数据"处理 | 不把工具结果当指令拼接进 system prompt 执行 | ✅ 设计约束 |
| NFR-S6 | 依赖供应链 | 锁定精确版本 | `uv.lock`;依赖面最小化(当前仅 httpx / langchain-core / langgraph / pydantic-settings) | ✅ |
| NFR-S7 | 数据隐私 | 会话数据默认本地存储 | 不上传遥测;事件流不携带密钥 | ✅ 设计保证 |
| NFR-S8 | 命令审计 | bash 危险命令拒绝带审计信息(黑名单命中原因) | 为确认环/回滚预留 | ✅ 已落地(FR-8.1) |

### 6.3 可用性(NFR-U)

| 编号 | 指标 | 要求 | 验收口径 | 状态 |
|---|---|---|---|---|
| NFR-U1 | 上手门槛 | 0 配置可体验 | 无任何 key 时 `fake` provider 可完整跑通对话 | ✅ |
| NFR-U2 | 可发现性 | 所有能力可见可查 | `/` 弹出命令列表、`/help` 全文帮助 | ⚠️ 随 TUI 移除,恢复时生效 |
| NFR-U3 | 反馈及时性 | 所有操作 ≤ 500ms 有视觉反馈 | 输入、切换、执行均有状态联动 | ⚠️ 同上 |
| NFR-U4 | 运行态指示 | agent 运行时状态可见 | RUNNING / ERROR / CANCELLED 状态可见 | ✅ headless 输出;TUI 恢复时生效 |
| NFR-U5 | 错误恢复 | Agent/命令异常不崩 | 配置损坏不阻塞启动;异常有可操作报错 | ✅ |
| NFR-U6 | 一致性 | 配置切换即时生效 | provider/model/effort 切换后状态同步更新 | ✅(replace_graph) |
| NFR-U7 | 输入容错 | 命令拼写错误有模糊提示 | 低于阈值不误执行,给可操作错误信息 | ⚠️ 随 TUI 移除 |
| NFR-U8 | 文案 | 中英文案统一、可读 | 面向中文用户优先,错误信息可操作化 | ✅ |

### 6.4 可靠性(NFR-R)

| 编号 | 指标 | 要求 | 验收口径 | 状态 |
|---|---|---|---|---|
| NFR-R1 | 崩溃恢复 | 会话可持久化,重启可恢复(v0.2) | `SessionStore` 落盘 + 恢复路径 | 🔲 v0.2 |
| NFR-R2 | 幂等性 | headless 逐行处理互不干扰 | 每行独立上下文,单行失败不拖垮整体 | ✅ |
| NFR-R3 | 超时与取消 | LLM 调用可中断 | `abort()` 中断运行;取消态事件正确广播 | ✅ |
| NFR-R4 | 重试策略 | 网络抖动可重试 | 传输层 httpx 重试;为 LLM 调用重试预留 | ✅(openai_compat 已含重试) |
| NFR-R5 | 图级可回放 | 同一 state 可重跑 | LangGraph checkpointer 提供天然基础 | ✅ |

### 6.5 可维护性(NFR-M)

| 编号 | 指标 | 要求 | 验收口径 | 状态 |
|---|---|---|---|---|
| NFR-M1 | 分层解耦 | 跨层 import 仅发生在 `app/container.py` / `app/main.py` | 解耦扫描测试强制校验(⚠️ 当前缺失,列入 v0.2 验收) | ⚠️ 需恢复自动校验 |
| NFR-M2 | 测试覆盖 | 核心编排层 100% 离线可测,总体覆盖率 ≥ 80% | `FakeClient` 注入;2026-08-14 实测 260 项测试全绿(见附录 B) | ✅ |
| NFR-M3 | 可替换性 | provider/工具/存储更换不动编排层 | 端口-适配器契约(`AgentPorts` / `AgentClient`) | ✅ |
| NFR-M4 | 代码规范 | 类型注解完整、中文 docstring | 分层职责单一,无循环 import | ✅ |
| NFR-M5 | 变更影响面 | 新增 provider=1 文件;新增工具=0 处 core 改动 | AR-4 判据 | ✅ |
| NFR-M6 | 同步约束 | `model:effort` 解析唯一实现 | `ai/model_pattern.py` 单一来源,factory 与命令层共用 | ✅ |

### 6.6 可扩展性(NFR-E)

| 编号 | 指标 | 要求 | 说明 |
|---|---|---|---|
| NFR-E1 | 供应商扩展 | 新增 provider = 新增 1 文件 + 环境变量 | `PROVIDERS` 注册表分发 |
| NFR-E2 | 工具扩展 | 新增工具不触碰 core | `bind_tools` 在组合根唯一交汇 |
| NFR-E3 | 会话扩展 | 多会话并发互不干扰 | SessionManager 设计 |
| NFR-E4 | 形态扩展 | 同图定义多平台部署 | `langgraph.json` 与 CLI 共享 |
| NFR-E5 | 感知扩展 | 事件流订阅方任意 | CLI / Web / 测试 / CI 均可订阅 |

### 6.7 兼容性(NFR-C)

| 编号 | 指标 | 要求 | 说明 |
|---|---|---|---|
| NFR-C1 | Python | ≥ 3.12 | pyproject 声明;类型注解使用 `from __future__` |
| NFR-C2 | 终端 | 支持真彩/ANSI 的现代终端 | TUI 恢复时生效 |
| NFR-C3 | 平台 | macOS / Linux 优先 | bash 工具含 Git for Windows / WSL 探测链;⚠️ Windows 实测 4 项 bash 测试失败待回归 |
| NFR-C4 | 安装 | 无系统级污染 | uv 虚拟环境隔离 |

### 6.8 可观测性(NFR-O)

| 编号 | 指标 | 要求 | 说明 |
|---|---|---|---|
| NFR-O1 | 事件流 | 10 类事件覆盖全生命周期 | FR-6.1 |
| NFR-O2 | 订阅编程接口 | `subscribe(fn)` 任意方接入 | 替代"只拿返回值"模式 |
| NFR-O3 | 日志分级 | 可开关、不泄漏密钥 | 生产可用级别可调 |

---

## 7. 数据需求(DR)

| ID | 数据对象 | 结构/格式 | 生命周期 | 状态 |
|---|---|---|---|---|
| DR-1 | 会话状态 | `AgentState`(MessagesState 扩展),thread 维度累积,checkpointer 快照 | 会话内累积;v0.1 内存(InMemorySaver),进程退出即失 | ✅ v0.1;持久化待 DR-3 |
| DR-2 | 事件流 | `AgentEvent`(type + payload + metadata)10 类,发射即弃(订阅制) | 单轮对话生命周期 | ✅ |
| DR-3 | 会话存储 | v0.2:`SessionStore` 线性存储(每轮 append);自研蓝图 R3 建议 JSONL 树形(id/parentId,天然支持分叉/回放) | 跨进程持久 | 🔲 v0.2 |
| DR-4 | 模型目录 | 内置目录(代码静态)+ `~/.codeagent/models.json` 用户覆盖,**upsert 合并**(同 id 覆盖、新 id 追加、内置保留) | 启动加载,可运行时重建(缓存 M11) | ✅ |
| DR-5 | 配置 | `~/.codeagent/.env` 命名空间隔离(全局 `LLM_PROVIDER` 与各 `PROVIDER_*`);首次启动幂等生成模板 | 启动加载 | ✅ |
| DR-6 | token 用量 | 模型 `usage_metadata` 透传为 `usage` 事件;v0.3 落库供成本透明(F-22) | 每轮产生 | ✅ 事件已落地;落库 P2 |
| DR-7 | 技能/提示词资源 | `resources/skills/`、`resources/prompts/` markdown 文件,按需加载(渐进式披露) | v0.3 启用 | 🔲 目录已建 |

---

## 8. 接口需求(IR)

| ID | 接口 | 契约要点 | 消费方 | 状态 |
|---|---|---|---|---|
| IR-1 | `AgentPorts` | frozen dataclass:`bound_model`(已 bind 工具)/ `tool_executor`(Runnable 黑盒)/ `checkpointer`(可选) | core/loop | ✅ |
| IR-2 | `build_graph(ports) -> CompiledGraph` | 纯组装零副作用;条件边 `should_continue` 只看 state 形状 | container / langgraph.json | ✅ |
| IR-3 | `AgentSession.run(text, recursion_limit=None)` | async;发布事件不返回值;thread 累积;可被 `abort()` 中断 | CLI / Web / 测试 | ✅ |
| IR-4 | `AgentSession.run_sync(text)` | 同步便捷入口(新线程 + asyncio.run) | 脚本 / 无 loop 环境 | ✅ |
| IR-5 | `EventBus.subscribe(fn)` / `emit(ev)` | 订阅方异常隔离;返回退订函数 | 任意感知方 | ✅ |
| IR-6 | `create_llm(cfg, *, registry, reasoning_effort, provider, model)` | provider+model 解析,返回未绑定工具的 ChatClient | container | ✅ |
| IR-7 | `ChatClient` 协议 + `SSEParser` | 框架无关消息/流协议;thinking/usage 全量透传 | ai/protocol | ✅ |
| IR-8 | `make_tools(cfg) -> list[BaseTool]` | 原子工具注册表枚举 | container | ✅ |
| IR-9 | CLI(headless) | `codeagent [--prompt P]`;无 `--prompt` 时 stdin 逐行;输出事件聚合文本 | 终端用户 / 脚本 | ✅ |
| IR-10 | `langgraph.json` 平台入口 | `graphs.agent` → `create_agent_graph`;与 CLI 共享同一份图定义 | LangGraph 平台 | 📝 P2 |
| IR-11 | `SessionManager`(v0.2) | `create / fork / switch / dispose` | CLI / TUI | 🔲 v0.2 |
| IR-12 | `SessionStore`(v0.2) | 线性存储 `append(entry)` / 恢复加载 | SessionManager | 🔲 v0.2 |

---

## 9. 可行性分析

### 9.1 技术实现可行性(高)

**依赖成熟度**:

| 依赖 | 版本(uv.lock) | 成熟度 | 承担角色 |
|---|---|---|---|
| httpx | ≥ 0.28.1 | 稳定 | OpenAI 兼容传输层(自研模型客户端) |
| langchain-core | ≥ 1.5.3 | 稳定 | BaseChatModel / 消息抽象 |
| langgraph | ≥ 1.2.10 | 稳定 | StateGraph / ToolNode / checkpointer |
| pydantic-settings | ≥ 2.14.2 | 稳定 | 分层配置 |
| pytest | ≥ 9.1.1 | 稳定 | 测试基建 |

(注:langchain-openai 与 textual 已随自研模型层与 TUI 移除而退出依赖表,依赖面进一步收窄。)

**关键风险与对策**:

| 风险 | 等级 | 对策 |
|---|---|---|
| 事件驱动架构实现复杂度 | 中 | Pi-Agent 成熟模式参考;`bus` 职责单一,先窄后宽(已落地) |
| 工具安全边界 | 中 | 危险命令黑名单已落地;确认机制 + 文件边界白名单 v0.2 |
| 长会话上下文膨胀 | 中 | compaction(v0.2)按手动→阈值渐进落地 |
| 多平台验证成本 | 低~中 | bash 已含 Git for Windows / WSL 探测链;⚠️ 4 项 bash 测试环境差异待回归 |
| 编排自研(第二步) | 中(暂缓) | 三未决问题回答后启动;消息归约先行 spike |

**结论**:核心依赖全部成熟稳定,架构文档已定稿,编排层契约(AgentPorts / build_graph / AgentSession)已落地。**技术风险可控,无颠覆性难点。**

### 9.2 市场定位可行性

见 §3.5:正面竞争不可行;差异化定位(可替换、可测试、可嵌入的工程底座)可行,吃国内生态与自研/教育市场。

### 9.3 资源投入可行性

**投入估算(单人全栈,按既有架构蓝图)**:

| 阶段 | 范围 | 预估工作量 | 交付物 |
|---|---|---|---|
| v0.1 | tools + core + session + container + 模型层自研(ModelRuntime) | ✅ 已落地 | headless CLI 可对话、可调用 read/write/edit/bash、事件流可订阅 |
| v0.2 | store + manager + compaction + 安全确认 + undo + AGENTS.md + TUI 恢复 + 解耦测试恢复 | 2–3 周(较 v0.1 报告上调,新增 TUI 恢复/undo/AGENTS.md) | 会话可恢复、可切换、可压缩、可回滚 |
| v0.3 | resources + extensions + MCP + 记忆 + 成本透明 + fork | 2–3 周 | 插件化、skills 按需加载 |

**成本结构**:全部依赖开源,无新增付费;主要成本为人力时间 + 模型 API 按量付费(可选,fake 可离线开发);风险集中点:单人维护可持续性、社区获取、文档与示例投入。

**投入优先级建议**:
1. v0.2 会话完善(持久化/undo/安全确认):从"可用"到"好用";
2. 恢复 TUI 交互形态与解耦扫描测试(当前缺口);
3. 再补安全确认机制(bash 确认/白名单):上线前必须;
4. 后做生态(skills/插件/Web):验证核心价值后再投入;
5. 全程保持测试全绿作为回归底线(当前 4 项环境敏感失败需先回归确认)。

---

## 10. 版本规划与里程碑

### 10.1 路线图

```
v0.1(✅ 已落地 2026-08-10): F-01~F-10   tools+core+session+container → 可对话、可调用工具、事件流可订阅
     后续演进(2026-08-13 现状): 模型客户端自研落地(ModelRuntime)、TUI 移除、headless 为当前唯一形态
v0.2(2–3 周):                F-11~F-17b  持久化+undo+安全+AGENTS.md+TUI恢复 → 可恢复、可回滚、好用
v0.3(2–3 周):                F-18~F-24   skills+插件+MCP+记忆+成本透明+fork+平台部署 → 生态成型
远期:                         F-25~F-28   多智能体/自动化/Web/Windows 全验证
(并行评估):                   编排自研第二步(蓝图存档,三未决问题回答后启动)
```

### 10.2 节奏建议(GAP 分析 §7)

1. 优先落地 **F-14 安全确认环**(bash 确认/白名单,黑名单已兜底),守住"工程化底座"信任;
2. 抢在竞品之前落地 **F-15 undo + F-22 成本透明**——社区高赞需求,与事件流/checkpointer 架构天然契合,成本低、差异化强;
3. 恢复 TUI 交互形态(FR-1.11)与解耦扫描测试(NFR-M1),补齐当前回归缺口;
4. 全程保持测试全绿作为回归底线,新功能一律可离线测试。

---

## 11. 风险分析

| 编号 | 类别 | 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|---|---|
| R1 | 技术 | 编排自研第二步中断 langgraph 平台部署入口 | 中 | 高 | 启动前回答三未决问题;平台部署刚需则重新评估净收益 |
| R2 | 技术 | 自研消息归约(工具结果按 tool_call_id 归属)写错 → 工具链断裂 | 中 | 高 | 启动前 spike 验证 |
| R3 | 技术 | Windows 平台 bash 行为差异(路径显示、PIPESTATUS) | 高 | 低~中 | 4 项失败测试回归;按环境归一化断言或补平台适配 |
| R4 | 质量 | 解耦扫描测试缺失,分层泄漏回归无法自动发现 | 中 | 中 | v0.2 重写 test_decoupling 覆盖 app/ 新结构 |
| R5 | 质量 | 文档与代码漂移(219 vs 304 vs 204 测试、TUI 状态、provider 数) | 已发生 | 中 | 以本文档为基线,版本更新时同步校准(附录 B 机制) |
| R6 | 市场 | 无自研模型,受第三方 API 制约;头部放开多供应商则差异化压缩 | 中 | 中 | 强化"工程底座"定位;成本透明(F-22)对冲信任赤字 |
| R7 | 进度 | 单人维护可持续性、社区获取不足 | 高 | 中 | 开发者指南(接入新 provider/工具)、文档与示例投入 |
| R8 | 安全 | 工具误操作风险(rm/越界写) | 中 | 高 | 黑名单已落地;v0.2 确认环 + 文件边界白名单(上线前必须) |
| R9 | 体验 | 无 TUI,交互形态倒退(相对竞品) | 确定 | 中 | ✅ TUI 已恢复 MVP(2026-08-13,E9~E11,`app/tui/`);斜杠命令/模糊补全拆 v0.2 |

---

## 12. 验收标准

### 12.1 全局验收基线(每个版本发布前必须满足)

1. **测试全绿**:`uv run pytest` 全量通过(当前 260 项全绿,2026-08-14 实测);核心编排层零网络、零密钥(`FakeClient`)可跑通全量;
2. **解耦判据**:解耦扫描测试(恢复后)强制校验跨层 import 仅出现在 `app/container.py` / `app/main.py`;
3. **离线可体验**:无任何 API Key 时以 `fake` provider 完整跑通"对话→工具调用→事件流"闭环;
4. **配置隔离**:全部配置类 `extra="ignore"`,防回归测试通过;
5. **安全底线**:密钥不出现在日志/事件流/输出;危险命令拒绝带审计信息。

### 12.2 v0.2 验收(F-11~F-17b)

- 会话持久化:重启进程后 `SessionStore` 恢复历史会话;`SessionManager` 支持 create/switch/dispose;
- 上下文压缩:手动触发 + 阈值自动触发,压缩后对话语义不丢失(回归测试);
- 安全权限:bash/write 敏感操作默认确认,未确认不执行;文件访问默认限定工作区,越界需显式确认;
- 回滚 `/undo`:回滚到指定消息及对应文件变更;
- AGENTS.md:全局→项目→子目录分层加载并注入系统提示词,越近优先级越高;
- TUI 增强:交互式终端 MVP 已恢复(2026-08-13,E9~E11),v0.2 补齐斜杠命令/模糊补全/选择器、Markdown 渲染与滚动交互;
- 解耦扫描测试恢复并通过。

### 12.3 v0.3 验收(F-18~F-24)

- Skills 按需加载:`resources/skills/` 渐进式披露生效;
- 插件两阶段(注册→绑定)可用;
- MCP 外部工具接入(含工具数分组预算策略);
- 轻量记忆跨会话生效;
- 成本透明:token 用量/费用估算可见(状态栏或输出);
- 分支会话 fork 可用;`langgraph.json` 平台入口可部署。

### 12.4 远期验收(F-25~F-28)

- 多智能体协作原型;Automations 定时触发;Web/HTTP 订阅事件流;Windows 平台全量测试通过。

---

## 附录 A:需求追踪矩阵

> 出处缩写:R=requirements-analysis.md(v0.1,已归档,内容已并入本文档)、A=architecture.md、G=feature-gap-analysis.md、B=self-built-orchestration-blueprint.md、C=2026-08-13 代码实测。

### A.1 功能需求追踪

| ID | 需求 | 优先级 | 状态 | 出处 | 对应 F-xx |
|---|---|---|---|---|---|
| FR-1.1~1.6, 1.8 | TUI 对话/流式渲染/斜杠命令/模糊补全/选择器/转义/键盘 | P0 | ✅(MVP 已恢复:对话/流式渲染/键盘导航可用;斜杠命令/模糊补全/选择器/`//` 转义拆 v0.2) | R §3.1; C | F-10, F-17b |
| FR-1.7 | 打断/取消 | P0 | ✅ 会话层保留 | R; C | — |
| FR-1.9 | Headless 模式 | P0 | ✅(headless 为默认形态;`--tui` 并行存在) | R; C | — |
| FR-1.10 | 多轮上下文 | P0 | ✅ | R; C | — |
| FR-1.11 | TUI 形态恢复(新增) | P1 | ✅(MVP,restore-tui 2026-08-13;斜杠命令等下一迭代) | C(缺口登记) | F-17b |
| FR-2.1~2.7 | 模型配置与管理 | P0/P1/P2 | ✅(2.7 规划) | R §3.1 | — |
| FR-2.8 | 模型客户端自研(ModelRuntime) | P0 | ✅ | B §1; C | — |
| FR-2.9 | 注册表缓存 | P0 | ✅ | C | — |
| FR-3.1~3.8 | 工具系统 | P0/P1 | ✅(3.5 待 v0.2) | R §3.1; C | F-01, F-02(删) |
| FR-4.1~4.7 | 编排引擎 | P0/P2 | ✅(4.7 规划) | R §3.1; A §5 | F-03~F-05 |
| FR-4.8 | 编排自研第二步 | P3 | 📝 蓝图暂缓 | B 全文 | — |
| FR-5.1~5.3 | AgentSession/总线/翻译 | P0 | ✅ | R; A §5.3; C | F-06~F-08 |
| FR-5.4~5.6 | 持久化/Manager/压缩 | P1 | 🔲 v0.2 | R; A §5.4 | F-11~F-13 |
| FR-5.7 | 会话树/分叉 | P2 | 📝 | R | F-23 |
| FR-5.8~5.9 | abort / replace_graph(新增) | P0 | ✅ | C | — |
| FR-5.10 | steer / followup | P1 | 🔲 v0.2 | A §5.3; B 收益2 | — |
| FR-6.1~6.5 | 可观测性与事件 | P0 | ✅(6.3 随 TUI 恢复) | R; C | — |
| FR-7.1~7.4 | 扩展与部署 | P2 | 🔲/📝 | R; G §5 | F-18~F-24 |
| FR-8.1~8.4 | 安全与权限 | P0/P1 | ✅ 黑名单;其余 v0.2 | G §4.2 G7 | F-14 |

### A.2 非功能需求追踪

| 组 | 条目 | 状态要点 | 出处 |
|---|---|---|---|
| NFR-P1~P10 | 性能 | 设计保证 + 待实测(部分随 TUI 恢复生效) | R §4.1 |
| NFR-S1~S8 | 安全 | 黑名单/审计已落地;确认环 v0.2 | R §4.2 |
| NFR-U1~U8 | 可用性 | 0 配置/fake 已落地;TUI 相关恢复时生效 | R §4.3 |
| NFR-R1~R5 | 可靠性 | abort 已落地;持久化 v0.2 | R §4.4 |
| NFR-M1~M6 | 可维护性 | ⚠️ 解耦扫描测试缺失(列入 v0.2 验收) | R §4.5; C |
| NFR-E1~E5 | 可扩展性 | 契约已落地 | R §4.6 |
| NFR-C1~C4 | 兼容性 | ✅ Windows 4 项 bash 测试已修复(标记文件法,2026-08-13 fix-bash-test-assertions) | R §4.7; C |
| NFR-O1~O3 | 可观测性 | 10 类事件已落地 | R §4.8; C |

---

## 附录 B:文档与代码一致性校准(2026-08-13 实测)

本附录记录四份文档与当前代码树之间的差异,作为后续版本更新时的对照基准。

### B.1 已确认差异清单

| # | 差异项 | requirements-analysis.md(v0.1, 08-10) | architecture.md(08-11) | GAP 分析(08-10) | 当前树实测(HEAD f0b29f2,2026-08-14) |
|---|---|---|---|---|---|
| 1 | 测试数量 | 219 全绿 | 304 全绿 | 219 全绿 | **260 项全绿**(08-13 曾 204 项:200 通过 + 4 项 bash 环境敏感失败,已由 fix-bash-test-assertions 修复——3 项 cwd 断言改标记文件法、1 项 PIPESTATUS 命令精简;08-14 TUI 修复、主流形态改造与 P2 死代码清理后;另有 3 项 bash 环境敏感失败待回归) |
| 2 | provider 数量 | 3(deepseek/openai/fake) | 6(+qwen/glm/kimi/minimax) | 3 | **7**(deepseek/openai/qwen/glm/kimi/minimax/fake,`PROVIDERS` 注册表确认) |
| 3 | TUI 状态 | ✅ 已落地(SessionAgentClient 流式渲染) | ✅ 已落地 | ✅ 已落地 | ✅ **已恢复为 MVP**(`app/tui/`:view/components/backend 端口 + textual 后端,`--tui` 进入;E9~E11);斜杠命令/模糊补全/选择器拆 v0.2 |
| 4 | 目录结构 | 顶层 `cli.py/container.py/config.py/model_pattern.py` + `tui/` | 同左 | 同左 | `app/` 包(main/config/container)+ `app/tui/`;`model_pattern.py` 移入 `ai/`;顶层无 cli/container/config |
| 5 | 事件类型 | 7 类(无 thinking_delta/run_cancelled/usage) | 7 类 | 7 类 | **10 类**(新增 thinking_delta / run_cancelled / usage,core/events.py 确认) |
| 6 | 会话接口 | run/subscribe/run_sync;abort 延后 | 同左 | 同左 | 新增 `abort()`、`replace_graph()` 已落地 |
| 7 | 模型客户端 | langchain-openai 统一接入 | 同左 | 同左 | **自研落地**(协议/传输/桥接三层,pyproject 已移除 langchain-openai;langchain-core/langgraph 保留于编排侧) |
| 8 | TUI 依赖 | textual 8.2.8 | textual | textual | **textual 已恢复为运行依赖**(TUI MVP 需要;pyproject dependencies 含 `textual>=2.1.0`) |
| 9 | 解耦扫描测试 | test_decoupling.py 强制校验 | §9 判据 | 有 | **test_decoupling.py 不在当前代码树**(2026-08-13 移除,计划 v0.2 按 `app/` 新分层重写) |
| 10 | 拦截管道 | FR-3.4 ❌ 已删除 | 无 | F-02 ❌ 已删除 | 确认不存在(一致) |
| 11 | 工具数量 | 4(read/write/edit/bash) | 同左 | 同左 | **7**(E8 补齐 grep/find/ls,纯 Python 落地,`tools/atomic/` + `tools/shared/` 确认) |

### B.2 校准口径约定(面向后续版本)

1. 需求状态以"代码实测"为准,文档中保留历史口径并标注 ⚠️;
2. 每次版本更新时,按 B.1 表格逐项复核并更新差异清单;
3. 测试数量口径统一为"`uv run pytest` 实测结果 + 失败项环境说明";
4. TUI 已恢复落地(2026-08-13,E9~E11):FR-1.1~1.6/1.8、FR-6.3、NFR-U2~U3 状态已由 ⚠️ 恢复为 ✅;斜杠命令/模糊补全/选择器仍列 v0.2。

---

*本文档合并自 docs/design/ 四份文档并经 2026-08-13 代码实测校准;对原文的引用以编号(R/A/G/B/C)标注于附录 A。*
