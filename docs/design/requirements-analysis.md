# codeagent 需求分析文档(完整版)

> 版本: v0.3.0(完整版,含 §0.1 状态勘误)
> 更新日期: 2026-08-27(当前状态与测试/CI 门禁复核;正文中的历史需求分析数据保留为历史快照)
> 编制口径: 以 `docs/design/` 下四份文档(需求分析报告 v0.1、架构设计、功能表 GAP 分析、编排自研蓝图)为需求来源综合而成,并对照 **2026-08-27 当前代码树**校准(校准明细见 §0.1 与附录 B)。**架构现状以 §0.1 勘误 + architecture.md(v0.3.0) 为准**。
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

## 0.1 状态勘误(2026-08-27,自研编排与 v0.3.0 已落地)

> 本文档编制于 2026-08-13(彼时编排自研仍处"第二步暂缓")。2026-08-14 `self-built-orchestration` 落地后,**编排层已全面自研**；2026-08-22 v0.3.0 功能范围完成验收。本节统一勘误:后续工作以本节 + [architecture.md](./architecture.md)(v0.3.0) 为架构事实源,以 `docs/iteration/v0.1.md` ~ `v0.3.md` 为演进记录;文中竞品对比 / GAP 分析 / 决策记录里的历史提及保留原貌(历史快照),不再逐条改动。

### 现状口径(2026-08-27 代码树复核)

