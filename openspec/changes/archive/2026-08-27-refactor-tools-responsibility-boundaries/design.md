## Context

当前 tools 层已经分为 atomic、mcp、shared 和安全策略，但职责边界仍不均衡。`atomic/bash.py` 同时包含安全检测、Shell 探测、进程生命周期、同步/异步执行和结果处理；`security.py` 同时处理 Bash、文件、MCP 三类策略，并依赖 Bash 的私有函数；`mcp/config.py` 同时解析 Server 启动配置和权限配置。

本变更必须保持 tools 层的分层约束：不依赖 core、session、ai；保持 `AtomicTool`、工具 schema、结构化结果、确认策略和 MCP 装配行为不变。具体动机见 `proposal.md`。

### 内建原子工具边界

当前对模型暴露的内建原子工具固定为八个：`read`、`write`、`edit`、`grep`、`find`、`ls`、`bash`、`skill`。原子工具的定义是一个稳定的工具名称、参数 schema 和结果契约，不要求内部实现只有一个系统调用。

其中 `read`、`write`、`edit` 属于文件修改/读取类，`grep`、`find`、`ls` 属于文件查询类，`bash` 属于进程执行类，`skill` 属于注入注册表查询类。`AtomicTool` 是工具协议基类，`McpTool` 虽然技术上实现该协议，但属于外部 MCP 适配器；`registry.py`、`security`、`execution`、`shared` 和 `mcp/client.py` 属于基础设施，不是内建原子工具。

## Goals / Non-Goals

**Goals:**

- 建立 atomic tool、执行基础设施、安全策略和 MCP 配置之间的单向依赖。
- 让 Bash 安全规则可以被安全分类器复用，而不依赖 `atomic/bash.py` 的私有实现。
- 统一同步与异步进程执行的公共生命周期语义，保留超时、取消、进程树清理和临时输出捕获行为。
- 保留当前公开模块入口和对外可观察行为，使本次变更可以分阶段落地。
- 将测试重点从私有函数位置迁移到稳定的行为和职责模块。
- 为八个内建原子工具建立明确的跨平台行为基线，统一路径、编码、换行、glob、遍历和错误语义。
- 将 Bash 的平台差异限制在执行后端，Linux/macOS 共用 POSIX 策略，Windows 使用显式 Git Bash 策略。

**Non-Goals:**

- 不改变 Bash 的安全规则、确认策略、输出格式、退出码语义或跨平台清理语义。
- 不重写 `grep.py`、`find.py`、简单原子工具或 MCP SDK transport；仅补充其跨平台验证和必要的公共抽象。
- 不引入新的沙箱、权限模型、第三方依赖或新的工具能力。
- 不在本变更中删除公开兼容入口；只迁移内部私有依赖，旧入口的删除需要单独变更确认。

## Decisions

### 1. 将 Bash 保留为原子工具门面

`atomic/bash.py` 只保留 `BashArgs`、`BashInvocationResult`、`BashTool` 以及参数校验、策略调用、执行结果映射和工具结果格式化。它不再实现 Shell 分词、危险命令递归分析、解释器发现或进程树管理。

目标调用链为：

```text
BashTool
  → security.bash_rules       # 硬拒绝检测
  → execution.shell            # bash 解析与受控环境
  → execution.process          # 同步/异步进程生命周期
  → BashInvocationResult       # 工具层结果映射
```

相比把所有逻辑继续留在 Bash 文件中，此方案允许替换执行器或安全规则而不改变工具 schema。相比把 Bash 拆成多个用户可见工具，保留单一 `bash` 入口可以维持原子工具契约。

### 2. 抽取进程执行基础设施

新增 `tools/execution/`，至少包含：

```text
tools/execution/
├── __init__.py
├── process.py       # ProcessRequest/ProcessResult、同步/异步等待、超时、取消、输出捕获
├── shell.py         # Shell 后端选择、bash 路径发现和受控环境
├── posix.py         # Linux/macOS 进程组、信号和清理实现
└── windows.py       # Git Bash、Windows 进程组、taskkill 和清理状态
```

`process.py` 统一同步和异步执行的公共步骤：创建输出临时文件、启动进程、等待、超时/取消后清理、读取并解码 stdout/stderr、清理临时文件。平台差异集中在 `posix.py` 和 `windows.py` 的进程启动参数、信号与 tree kill 实现中，调用方只接收结构化原始执行结果。

Linux 与 macOS 共用 POSIX backend；macOS 不假设系统 Bash 支持现代 Bash 特性，Shell 命令只使用约定的 Bash 兼容语法或由 resolver 选择可用 Bash。Windows 默认选择真实 Git Bash/MSYS Bash，跳过 `System32/bash.exe` 和 `WindowsApps/bash.exe` 这类 WSL 转发器；WSL 只有在未来提供显式 backend 选择时才启用，不作为隐式 fallback。Windows 的 `taskkill /T` 无法证明所有 MSYS 后台孙进程已停止，必须保留 `cleanup_uncertain` 状态。

保留 Bash 特有的退出码语义和面向模型的输出格式在 `atomic/bash.py`，因为 `grep` 退出码 1 是否成功以及最终文本格式属于 Bash 工具契约，而不是通用进程执行器行为。

### 3. 抽取 Bash 安全规则并消除反向依赖

新增 `tools/security/` 包：

```text
tools/security/
├── __init__.py       # 重新导出现有公开分类入口
├── decision.py       # SecurityDecision 和 allow/ask/deny 常量
├── bash_rules.py     # DANGEROUS_PATTERNS、Shell 分词、嵌套命令和 rm 语义检测
├── filesystem.py     # within_workspace、classify_file
├── mcp.py            # classify_mcp
└── classifier.py     # classify_bash、classify_tool 及统一分发
```

