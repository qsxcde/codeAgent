## Context

See `proposal.md` for the motivation and scope. 当前 `src/codeagent/core` 已经完成若干行为层面的拆分，但实现仍以多个平铺模块存在；其中 `ports.py` 同时包含外部端口、上下文契约和编排配置，形成了不清晰的依赖方向。现有 `codeagent.core` 根包被 app、session、tools 和测试作为稳定公共 façade 使用，且工作区已经包含前一项 core 运行时重构的未提交修改。

本设计只调整物理路径和内部导入，不修改消息、事件、工具协议、会话格式或运行时语义。所有迁移都必须在当前工作树上增量完成，不能回退或覆盖已有修改。

## Goals / Non-Goals

**Goals:**

- 让每个 core 模块只落在一个可解释的职责子包中。
- 建立单向依赖：契约层不依赖上下文实现，编排层依赖领域服务，根包只负责公共导出。
- 保持 `from codeagent.core import ...` 的现有公共导出和对象身份不变。
- 删除旧的平铺内部模块路径，避免新旧路径长期并存。
- 用结构、导出和边界测试防止重新出现循环依赖或跨层导入。

**Non-Goals:**

- 不重新设计 `Agent` 的执行行为、工具协议或上下文预算算法。
- 不改变 `AgentLoopConfig`、消息和事件的字段、序列化形态或默认值。
- 不保留 `codeagent.core.context`、`codeagent.core.ports` 等旧内部模块作为兼容别名。
- 不新增第三方依赖，也不顺手重构 `app`、`session`、`ai` 或 `tools` 的职责。

## Decisions

### 1. 按职责建立六个子包，根目录只保留入口

目标结构如下：

```text
src/codeagent/core/
├── __init__.py                 # 稳定公共 re-export façade
├── agent.py                    # Agent 公共运行时外壳
├── contracts/
│   ├── __init__.py
│   ├── errors.py
│   ├── events.py
│   ├── messages.py
│   └── ports.py                # 外部实现需要满足的中立端口
├── context/
│   ├── __init__.py
│   ├── budget.py
│   ├── contracts.py            # 上下文准备、预算端口和工具元数据
│   ├── model.py                # AgentContext
│   └── preflight.py
├── model/
│   ├── __init__.py
│   └── request.py
├── execution/
│   ├── __init__.py
│   ├── cleanup.py
│   ├── result.py
│   ├── runtime.py
│   └── state.py
├── orchestration/
│   ├── __init__.py
│   ├── batch.py
│   ├── config.py               # AgentLoopConfig 与编排回调类型
│   ├── errors.py
│   ├── loop.py
│   ├── tool_call.py
│   └── turn.py
└── support/
    ├── __init__.py
    └── awaiting.py             # 同步/异步回调归一化辅助函数
```

`Agent` 和 `__init__.py` 是有意保留的根级入口；其余生产模块全部进入职责子包。`support` 只承载无领域状态的通用辅助逻辑，避免把 `awaiting.py` 伪装成协议或编排模块。

### 2. 采用显式文件迁移，并拆解原 `ports.py`

文件迁移关系如下：

| 旧路径 | 新路径 | 处理方式 |
| --- | --- | --- |
| `core/errors.py` | `core/contracts/errors.py` | 直接迁移 |
| `core/events.py` | `core/contracts/events.py` | 直接迁移 |
| `core/messages.py` | `core/contracts/messages.py` | 直接迁移 |
| `core/ports.py` | `core/contracts/ports.py` | 仅保留模型、工具、运行时和策略端口 |
| `core/context.py` | `core/context/model.py` | 直接迁移并更新端口导入 |
| `core/context_budget.py` | `core/context/budget.py` | 直接迁移并更新消息导入 |
| `core/context_preflight.py` | `core/context/preflight.py` | 直接迁移并更新预算导入 |
| `ports.py` 中的上下文类型 | `core/context/contracts.py` | 提取上下文准备、工具元数据和预算端口 |
| `ports.py` 中的 `AgentLoopConfig` | `core/orchestration/config.py` | 提取编排配置及相关回调类型 |
| `core/model_request.py` | `core/model/request.py` | 直接迁移 |
| `core/execution.py` | `core/execution/runtime.py` | 直接迁移 |
| `core/execution_cleanup.py` | `core/execution/cleanup.py` | 直接迁移 |
| `core/execution_result.py` | `core/execution/result.py` | 直接迁移 |
| `core/execution_state.py` | `core/execution/state.py` | 直接迁移 |
| `core/loop.py` | `core/orchestration/loop.py` | 直接迁移 |
| `core/loop_errors.py` | `core/orchestration/errors.py` | 直接迁移 |
| `core/turn.py` | `core/orchestration/turn.py` | 直接迁移 |
| `core/tool_batch.py` | `core/orchestration/batch.py` | 直接迁移 |
| `core/tool_result.py` | `core/orchestration/tool_call.py` | 直接迁移 |
| `core/awaiting.py` | `core/support/awaiting.py` | 直接迁移 |