| 条目 | 本文档原文口径 | 现状 |
|---|---|---|
| 编排引擎 | LangGraph(StateGraph / ToolNode / checkpointer;FR-4、AR-5、IR-2) | **自研 ReAct 主循环**(`core/loop.py` `run_agent_loop`,模型→工具→继续/结束,事件直接 emit)+ 消息归约(`core/messages.py`,按 tool_call_id 归属,uuid7) |
| AgentLoopConfig | `bound_model / tool_executor / checkpointer`(IR-1、AR-2) | `model / tools / policy`(无 store;core 循环不落盘,存储经会话层注入) |
| 编排自研第二步(FR-4.8 / AR-5) | 📝 暂缓,三未决问题待答 | ✅ **已落地**(2026-08-14,spike 双跑 diff 通过;平台部署非刚需、JSONL 树形为格式结论) |
| 事件类型(FR-6.1 / NFR-O1) | 10 类 | **11 类**(新增 `confirmation_requested`,执行前安全确认环事件) |
| 工具数量(附录 B #11) | 7 | **8 个内建工具**(新增 `skill` 技能寻址工具);MCP 工具按用户配置动态加载 |
| 会话持久化(DR-3 / FR-5.4) | 🔲 v0.2 线性 | ✅ **JSONL 树形**(`SessionStore` 按 id/parentId,v0.2 已落地,含 fork) |
| 会话生命周期(FR-5.5 / FR-5.10) | 🔲 v0.2 / 🔲 未落地 | ✅ `SessionManager`(create/switch/fork/dispose)+ `steer`/`followup`/`abort` 已落地 |
| 上下文压缩(FR-5.6) | 🔲 v0.2 | ✅ 已落地(`compaction`,手动 + 阈值) |
| 安全确认环(FR-8.2 / NFR-S3) | 🔲 v0.2 | ✅ 已落地(`security-permissions`:ApprovalPolicy + tools/security.py 三档分类器,headless 缺省 fail closed) |
| AGENTS.md 分层(F-16) | 🔲 v0.2 规划 | ✅ 已落地(`app/agents.py`,全局→项目→子目录分层注入) |
| 平台部署 `langgraph.json`(F-24 / IR-10) | 📝 P2 | **永久调整**:随自研编排改写为 HTTP/事件订阅入口(F-27);**2026-08-22 定案:Web/HTTP 入口移出 v0.3(E12)**——平台向无真实消费者,价值被 CLI/TUI 事件流订阅覆盖,推迟远期按需重估 |
| 测试基线(附录 B) | 336(2026-08-14) | **938 passed**(2026-08-27 Windows 复核；测试零网络零密钥；跨平台矩阵已配置，结果以 CI artifact 为准) |
| 解耦扫描测试(NFR-M1 / AR-4) | 已移除待恢复 | ✅ 已重写恢复(`tests/test_decoupling.py`,2026-08-14,AST 扫描 + anti-wargaming 守卫) |

> 权威架构描述见 [architecture.md](./architecture.md)(v0.3);迭代与验收见 `docs/iteration/v0.2.md` / `v0.3.md`;审计见 `docs/review/audit-2026-08-21.md`。

### 现阶段工程治理状态(2026-08-27)

- 全量离线测试：`uv run pytest -q`，**938 passed**。
- 静态检查：Ruff 已接入，首阶段阻断语法错误、未定义名称和未使用局部变量。
- 发布前检查：CI 已配置 wheel 构建、干净虚拟环境安装、fake provider CLI 和内建 resources 冒烟。
- 跨平台检查：CI 已配置 Ubuntu、Windows、macOS 矩阵，统一使用离线测试集；本地 Windows 结果已复核，其他平台以 CI 为准。
- 覆盖率/性能：已输出结构化报告，暂不设置高强度硬阈值，待稳定 CI 数据后评估。

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
| 端口-适配器(hexagonal) | 横切解耦架构:编排层只认识端口(`AgentLoopConfig`),具体实现由组合根装配 |
| 三层协作 / 双层 loop | Pi-Agent 设计哲学:Factory(装配)/ Session(单对话)/ Runtime(会话生命周期)三层;无状态循环(LangGraph 图)与有状态外壳(`session/`)双层 |
| 会话即状态 | 会话上下文以 thread 维度累积在图中,状态即会话 |
| 组合根 | `container.py`(现 `app/container.py`),全项目唯一允许跨层 import 的地方 |
| ModelRuntime | 自研模型客户端层(自研蓝图第一步):`model/` + `transport/` + `providers/`,替代 langchain 模型客户端 |
| ReAct | 推理-行动循环:模型 ↔ 工具交替直至模型不再请求工具 |
| provider | 模型供应商(deepseek / openai / qwen / glm / kimi / minimax / fake) |
| effort | 运行时思考强度(`model:effort` 内联语法) |

### 1.5 参考文档

| 文档 | 说明 |
|---|---|
| `requirements-analysis.md`(v0.1,已归档) | 需求分析报告 v0.1(2026-08-10),内容已并入本文档;原文可从 git 历史(提交 5b137b4)恢复 |
| [architecture.md](architecture.md) | 架构设计文档 v0.3.0(2026-08-27) |
| [feature-gap-analysis.md](feature-gap-analysis.md) | 功能表全面分析 / 竞品对标 GAP(2026-08-10) |
| [self-built-orchestration-blueprint.md](self-built-orchestration-blueprint.md) | 编排引擎自研决策与收益记录(第二步已落地,2026-08-27 校准) |
| README.md / pyproject.toml / src/codeagent/ | 项目现状(2026-08-27 复核) |

---

## 2. 项目概述与产品定位

### 2.1 项目背景

`codeagent` 是基于**自研编排**(2026-08-14 起,已弃用 langgraph/langchain)的编程 Agent,采用 Pi-Agent 设计哲学(三层协作 / 双层 loop / 事件驱动 / 会话即状态)+ 端口-适配器(hexagonal)横切解耦。v0.1 已打通"可对话 + 可调用工具 + 事件流可订阅"的最小闭环,v0.2 完成会话完善(持久化/分叉/安全确认/TUI 命令体系),v0.3 已完成 Skills、MCP、token 用量透明、会话树及全量验收。

### 2.2 产品愿景

目标不是"复刻一个 Claude Code",而是构建一个**可演进、可替换、可感知、可测试**的编程 Agent **工程底座**:

| 特性 | 含义 | 落地形态 |
|---|---|---|
| 可演进 | 从单工具调用型 Agent 平滑演进到多 Agent / 多会话 / 平台部署 | 分层结构 + 演进路线(§10) |
| 可替换 | 更换模型供应商、工具集、存储,均不触碰 Agent 编排代码 | 端口-适配器 + 组合根唯一交汇 |
| 可感知 | 会话运行过程以事件流对外暴露,CLI / TUI / 测试 / CI 都能订阅 | `EventBus` + `AgentEvent` 全生命周期;Web/HTTP 暂未实现 |
| 可测试 | 核心编排层零网络、零密钥即可运行 | `FakeClient` 离线假模型注入 |

### 2.3 设计哲学:两条正交轴(架构需求 AR 的总纲)

| 轴 | 分的是什么 | 来源 |
|---|---|---|
| **横切轴:依赖方向** | config / 工具 / 编排 / 调用之间谁认识谁 | 端口-适配器(hexagonal) |
| **纵切轴:生命周期** | 装配(Factory)/ 单个对话(Session)/ 会话生命周期(Runtime) | Pi-Agent 三层协作 |

Loop 双层(无状态循环 / 有状态 Agent)是另一条正交结构:**自研 ReAct 主循环**(`core/loop.py` `run_agent_loop`)提供无状态循环(模型→工具→继续/结束),有状态外壳由 `session/` 层补齐。

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
| 技术栈 | Python + 自研编排(ReAct 主循环 + JSONL 树形,无 langgraph) | Node.js | TypeScript(闭源) | TypeScript(开源) |
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
| 终端 TUI | ✅ | ✅ | ✅ | ✅ | ✅ Textual TUI（命令、补全、选择器、Markdown、滚动与确认环） | 齐平 |
| 工具集 read/write/edit/bash | ✅ | ✅ | ✅ | ✅ | ✅ 已落地 | 齐平 |
| ReAct 编排(自研) | ✅ | ✅ | ✅ | ✅ | ✅ 已落地(全异步自研循环,工具并行+错误归属精确,无 langgraph) | 齐平 |
| 事件流/可感知 | 部分 | 部分 | 部分 | 部分 | ✅ AgentEvent 11 类全生命周期 | 领先 |
| 会话持久化/恢复 | ✅ | ✅ | ✅ | ✅ | ✅ JSONL 树形会话，可恢复 / 切换 / 压缩 / 分叉 | 齐平 |
| 会话回滚 /undo | 部分 | 需求中(297👍) | 部分 | ✅ 快照回滚 | ✅ 以 `/fork` 分支会话语义替代撤销 | 有意差异 |
| 分层指令 AGENTS.md | ✅ | ✅ | 部分 | 提案被关 | ✅ 全局→项目→子目录分层注入 | 齐平 |
| 记忆系统 Memories | ✅ | ✅ | 部分 | ⬜ | 📝 P2 | P2 差距 |
| MCP 工具扩展 | ✅ | ✅ | ✅ | ✅ | ✅ 最小协议面 + 分组预算 + 权限规则 | 齐平（完整生态留后续） |
| Skills 技能系统 | ✅ 成熟 | ✅ | ✅ | 部分 | ✅ 三源发现 + 渐进式披露 + `/skills` | 齐平 |
| 插件系统 | ✅ 本地免市集 | ✅ | ✅ | 部分 | 📝 已移出 v0.3（Skills + MCP 覆盖当前需求） | 远期重估 |
| 安全权限模型 | ✅ 手动挡/分类器 | 审批机制 | ✅ | 部分 | ✅ ApprovalPolicy 三档分类 + TUI 确认 / headless fail closed | 齐平 |
| 成本透明/配额控制 | ⬜ 出问题 | ⬜ 出问题 | 部分 | ⬜ | ✅ token 用量落库与可见（不做费用估算） | 差异化基础已具备 |
| 多智能体/Teams | ✅ | ✅ | 部分 | ⬜ | 📝 P3 | P3 |
| 定时任务 Automations | 部分 | ✅ | 部分 | ⬜ | 📝 P3 | P3 |
| SDK 编程接入 | ✅ | ✅ | ✅ | 部分 | ✅ 事件流天然适配 | P2/P3 |
| 平台部署 | ✅ | ✅ | ✅ | 部分 | ⚠️ `langgraph.json` 废弃,改写为 HTTP/事件订阅(F-27);**2026-08-22 移出 v0.3(E12),远期按需重估** | P2/P3 |

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
| FR-2.2 | 统一模型创建入口 | `app.composition.model_selection.create_llm()` 按 provider+model 解析并构造未绑定工具的模型 | P0 | ✅ |
| FR-2.3 | 内置模型目录 | 模型元数据(id/别名/reasoning/maxTokens)静态登记(`catalog/builtin.py`) | P0 | ✅ |
| FR-2.4 | 用户模型覆盖 | `~/.codeagent/models.json` 按 id **upsert 合并**(同 id 覆盖、新 id 追加、内置保留) | P1 | ✅ |
| FR-2.5 | 运行时思考强度切换 | `model:effort` 内联 / `/effort` 命令,优先级:内联>参数>配置默认 | P0 | ✅(`app/composition/model_selection.py` 单一解析实现) |
| FR-2.6 | 缺失密钥可操作报错 | 缺 API Key 报"请配置 DEEPSEEK_API_KEY"而非 SDK 原始错误 | P0 | ✅ |
| FR-2.7 | 模型列表探测 | 调用供应商 `/models` 自动发现模型(当前目录静态兜底) | P2 | 📝 |
| FR-2.8 | 模型客户端自研(ModelRuntime) | 框架无关模型契约 + OpenAI 兼容传输层,替代 langchain 模型客户端(自研蓝图第一步) | P0 | ✅ 已落地:`model/`(ChatClient 契约)+ `transport/sse.py` 与 `transport/openai_compat.py`(httpx);`ai/bridge/` 已随自研编排删除,组合根直接适配 |
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
| FR-4.1 | AgentLoopConfig 端口 | 编排认识的唯一外部世界:`bound_model / tool_executor / checkpointer` | P0 | ✅ |
| FR-4.2 | AgentState | 对话状态结构(基于 MessagesState) | P0 | ✅ |
| FR-4.3 | ReAct 循环 | agent →(有 tool_calls)→ tools → agent;否则 END;全异步 | P0 | ✅ |
| FR-4.4 | agent / tools 节点 | 异步节点 + 工具异常兜底 | P0 | ✅ |
| FR-4.5 | 循环条件 | `should_continue` 只看 state 形状,不 import 具体工具 | P0 | ✅ |
| FR-4.6 | Checkpointer | 图级持久化(thread_id);默认内存 InMemorySaver,会话维度累积 | P0 | ✅ |
| FR-4.7 | 多智能体协作 | 多 Agent 编排(远期) | P2 | 📝 |
| FR-4.8 | 编排自研(第二步) | ReAct 主循环 / 消息归约 / 持久化 / 工具调度 / 控制流自研,替代 langgraph 编排层 | P3 | ✅ **已落地**(2026-08-14 `self-built-orchestration`:三未决问题已答——平台部署非刚需、归约 spike 通过、JSONL 树形为格式结论;详见 §0.1) |

### 4.6 FR-5 会话层

| ID | 需求 | 说明 | 优先级 | 状态 |
|---|---|---|---|---|
| FR-5.1 | AgentSession | 全异步 `run` + `subscribe` + `run_sync`;会话维度 thread 累积 | P0 | ✅ |
| FR-5.2 | 事件总线 | `EventBus.subscribe / emit`,CLI / TUI / 测试统一订阅 | P0 | ✅ |
| FR-5.3 | 事件流翻译 | `graph.astream(thread_id, [messages, updates])` → `AgentEvent` 序列 | P0 | ✅ |
| FR-5.4 | 会话持久化 | SessionStore 存储,重启可恢复 | P1 | ✅ 已落地(v0.2:**JSONL 树形**,按 id/parentId) |
| FR-5.5 | SessionManager | create / fork / switch / dispose | P1 | ✅ 已落地(v0.2,含 `replace_config` 热切换) |
| FR-5.6 | 上下文压缩 | 手动 + 阈值触发 compaction | P1 | ✅ 已落地(v0.2) |
| FR-5.7 | 会话树/分叉 | 分支会话、对比探索 | P2 | ✅ fork 已落地(v0.2,JSONL 树形);树导航 v0.3 |
| FR-5.8 | 运行中断 abort | `abort()` 中断当前运行并广播 `run_cancelled` | P0 | ✅ 已落地 |
| FR-5.9 | 端口热替换 | `replace_config()` 切换 provider/model/effort 时重建端口 | P0 | ✅ 已落地(`SessionManager.replace_config`) |
| FR-5.10 | steer / followup | 运行中注入消息 / 结束后追问一轮 | P1 | ✅ 已落地(v0.2;自研循环下为几行代码,验证蓝图"收益 2") |

### 4.7 FR-6 可观测性与事件

| ID | 需求 | 说明 | 优先级 | 状态 |
|---|---|---|---|---|
| FR-6.1 | AgentEvent 类型 | **11 类**:`session_started / text_delta / thinking_delta / agent_message / tool_call / tool_result / turn_end / error / run_cancelled / usage / confirmation_requested`(确认环事件) | P0 | ✅(比 v0.1 报告多出 thinking_delta / run_cancelled / usage;`confirmation_requested` 随 security-permissions 加入) |
| FR-6.2 | 事件订阅接口 | 对外暴露可编程订阅(`EventBus.subscribe`,订阅方异常隔离) | P0 | ✅ |
| FR-6.3 | 状态栏实时反馈 | TUI 运行态/错误态/取消态可视化 | P0 | ✅(随 TUI 恢复:E9~E11 状态栏 + 状态色,运行/错误/取消可见) |
| FR-6.4 | token 用量事件 | `usage` 事件透传模型 usage_metadata | P0 | ✅ 已落地 |
| FR-6.5 | 思考过程事件 | `thinking_delta` 透传推理模型 reasoning_content | P0 | ✅ 已落地(自研蓝图"收益 1"的 thinking 缺口已闭合) |

### 4.8 FR-7 扩展与部署

| ID | 需求 | 说明 | 优先级 | 状态 |
|---|---|---|---|---|
| FR-7.1 | Skills 按需加载 | `resources/skills/` 技能文件渐进式披露 | P2 | ✅ 三源发现、渐进式披露与 `/skills` 已落地 |
| FR-7.2 | 插件系统 | `extensions/` 两阶段(注册→绑定)扩展机制 | P2 | 📝 已移出 v0.3，待 MCP 生态成熟后重估 |
| FR-7.3 | 平台部署 | 平台入口 | P2 | ⚠️ **永久调整**(v0.2 定案):`langgraph.json` 随自研编排废弃,改写为 HTTP/事件订阅入口(F-27);**2026-08-22 移出 v0.3(E12),远期按需重估** |
| FR-7.4 | Web / API 暴露 | 事件流天然适配 Web 订阅 | P2 | 📝(随 F-27 移出,远期按需重估) |

### 4.9 FR-8 安全与权限(上线前刚需,GAP F-14)

| ID | 需求 | 说明 | 优先级 | 状态 |
|---|---|---|---|---|
| FR-8.1 | 危险命令黑名单 | `rm -rf /` 等价写法拦截,拒绝带审计信息(命中原因) | P0 | ✅ 已落地(字符串正则 + shlex 分词语义级检测) |
| FR-8.2 | bash 确认环 | 敏感/未确认命令默认拒绝或需用户确认 | P1 | ✅ 已落地(v0.2 `security-permissions`:ApprovalPolicy 三档 deny/ask/allow;headless 缺省 fail closed,`--yes` 逃生舱) |
| FR-8.3 | 文件访问边界 | read/write/edit 默认限定工作区,跨工作区访问需显式确认 | P1 | ✅ 已落地(`tools/security.py` `classify_file`:越界读 allow+warning,越界写 ask;bash 经 `_dangerous_intent` + 边界判定) |
| FR-8.4 | Prompt 注入防护 | 工具返回内容按"数据"处理,不拼进 system prompt 当指令执行 | P0 | ✅ 设计约束,持续保持 |

### 4.10 修订版功能实现清单(合并 GAP 分析 §5,F-01~F-28)

> 与 FR 编号的映射见附录 A;`[竞品对标]` 表示由竞品最新动态催生的新增项。

**P0 — v0.1:最小可跑闭环**

| ID | 功能 | 状态(2026-08-13) |
|---|---|---|
| F-01 | `tools/` 原子工具 read/write/edit/bash + 注册表 | ✅ 已落地(08-09) |
| F-02 | ~~`tools/pipeline.py` 拦截管道~~ | ❌ 已删除(危险命令由 bash 黑名单承担) |
| F-03 | `core/ports.py` AgentLoopConfig | ✅ 已落地(**自研版:`model / tools / policy`,无 store**) |
| F-04 | `core/messages.py` 消息模型 + `core/loop.py` `run_agent_loop` | ✅ 已落地(自研编排后 `state.py`/`build_graph` 删除,改为自研 ReAct 主循环,2026-08-14) |
| F-05 | ~~`core/nodes/` agent & tools 节点~~ | ⚠️ 随自研编排删除(循环内直接 emit,工具并行经 `asyncio.gather`) |
| F-06 | `core/events.py` AgentEvent 类型 | ✅ 已落地(**11 类事件**,含 `confirmation_requested`) |
| F-07 | `session/bus.py` 事件总线 | ✅ 已落地 |
| F-08 | `session/session.py` AgentSession | ✅ 已落地(含 abort / steer / followup;自研版) |
| F-09 | `container.py` 接线(现 `app/container.py`) | ✅ 已落地(create_agent_config / create_agent_session / create_session_manager / create_tui_app) |
| F-10 | 流式回复渲染 | ⚠️ 事件→StreamChunk 渲染层随 TUI 移除;headless 事件聚合保留 |

**P1 — v0.2:好用的刚需(1–2 周)**

| ID | 功能 | 说明 | 依据 |
|---|---|---|---|
| F-11 | `session/store.py` 会话持久化 | ✅ JSONL 树形,重启恢复 | 竞品标配 |
| F-12 | `session/manager.py` SessionManager | ✅ create/switch/fork/dispose | 竞品标配 |
| F-13 | `session/compaction.py` 上下文压缩 | ✅ 手动 + 阈值 | 长会话刚需 |
| F-14 | 安全权限模型 `[竞品对标]` | ✅ 已落地(security-permissions:三档分类器 + 确认环) | Claude Code 手动挡 |
| F-15 | 会话回滚 `/undo` `[竞品对标]` | ⚠️ **改写为 `/fork`**(v0.2 T-42 定案:回滚语义以分支会话替代,F-23 提前) | Codex 297👍 / OpenCode 快照 |
| F-16 | AGENTS.md 分层指令 `[竞品对标]` | ✅ 已落地(agents-md-hierarchy:全局→项目→子目录,`app/agents.py`) | 行业标准化 |
| F-17 | 会话列表与切换 | ✅ 已落地(`/sessions`,订阅跟随切换) | 竞品标配 |
| F-17b | TUI 形态恢复(FR-1.11) | ✅ 已落地(v0.2 T-44/T-45:命令/补全/选择器/Markdown/滚动) | 本项目演进 |

**P2 — v0.3:生态与差异化(2–3 周)**

| ID | 功能 | 说明 | 依据 |
|---|---|---|---|
| F-18 | `resources/skills/` 技能系统 | ✅ 已落地(v0.3 阶段 1,skills-system:三源发现 + 渐进式披露 + `/skills`) | Claude/Codex Skills |
| F-19 | `extensions/` 插件系统 | 📝 已移出 v0.3（Skills + MCP 覆盖当前需求），远期重估 | Claude 本地插件 |
| F-20 | MCP 客户端适配 `[竞品对标]` | ✅ 已落地（`tools/list` / `tools/call`、命名空间化、分组预算、权限规则） | 竞品标配 |
| F-21 | 轻量记忆 `~/.codeagent/memory` `[竞品对标]` | 📝 已移出 v0.3，远期按需重估 | Codex Memories |
| F-22 | 成本透明 `[竞品对标]` | ✅ token 用量归一、落库与可见；费用估算按范围调整移出 | 信任赤字诉求 |
| F-23 | 分支会话 fork | ✅ fork 已于 v0.2 落地；会话树导航已于 v0.3 落地 | Pi fork 语义 |
| F-24 | 平台部署 `langgraph.json` | ⚠️ **永久调整**(v0.2 定案):随自研编排废弃,改写为 HTTP/事件订阅入口(F-27);**2026-08-22 移出 v0.3(E12),远期按需重估** | — |

**P3 — 远期**

| ID | 功能 | 说明 |
|---|---|---|
| F-25 | 多智能体协作 | Teams 级;事件流天然适配 |
| F-26 | Automations 定时任务 | 后台触发 agent |
| F-27 | Web / HTTP API | 事件流订阅暴露;**2026-08-22 从 v0.3 移出(E12),远期按需重估** |
| F-28 | Windows 验证 | ✅ 已闭环:bash 探测链适配 + fix-bash-test-assertions 断言修复(2026-08-13)+ WSL 转发器探测修复(2026-08-14);2026-08-27 Windows 复核全量 **938 passed** |

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
| `ai/` | 模型基础设施(model/catalog/transport/providers) | 基础依赖 | app、core、session、tools 的反向 |
| `tools/` | 工具层:原子工具 + 注册表 | config | 模型、编排 |
| `core/` | 编排层:端口、消息、循环、事件 | 只有 `ports.py`(及 core 内部) | config、ai、tools、session |
| `session/` | 有状态会话 + 事件分发 | core(ports/loop)、bus、store | ai、tools、config |
| `app/container.py` | 组合根,创建图与会话 | 全部(唯一交汇点) | — |
| `app/main.py` | 命令行入口(headless) | container、session、bus | core、ai、tools |
| `resources/` | 技能 / 提示词按需加载 | — | 延后可先空 |

### 5.2 AR-2 核心契约(P0,✅ 已落地)

**AgentLoopConfig(编排认识外部世界的唯一窗口,自研版)**:

```python
@dataclass(frozen=True)
class AgentLoopConfig:
    model: ModelPort               # 模型端口(组合根适配 ai 层 ChatClient)
    tools: list[Any]               # 工具列表(自研 AtomicTool 实例,直接 invoke)
    policy: ApprovalPolicy | None = None   # 执行前安全策略(可空 = 无确认环)
```

- 设计理由:编排层不绑定具体工具——工具列表作为数据传入循环按名查找 `invoke`,加/换工具时 `core/` 零改动;`store` 不在端口内(core 循环不落盘,存储经会话层注入)。

**run_agent_loop(自研 ReAct 主循环)**:

```python
async def run_agent_loop(session, model, tools, policy, ...) -> None:
    # for 循环:模型 → 工具 → 继续/结束
    # 有 tool_calls → 逐个经 policy.decide → emit(tool_call / tool_result)
    # 无 tool_calls → 结束本轮
```

- 循环条件由消息形状驱动(最后一条有没有 `tool_calls`),不 import 任何具体工具;事件在循环内直接 emit(无翻译层)。

**AgentSession(有状态会话壳)**:

```python
class AgentSession:
    def __init__(self, ports, bus, store=None, session_id=None,
                 recursion_limit=50, tool_timeout=None, summarizer=None): ...
    async def run(self, text) -> None: ...    # 直接驱动 run_agent_loop,发布事件,不返回值
    async def steer(self, text) -> None: ...  # 运行中注入消息
    async def followup(self) -> None: ...     # 结束后续跑一轮
    def subscribe(self, fn) -> Subscriber: ...                    # 订阅事件
    def abort(self) -> None: ...                                  # 中断运行,广播 run_cancelled
```

- 会话历史自研 `Message` 列表;成功轮次才落盘 `SessionStore`(JSONL 树形),失败/取消内存回滚;
- `steer / followup / abort` 已落地(v0.2,自研循环下为几行代码,验证蓝图"收益 2");热切换经 `SessionManager.replace_config`。

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

> ✅ 2026-08-14 已重写恢复:`tests/test_decoupling.py` AST 扫描强制校验(70+ 项断言),并带 anti-wargaming 守卫(`test_scan_has_content` / `test_composition_roots_exist` / `test_textual_only_in_engine_backend`),规则写错或例外文件被删都会被抓住。

### 5.5 AR-5 演进蓝图:自研两阶段(P3,✅ 两步均已落地)

「不依赖 langchain 自研统一封装」分两步走:

| 阶段 | 内容 | 状态 |
|---|---|---|
| 第一步:自研 ModelRuntime | 替代 langchain 模型客户端层(`ai/`) | ✅ 已落地(`model/` + `transport/` + `providers/`,pyproject 已移除 langchain-openai) |
| 第二步:自研 ReAct 编排 | 替代 langgraph 编排层(`core/` + `session/` 部分) | ✅ **已落地**(2026-08-14 `self-built-orchestration`:三未决问题已答——平台部署非刚需、归约 spike 通过(5 场景双跑 diff)、JSONL 树形为格式结论;pyproject 移除 langchain-core/langgraph) |

**第二步蓝图要点**(已落地,2026-08-14 验证):

- 蓝图主张:自研 5 组件(R1 ReAct 主循环 / R2 消息归约(约 30 行,最关键)/ R3 会话持久化(JSONL 树形)/ R4 工具调度(并行 gather + 单 call 错误归属)/ R5 控制流(recursion_limit / abort / 工具超时)),收益为事件流原生化、steer/followup/abort 变几行代码、会话树分叉变一个字典、工具层解耦加深、控制流全是普通代码——均已兑现。
- 三未决问题结论(2026-08-14 评估定案):①平台部署**非刚需**,可放弃 langgraph 生态(F-24 改写为 HTTP/事件订阅入口);②消息归约 spike 为**正确性 gate**,5 场景双跑 diff ALL PASS;③会话持久化定案 **JSONL 树形**(按 id/parentId)。
- 边界:SSE 流式解析(归模型层)、工具 schema(pydantic 已提供)不自研;平台部署入口经自研后重设计(见上)。

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
| NFR-S6 | 依赖供应链 | 锁定精确版本 | `uv.lock`;依赖面最小化(自研编排后:httpx / pydantic / pydantic-settings / textual,无 langchain/langgraph) | ✅ |
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
| NFR-R5 | 会话可回放 | 同一历史可重跑 | JSONL 树形存储提供回放基础(自研编排后替代 checkpointer) | ✅ |

### 6.5 可维护性(NFR-M)

| 编号 | 指标 | 要求 | 验收口径 | 状态 |
|---|---|---|---|---|
| NFR-M1 | 分层解耦 | 跨层 import 仅发生在 `app/container.py` / `app/main.py` | `tests/test_decoupling.py` AST 强制校验(2026-08-14 重写,70 项断言) | ✅ |
| NFR-M2 | 测试覆盖 | 核心编排层 100% 离线可测,总体覆盖率 ≥ 80% | `FakeClient` 注入;快速质量集覆盖率报告为 79%,全量测试 938 passed | ⚠️(报告已接入，暂不设置硬阈值，待 CI 数据稳定后评估) |
| NFR-M3 | 可替换性 | provider/工具/存储更换不动编排层 | 端口-适配器契约(`AgentLoopConfig` / `AgentClient`) | ✅ |
| NFR-M4 | 代码规范 | 类型注解完整、中文 docstring | 分层职责单一,无循环 import | ✅ |
| NFR-M5 | 变更影响面 | 新增 provider=1 文件;新增工具=0 处 core 改动 | AR-4 判据 | ✅ |
| NFR-M6 | 同步约束 | `model:effort` 解析唯一实现 | `app/composition/model_selection.py` 单一来源,组合根各入口共用 | ✅ |

### 6.6 可扩展性(NFR-E)

| 编号 | 指标 | 要求 | 说明 |
|---|---|---|---|
| NFR-E1 | 供应商扩展 | 新增 provider = 新增 1 文件 + 环境变量 | `PROVIDERS` 注册表分发 |
| NFR-E2 | 工具扩展 | 新增工具不触碰 core | `bind_tools` 在组合根唯一交汇 |
| NFR-E3 | 会话扩展 | 多会话并发互不干扰 | SessionManager 设计 |
| NFR-E4 | 形态扩展 | 事件流多平台订阅 | CLI / TUI / 测试 / CI 均可订阅;Web/HTTP 入口(F-27)已移出 v0.3(2026-08-22,E12),Web 仅为潜在消费方 |
| NFR-E5 | 感知扩展 | 事件流订阅方任意 | CLI / TUI / 测试 / CI 均可订阅 |

### 6.7 兼容性(NFR-C)

| 编号 | 指标 | 要求 | 说明 |
|---|---|---|---|
| NFR-C1 | Python | ≥ 3.12 | pyproject 声明;类型注解使用 `from __future__` |
| NFR-C2 | 终端 | 支持真彩/ANSI 的现代终端 | TUI 恢复时生效 |
| NFR-C3 | 平台 | macOS / Linux 优先 | ⚠️ bash 含 Git for Windows / WSL 探测链;Windows 已复核 938 passed;Ubuntu/Windows/macOS CI 矩阵已配置，其他平台结果待 CI |
| NFR-C4 | 安装 | 无系统级污染 | uv 虚拟环境隔离 |

### 6.8 可观测性(NFR-O)

| 编号 | 指标 | 要求 | 说明 |
|---|---|---|---|
| NFR-O1 | 事件流 | 11 类事件覆盖全生命周期 | FR-6.1 |
| NFR-O2 | 订阅编程接口 | `subscribe(fn)` 任意方接入 | 替代"只拿返回值"模式 |
| NFR-O3 | 日志分级 | 可开关、不泄漏密钥 | 生产可用级别可调 |

---

## 7. 数据需求(DR)

| ID | 数据对象 | 结构/格式 | 生命周期 | 状态 |
|---|---|---|---|---|
| DR-1 | 会话状态 | 自研 `Message`(role/content/tool_calls/tool_call_id/id/parentId,uuid7),会话维度累积 | 会话内累积;v0.1 内存,进程退出即失;v0.2 起落盘 DR-3 | ✅ |
| DR-2 | 事件流 | `AgentEvent`(type + payload + metadata)**11 类**,发射即弃(订阅制) | 单轮对话生命周期 | ✅ |
| DR-3 | 会话存储 | v0.2 定案:**JSONL 树形**(每轮 append,按 id/parentId,天然支持分叉/回放;替代 checkpointer) | 跨进程持久 | ✅ 已落地(v0.2,含 fork) |
| DR-4 | 模型目录 | 内置目录(代码静态)+ `~/.codeagent/models.json` 用户覆盖,**upsert 合并**(同 id 覆盖、新 id 追加、内置保留) | 启动加载,可运行时重建(缓存 M11) | ✅ |
| DR-5 | 配置 | `~/.codeagent/.env` 命名空间隔离(全局 `LLM_PROVIDER` 与各 `PROVIDER_*`);首次启动幂等生成模板 | 启动加载 | ✅ |
| DR-6 | token 用量 | 模型 `usage_metadata` 透传为 `usage` 事件;v0.3 会话级 append-only 落库并在 `/status` 与 CLI 展示 | 每轮产生 | ✅ 已落地（输入 / 输出 / 推理 / 缓存命中；不做费用估算） |
| DR-7 | 技能/提示词资源 | `resources/skills/` markdown 文件,按需加载(渐进式披露:描述入 prompt,正文经 skill 工具) | v0.3 阶段 1 启用 | ✅ 已落地(三源发现,同名遮蔽 个人>项目>内建) |

---

## 8. 接口需求(IR)

| ID | 接口 | 契约要点 | 消费方 | 状态 |
|---|---|---|---|---|
| IR-1 | `AgentLoopConfig` | frozen dataclass:`model`(ModelPort)/ `tools`(list[Any])/ `policy`(ApprovalPolicy,可选);**无 store**(core 不落盘) | core/loop | ✅ 已落地(自研版) |
| IR-2 | `run_agent_loop(session, model, tools, policy, ...)` | 自研 ReAct 主循环;循环内直接 emit 事件;循环条件看消息形状 | session/session | ✅ 已落地(自研版,替代 build_graph) |
| IR-3 | `AgentSession.run(text, recursion_limit=None)` | async;发布事件不返回值;thread 累积;可被 `abort()` 中断 | CLI / TUI / 测试 | ✅ |
| IR-4 | `AgentSession.run_sync(text)` | 同步便捷入口(新线程 + asyncio.run) | 脚本 / 无 loop 环境 | ✅ |
| IR-5 | `EventBus.subscribe(fn)` / `emit(ev)` | 订阅方异常隔离;返回退订函数 | 任意感知方 | ✅ |
| IR-6 | `create_llm(cfg, *, registry, reasoning_effort, provider, model)` | provider+model 解析,返回未绑定工具的 ChatClient | container | ✅ |
| IR-7 | `ChatClient` 协议 + `SSEParser` | 框架无关消息/流协议;thinking/usage 全量透传 | ai/model + ai/transport/sse | ✅ |
| IR-8 | `make_tools(cfg) -> list[BaseTool]` | 原子工具注册表枚举 | container | ✅ |
| IR-9 | CLI(headless) | `codeagent [--prompt P]`;无 `--prompt` 时 stdin 逐行;输出事件聚合文本 | 终端用户 / 脚本 | ✅ |
| IR-10 | ~~`langgraph.json` 平台入口~~ | ⚠️ 随自研编排废弃(v0.2 定案);改写为 HTTP/事件订阅入口(F-27);**2026-08-22 移出 v0.3(E12),远期按需重估** | Web/HTTP | 📝 远期 |
| IR-11 | `SessionManager` | `create / fork / switch / dispose` + `replace_config` 热切换 | CLI / TUI | ✅ 已落地(v0.2) |
| IR-12 | `SessionStore` | JSONL 树形 `append(entry)`(按 id/parentId)/ 恢复加载 | SessionManager | ✅ 已落地(v0.2) |

---

## 9. 可行性分析

### 9.1 技术实现可行性(高)

**依赖成熟度**:

| 依赖 | 版本(uv.lock) | 成熟度 | 承担角色 |
|---|---|---|---|
| httpx | ≥ 0.28.1 | 稳定 | OpenAI 兼容传输层(自研模型客户端) |
| pydantic / pydantic-settings | ≥ 2.x | 稳定 | 工具 Args schema / 分层配置 |
| textual | ≥ 2.1.0 | 稳定 | TUI 引擎(仅 `app/tui/textual_backend.py` 加载) |
| pytest | ≥ 9.1.1 | 稳定 | 测试基建 |

(注:langchain-core / langgraph / langchain-openai 已随自研编排与模型层落地**全部移除**——2026-08-14 自研编排后运行时依赖收敛为 httpx / pydantic / pydantic-settings / textual。)

**关键风险与对策**:

| 风险 | 等级 | 对策 |
|---|---|---|
| 事件驱动架构实现复杂度 | 中 | Pi-Agent 成熟模式参考;`bus` 职责单一,先窄后宽(已落地) |
| 工具安全边界 | 中 | 危险命令黑名单已落地;确认机制 + 文件边界白名单 v0.2 |
| 长会话上下文膨胀 | 中 | compaction(v0.2)按手动→阈值渐进落地 |
| 多平台验证成本 | 低~中 | ✅ 已闭环:bash 含 Git for Windows / WSL 探测链,环境差异经断言修复与 WSL 转发器排除(2026-08-14) |
| 编排自研(第二步) | 中(暂缓) | 三未决问题回答后启动;消息归约先行 spike |

**结论**:核心依赖全部成熟稳定,架构文档已定稿,编排层契约(AgentLoopConfig / run_agent_loop / AgentSession)已落地(自研版)。**技术风险可控,无颠覆性难点。**

### 9.2 市场定位可行性

见 §3.5:正面竞争不可行;差异化定位(可替换、可测试、可嵌入的工程底座)可行,吃国内生态与自研/教育市场。

### 9.3 资源投入可行性

**投入估算(单人全栈,按既有架构蓝图)**:

| 阶段 | 范围 | 预估工作量 | 交付物 |
|---|---|---|---|
| v0.1 | tools + core + session + container + 模型层自研(ModelRuntime) | ✅ 已落地 | headless CLI 可对话、可调用 read/write/edit/bash、事件流可订阅 |
| v0.2 | store + manager + compaction + 安全确认 + undo + AGENTS.md + TUI 恢复 + 解耦测试恢复 | 2–3 周(较 v0.1 报告上调,新增 TUI 恢复/undo/AGENTS.md) | 会话可恢复、可切换、可压缩、可回滚 |
| v0.3 | Skills + MCP + token 用量透明 + 会话树 | 阶段 1~4 已落地，阶段 6 验收已完成 | 扩展工具、用量可见、会话树导航 |

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
| R1 | 技术 | ~~编排自研中断 langgraph 平台部署入口~~ | 中 | 高 | ✅ 已消解(2026-08-14 定案:平台部署非刚需,F-24 改写为 HTTP/事件订阅入口 F-27);**2026-08-22 Web/HTTP 入口移出 v0.3(E12),远期按需重估** |
| R2 | 技术 | 自研消息归约(工具结果按 tool_call_id 归属)写错 → 工具链断裂 | 中 | 高 | ✅ 已消解(2026-08-14 spike 5 场景双跑 diff ALL PASS) |
| R3 | 技术 | Windows 平台 bash 行为差异(路径显示、PIPESTATUS) | 高 | 低~中 | ✅ 已闭环;2026-08-27 Windows 全量 **938 passed**;Ubuntu/macOS 由 CI 矩阵持续验证 |
| R4 | 质量 | 解耦扫描测试缺失,分层泄漏回归无法自动发现 | 中 | 中 | ✅ 已重写恢复(2026-08-14,AST 扫描 70+ 断言) |
| R5 | 质量 | 文档与代码漂移(219 vs 304 vs 204 测试、TUI 状态、provider 数) | 已发生 | 中 | 以本文档为基线,版本更新时同步校准(附录 B 机制) |
| R6 | 市场 | 无自研模型,受第三方 API 制约;头部放开多供应商则差异化压缩 | 中 | 中 | 强化"工程底座"定位;成本透明(F-22)对冲信任赤字 |
| R7 | 进度 | 单人维护可持续性、社区获取不足 | 高 | 中 | 开发者指南(接入新 provider/工具)、文档与示例投入 |
| R8 | 安全 | 工具误操作风险(rm/越界写) | 中 | 高 | 黑名单已落地;v0.2 确认环 + 文件边界白名单(上线前必须) |
| R9 | 体验 | 无 TUI,交互形态倒退(相对竞品) | 确定 | 中 | ✅ TUI 已恢复 MVP(2026-08-13,E9~E11,`app/tui/`);斜杠命令/模糊补全拆 v0.2 |

---

## 12. 验收标准

### 12.1 全局验收基线(每个版本发布前必须满足)

1. **测试无失败**:`uv run pytest -q` 全量通过（2026-08-27 Windows 复核 **938 passed**）;核心编排层零网络、零密钥(`FakeClient`)可跑通全量;
2. **解耦判据**:解耦扫描测试强制校验跨层 import 仅出现在 `app/container.py` / `app/main.py`(2026-08-14 已重写恢复);
3. **离线可体验**:无任何 API Key 时以 `fake` provider 完整跑通"对话→工具调用→事件流"闭环;
4. **配置隔离**:全部配置类 `extra="ignore"`,防回归测试通过;
5. **安全底线**:密钥不出现在日志/事件流/输出;危险命令拒绝带审计信息。

### 12.2 v0.2 验收(F-11~F-17b)

- ✅ 会话持久化:`SessionStore`(JSONL 树形)重启恢复历史会话;`SessionManager` 支持 create/switch/fork/dispose;
- ✅ 上下文压缩:手动触发 + 阈值自动触发,压缩后对话语义不丢失(回归测试);
- ✅ 安全权限:bash/write 敏感操作默认确认,未确认不执行;文件访问默认限定工作区,越界需显式确认;
- ⚠️ 回滚 `/undo`:改写为 `/fork`(分支会话语义,见 F-15);
- ✅ AGENTS.md:全局→项目→子目录分层加载并注入系统提示词,越近优先级越高;
- ✅ TUI 增强:斜杠命令/模糊补全/选择器、Markdown 渲染与滚动交互已落地(T-44/T-45);`/login` 于 v0.3 追加;
- ✅ 解耦扫描测试恢复并通过(AST 扫描,70+ 断言)。

### 12.3 v0.3 验收(F-18~F-24)

- ✅ Skills 按需加载:`resources/skills/` 渐进式披露生效(2026-08-19 阶段 1 落地,590/590 基线);
- 📝 插件两阶段(注册→绑定)已移出 v0.3，待生态成熟后重估;
- ✅ MCP 外部工具接入(最小 `tools/list` / `tools/call` 协议面、命名空间化、分组预算与权限规则);
- 📝 轻量记忆已移出 v0.3，待跨会话记忆价值域扩大时重估;
- ✅ 成本透明:token 用量归一、会话级落库与 `/status` / CLI 可见；费用估算按范围调整移出;
- ✅ 分支会话 fork(v0.2)与会话树导航(v0.3)可用;Web/HTTP 入口(F-27)已于 2026-08-22 移出 v0.3(E12),远期按需重估。

### 12.4 远期验收(F-25~F-28)

- 多智能体协作原型;Automations 定时触发;Web/HTTP 订阅事件流。Windows 平台验证已闭环，后续仅需保持回归。

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
| FR-4.1~4.7 | 编排引擎 | P0/P2 | ✅ 已落地(自研版;F-04/05 形态变化见 §0.1) | R §3.1; A §5 | F-03~F-05 |
| FR-4.8 | 编排自研第二步 | P3 | ✅ **已落地**(2026-08-14) | B 全文 | — |
| FR-5.1~5.3 | AgentSession/总线/循环 | P0 | ✅(自研版:run_agent_loop 直接驱动) | R; A §5.3; C | F-06~F-08 |
| FR-5.4~5.6 | 持久化/Manager/压缩 | P1 | ✅ 已落地(v0.2,JSONL 树形) | R; A §5.4 | F-11~F-13 |
| FR-5.7 | 会话树/分叉 | P2 | ✅ fork 已落地;树导航 v0.3 | R | F-23 |
| FR-5.8~5.9 | abort / replace_config(新增) | P0 | ✅ | C | — |
| FR-5.10 | steer / followup | P1 | ✅ 已落地(v0.2) | A §5.3; B 收益2 | — |
| FR-6.1~6.5 | 可观测性与事件 | P0 | ✅(11 类事件;6.3 随 TUI 落地) | R; C | — |
| FR-7.1~7.4 | 扩展与部署 | P2 | 🔲/📝(7.1 ✅ Skills;7.3 改写为 F-27,2026-08-22 移出 v0.3 E12) | R; G §5 | F-18~F-24 |
| FR-8.1~8.4 | 安全与权限 | P0/P1 | ✅ 黑名单 + 确认环 + 文件边界已落地 | G §4.2 G7 | F-14 |

### A.2 非功能需求追踪

| 组 | 条目 | 状态要点 | 出处 |
|---|---|---|---|
| NFR-P1~P10 | 性能 | 设计保证 + 待实测(部分随 TUI 恢复生效) | R §4.1 |
| NFR-S1~S8 | 安全 | ✅ 黑名单/审计/确认环/文件边界全部落地(v0.2) | R §4.2 |
| NFR-U1~U8 | 可用性 | 0 配置/fake 已落地;TUI 相关随 TUI 落地生效 | R §4.3 |
| NFR-R1~R5 | 可靠性 | ✅ abort/steer/followup 落地;JSONL 持久化落地 | R §4.4 |
| NFR-M1~M6 | 可维护性 | ✅ 解耦扫描测试已重写恢复(2026-08-14,70+ 断言) | R §4.5; C |
| NFR-E1~E5 | 可扩展性 | 契约已落地;E4 事件流订阅已满足(F-27 入口 2026-08-22 移出 v0.3,E12) | R §4.6 |
| NFR-C1~C4 | 兼容性 | ✅ Windows bash 测试已修复(标记文件法,2026-08-13 fix-bash-test-assertions);2026-08-27 Windows 全量回归 938 passed，跨平台矩阵已配置 | R §4.7; C |
| NFR-O1~O3 | 可观测性 | 11 类事件已落地 | R §4.8; C |

---

## 附录 B:文档与代码一致性校准(2026-08-13 实测)

本附录记录四份文档与当前代码树之间的差异,作为后续版本更新时的对照基准。

### B.1 已确认差异清单

| # | 差异项 | requirements-analysis.md(v0.1, 08-10) | architecture.md(08-11) | GAP 分析(08-10) | 当前树实测(HEAD f0b29f2,2026-08-14) |
|---|---|---|---|---|---|
| 1 | 测试数量 | 219 全绿 | 304 全绿 | 219 全绿 | **336 项全绿**(08-13 曾 204 项:200 通过 + 4 项 bash 环境敏感失败,已由 fix-bash-test-assertions 修复——3 项 cwd 断言改标记文件法、1 项 PIPESTATUS 命令精简;08-14 TUI 修复、主流形态改造与 P2 死代码清理后曾 3 项 bash 失败,根因是 `_resolve_bash` 命中 WSL 转发器,已修复并补回归测试;含 v0.2 解耦扫描 70 项) |
| 2 | provider 数量 | 3(deepseek/openai/fake) | 6(+qwen/glm/kimi/minimax) | 3 | **7**(deepseek/openai/qwen/glm/kimi/minimax/fake,`PROVIDERS` 注册表确认) |
| 3 | TUI 状态 | ✅ 已落地(SessionAgentClient 流式渲染) | ✅ 已落地 | ✅ 已落地 | ✅ **已恢复为 MVP**(`app/tui/`:view/components/backend 端口 + textual 后端,`--tui` 进入;E9~E11);斜杠命令/模糊补全/选择器拆 v0.2 |
| 4 | 目录结构 | 顶层 `cli.py/container.py/config.py/model_pattern.py` + `tui/` | 同左 | 同左 | `app/` 包(main/config/container/composition)+ `app/tui/`;`ai/` 保留 model/catalog/transport/providers;顶层无 cli/container/config |
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

### B.3 2026-08-21 初审及 2026-08-24 后续复核(自研编排落地后)

| # | 差异项 | B.1 记录(08-14) | 2026-08-24 后续复核 |
|---|---|---|---|
| 1 | 测试数量 | 336 项全绿 | **938 passed**(2026-08-27 Windows 复核;2026-08-21 审计 12 条缺陷全部修复闭环,见 `docs/review/audit-2026-08-21.md` 与 v0.3 §6.5) |
| 5 | 事件类型 | 10 类 | **11 类**(新增 `confirmation_requested`,security-permissions) |
| 6 | 会话接口 | abort / replace_graph | `abort` / `steer` / `followup`;热切换改 `SessionManager.replace_config` |
| 7 | 模型客户端 | 自研,langchain-core/langgraph 保留于编排侧 | **langchain-core/langgraph 全部移除**(2026-08-14 自研编排;`ai/bridge/` 删除) |
| 9 | 解耦扫描测试 | 不在代码树 | ✅ **已重写恢复**(2026-08-14,AST 扫描 70+ 断言,带 anti-wargaming 守卫) |
| 11 | 工具数量 | 7 | **8**(新增 `skill` 技能寻址工具,v0.3 阶段 1) |
| — | 会话持久化 | 🔲 v0.2 线性 | ✅ **JSONL 树形已落地**(含 fork) |
| — | 安全确认环 | 🔲 v0.2 | ✅ 已落地(ApprovalPolicy + 三档分类器) |
| — | 平台部署 | `langgraph.json` 待设计 | ⚠️ 永久废弃,改写为 HTTP/事件订阅(F-27);**2026-08-22 移出 v0.3(E12),远期按需重估** |

---

*本文档合并自 docs/design/ 四份文档并经 2026-08-13 代码实测校准(2026-08-21 追加 §0.1 勘误与附录 B.3 复核);对原文的引用以编号(R/A/G/B/C)标注于附录 A。架构现状以 §0.1 勘误 + architecture.md(v0.3) 为准。*