`atomic/bash.py` 和 `security/classifier.py` 共同依赖 `security/bash_rules.py`。安全包不再从 atomic 工具导入私有函数。

`security/__init__.py` 继续导出当前 `security.py` 的公开名称，例如 `SecurityDecision`、`classify_bash`、`classify_file`、`classify_mcp` 和 `classify_tool`，因此组合根的策略装配无需改变。`BashTool` 当前显式导出的 `DANGEROUS_PATTERNS` 也保留为规则模块的公开引用；私有辅助函数不作为稳定接口保留。

### 4. 分离 MCP Server 配置和权限配置

在现有 `tools/mcp/` 下新增：

```text
tools/mcp/
├── server_config.py   # McpServerSpec、parse_mcp_config
├── permissions.py     # McpPermissionRules、parse_mcp_permissions
├── config.py          # 现有入口的集中导出，避免调用方立即改路径
├── client.py
├── adapter.py
├── loader.py
└── budget.py
```

Server 配置只被 loader 使用，权限配置只被策略装配使用。`config.py` 保留为薄导出层，不继续承载解析实现。这样可以先迁移内部依赖，再在未来单独评估是否删除旧入口。

### 5. 测试按职责迁移

- Bash 工具测试继续覆盖完整工具行为：执行、输出、超时、取消、cwd、环境和结构化结果。
- Bash 安全规则测试迁移到 `security/bash_rules.py` 或通过 `classify_bash` 验证，不再要求 `atomic/bash.py` 持有实现函数。
- 进程执行测试覆盖同步/异步公共生命周期及 Windows/Unix 分支；临时文件清理和清理不确定状态保持可断言。
- 文件边界、MCP 权限和 MCP 配置测试分别归入对应模块。
- 保留对外入口测试，确保 `tools.security`、`tools.mcp.config`、`tools.atomic` 的既有公开导入继续工作。

### 6. 内建原子工具的跨平台语义

文件类原子工具不通过 Shell 实现，统一依赖 `FsOps` 和路径解析能力：

- 路径输入以注入的 `cwd` 为基准，内部使用 `Path`，对外输出统一使用正斜杠相对路径；Windows 驱动器、UNC 路径和 Unix 路径不得通过字符串拼接混淆。
- `read`、`grep`、`find` 使用 UTF-8/非 UTF-8 和二进制的统一处理；`write` 统一写入 LF；`edit` 保留原文件 BOM 和 CRLF 约定；权限失败返回结构化可诊断错误。
- `grep`、`find` 的 glob 和相对路径匹配在不同平台保持相同分隔符语义；`ls` 的隐藏项定义保持现有的点前缀规则，不额外依赖 Windows 文件属性；排序和截断结果保持确定性。
- 遍历工具对 Unix 符号链接和 Windows junction 的行为必须明确并通过测试覆盖，不能因平台默认遍历策略不同而静默扩大搜索范围。
- `skill` 只读取组合根注入的内存注册表，不创建平台专用实现；MCP 工具保持外部工具语义不变，只有 server 启动命令、stdio、环境变量和配置路径交由平台适配。

BashTool 不直接判断 `os.name` 或拼接平台命令；它只依赖 Shell/Process backend。Windows 中的 `cmd.exe /c`、`powershell -Command` 等嵌套包装器不由 Bash 规则完整解析，应由独立的 Windows 安全规则识别并按确认策略处理。

相比为每个原子工具实现三套代码，本方案选择统一的文件工具语义和少量平台后端：文件工具共享路径/文件系统抽象，只有进程与 Shell 生命周期保留平台差异。

### 7. 迁移顺序和依赖方向

先新增并测试规则/执行模块，再让旧门面调用新实现，之后迁移组合根和测试导入，最后删除重复实现。迁移期间禁止新模块反向依赖 `atomic/bash.py`，并通过 import 边界测试防止 execution/security/mcp 反向依赖 core、session 或 ai。

## Risks / Trade-offs

- [导入路径变化] 将 `security.py` 转为 package 可能影响直接导入行为 → 由 `security/__init__.py` 保留现有公开导出，并先运行导入回归测试。
- [安全规则漂移] 移动 Bash 规则时可能改变边界命令判定 → 先冻结现有行为测试，迁移后逐条比较 deny/ask/allow 结果。
- [进程清理回归] 同步/异步执行器抽取可能改变取消时序或 Windows 清理状态 → 使用现有树级击杀、取消和 cleanup_uncertain 测试作为验收基线。
- [临时文件泄漏] 公共执行器异常路径可能遗漏临时文件删除 → 将 stdout/stderr 文件生命周期封装在单一上下文中，并增加异常、超时、取消后的清理断言。
- [过度拆分] 新增过多小模块会增加导航成本 → 只拆本变更已确认的四类边界；grep/find、MCP client 和简单原子工具维持现状。
- [测试依赖私有实现] 旧测试直接导入 Bash 私有函数 → 将这些测试迁移到规则模块或公开分类入口，不为旧私有路径增加兼容层。

## Migration Plan

1. 创建 execution 和 security 子模块，复制并单元验证现有行为。
2. 将 `BashTool` 接入新的安全规则和进程执行器，删除 Bash 内重复实现。
3. 将 `security.py` 迁移为 `security` package，更新组合根和测试导入，保留公开导出。
4. 拆分 MCP Server 配置与权限配置，保留 `mcp.config` 导出入口。
5. 运行 tools 相关窄测试、导入边界检查和规格验证；确认后再运行全量测试。
6. 若迁移失败，回滚新增模块接入点即可恢复原实现；不需要修改 session 数据或用户配置。