拆分 `ports.py` 而不是让 `contracts.ports` 继续导入 `context`，是为了消除反向依赖。上下文契约可以依赖 `contracts.ports.AgentTool`，编排配置可以依赖上下文契约；契约层本身不再依赖预算实现或 preflight 配置。

### 3. 固定单向依赖并禁止通过根 façade 反向导入

模块间依赖方向固定为：

```text
contracts
   ↓
context ───────┐
   ↓           │
model          │
   ↓           │
execution      │
   ↓           │
orchestration ─┘
   ↓
agent
```

更具体地说：

- `contracts` 只依赖标准库和同层契约类型。
- `context` 依赖 `contracts`，不依赖 `model`、`execution` 或 `orchestration`。
- `model` 依赖 `contracts` 和 `context`。
- `execution` 依赖 `contracts`，必要时使用 `context` 的中立数据类型。
- `orchestration` 依赖 `contracts`、`context`、`model` 和 `execution`。
- `agent` 只组装 `orchestration` 的公开运行函数和配置。
- `core/__init__.py` 可以导入各子包公开符号，但任何子包内部不得导入 `codeagent.core` 根 façade。

所有子包的 `__init__.py` 保持最小化，不做跨子包的 eager re-export；公共符号统一由 `core/__init__.py` 显式导出。这样既避免包初始化期间的隐式循环，也让内部依赖能直接反映真实模块边界。

### 4. 保持公共 façade，明确移除内部兼容入口

先根据现有 `core/__init__.py` 建立名称到新模块的显式映射，再修改 app、session、tools、测试和文档中的内部导入。根包继续导出 `Agent`、消息、事件、端口、上下文预算和运行时 API，导出对象直接来自新路径，不能通过动态代理或旧模块注入实现。

迁移完成后，旧平铺 `.py` 文件必须不存在；测试显式断言旧路径不能被导入，并断言公共根导出仍与新模块对象相同。这个选择与 proposal 中的 breaking change 一致：公共入口稳定，内部模块路径不承诺兼容。

### 5. 以结构契约和分层检查保护重构

测试分为三类：

1. 包结构测试：检查目标子包和文件存在、旧平铺文件不存在、根 façade 导出不变。
2. 导入边界测试：扫描 core 生产文件的导入，拒绝 `config`、`ai`、`tools`、`session`，拒绝子包反向导入 `codeagent.core`，并验证核心模块可在干净导入顺序下加载。
3. 行为回归测试：复用现有 core、contract、session、app integration 测试，确认路径迁移没有改变执行、预算、事件和取消语义。

测试应优先在新结构的最小导入契约完成后再迁移实现，失败时按“结构 → 导入 → 行为”顺序定位。

## Risks / Trade-offs

- [内部导入遗漏] → 先以 `rg` 盘点所有 `codeagent.core.<old_module>` 引用，再由 Ruff、窄测试和完整测试共同覆盖；完成后对旧路径做负向导入检查。
- [拆分 `ports.py` 引入循环依赖] → 先把上下文契约和编排配置提取到各自模块，保持子包 `__init__.py` 不做 eager import，并执行多种导入顺序测试。
- [外部用户依赖旧内部路径] → proposal 明确这是 breaking change；公共 `codeagent.core` façade 不变，并在架构文档中记录迁移后的推荐路径。
- [工作区已有未提交改动被误覆盖] → 修改前后检查 `git status` 与相关 diff，只使用精确的文件迁移和补丁，不回退前一变更。
- [大规模重命名降低审查可读性] → 将纯路径迁移与 `ports.py` 的职责提取分开提交式步骤，保持每一步可运行并及时更新任务勾选状态。

## Migration Plan

1. 记录当前测试基线和工作区状态，确认前一 core 变更的文件保持不变。
2. 新建六个子包及最小 `__init__.py`，先添加结构和导入契约测试。
3. 迁移契约、上下文和 support 模块；从 `ports.py` 提取上下文契约与编排配置。
4. 迁移 model、execution 和 orchestration 模块，按依赖方向逐层更新内部导入。
5. 更新 `core/__init__.py`、仓内调用方、测试和文档，删除旧平铺模块。
6. 运行窄测试、分层测试、Ruff、`git diff --check`、完整测试、构建和 OpenSpec 校验。

回滚策略是恢复本次变更涉及的路径迁移和导入更新；不触碰工作区中前一变更的独立修改。由于不保留兼容别名，发布前必须完成全仓导入扫描和完整测试。
