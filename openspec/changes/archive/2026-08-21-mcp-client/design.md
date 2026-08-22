# MCP 客户端接入 — 设计

> 对应 v0.3 阶段 2(T-53~T-55,F-20)。探索期定案(2026-08-20):同步工具层 + 官方 SDK 线程桥(方案 C,对齐 Python 生态主流——langchain `run_in_executor` / openai-agents-python `asyncio.to_thread`);插件系统已移出(E5),MCP 是工具扩展唯一通道。

## 1. 核心架构:同步工具层 + 官方 SDK 线程桥

```
            工具层(同步,保持现状)                    MCP 侧(后台线程)
┌──────────────────────────────┐     ┌─────────────────────────────────┐
│ core/loop.py                  │     │ tools/mcp/client.py             │
│  _execute_tools (gather)      │     │  McpServerClient                │
│    └─ to_thread(tool.invoke)  │     │  ├─ 后台线程 + asyncio 事件循环  │
│         └─ McpTool._invoke    │────▶│  ├─ ClientSession(SDK)          │
│            run_coroutine_     │     │  │   ├─ StdioServerTransport    │
│            threadsafe(        │     │  │   └─ initialize/tools/list   │
│              call_tool).result│◀────│  └─ call_tool → 文本/错误        │
└──────────────────────────────┘     └─────────────────────────────────┘
```

- **为什么保持同步工具层**:Python agent 生态事实标准(openai-agents-python 对同步函数工具同样 `asyncio.to_thread`);AtomicTool 同步契约 + 离线直调测试全不动;`to_thread` 桥已在循环里,零迁移;
- **为什么用官方 SDK 而非手写**:协议正确性(版本协商/错误形状/通知/stdio 写锁)交给官方;250 行手写协议的自维护成本不值——桥 SDK 是 Python 主流验证过的模式;
- **每 server 一个后台线程 + 独立事件循环**:SDK 会话生命周期(initialize/通知/关停)全在循环内;`McpTool._invoke` 同步阻塞 `run_coroutine_threadsafe(...).result(timeout)`——超时由调用方 `wait_for` 与 `result(timeout)` 双保护;
- **并发**:并行工具调用 = 多个 to_thread 线程同时 `run_coroutine_threadsafe`——SDK 会话按 JSON-RPC id 匹配响应,stdio 写由 SDK 内部串行化,无需额外锁;
- **收尾**:组合根 dispose / `atexit` → `run_coroutine_threadsafe(session.aclose())` + 终止后台线程,防子进程泄漏。

## 2. 配置与信任(D3)

```json
// ~/.codeagent/mcp.json(用户级唯一配置源)
{
  "servers": [
    {"name": "github", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
    {"name": "db", "command": "python", "args": ["-m", "my_mcp_server"]}
  ]
}
```

- **只做用户级**:项目级 `.mcp.json` 是恶意向量(仓库引导启动任意外部进程)——比项目级技能(提示词注入)危险一个量级,明确不做;信任模型 = "用户显式配置即信任",安全分类器未知名工具默认 ALLOW 语义保持;
- 配置缺失/空 → 无 MCP 工具,装配正常;格式错误 → 诊断 + 跳过该文件。

## 3. 工具适配与命名(D4)

```
McpTool(AtomicTool):
  name        = "mcp__<server>__<tool>"  # mcp__ 命名空间(CC/CodeBuddy 共识),权限通配规则书写面
  Args        = BaseModel + extra="allow"   # 任意 JSON Schema 参数透传
  description = server 声明描述,预算阶段截断(≤200 字符)
  _invoke     = client.call_tool(name, args.model_dump())
                 → {content:[{type:text}]} 提取文本;isError → 错误结果
```

- **超时**:`run_coroutine_threadsafe(...).result(timeout)`——timeout 取会话 `tool_timeout`(不设则 SDK 默认);SDK 调用本身在后台循环,不阻塞事件循环;
- **输出截断**:server 返回大文本 → 按 `tools/shared/truncate.py` 既有设施截断(对齐 Claude `MAX_MCP_OUTPUT` 思路),防上下文爆炸;
- **崩溃语义**:调用时 server 已死 → SDK 抛错 → 单条错误结果回填,本轮其余工具照常;不自动重启(MVP)。

### 3.5 MCP 权限规则(主流修订,CodeBuddy 式三级)

```
~/.codeagent/mcp.json 增 permissions 段:
{"permissions": {"allow": [...], "ask": [...], "deny": [...]}}

规则粒度:全部(mcp__*) / server 级(mcp__github,mcp__github__*) / 工具级(mcp__github__get_issue)
优先级:deny > ask > allow;未命中 → 默认 allow(用户级配置即信任)
headless:ask 降级 deny(fail closed,既有 _Policy 逻辑自动生效)

实现:McpPermissionRules(纯函数,归一化匹配)经 _create_policy 注入
classify_tool(mcp_rules=...) → 循环 policy.decide 天然接住(ask → 确认环 / deny → 拒绝回填)
```

对齐依据(2026-08-20 实查):CodeBuddy 官方文档的三级规则 + 通配;
Claude 调用前询问;项目无 project 级 server,故无"首次连接审批"(CodeBuddy 只对
project scope 审批)——默认放行的信任模型与 CodeBuddy user scope 一致。

## 4. 分组预算(T-54,D5)

```
apply_budget(tools_by_server, global_cap=40, per_server_cap=15, desc_cap=200)
  → (kept: list[McpTool], diagnostics: list[str])
```

- 纯函数,离线可测;内建工具不参与(恒保留);
- 裁剪确定性:按 server 配置顺序 + 工具列表顺序,超限者裁掉并出诊断(`dropped: github:tool_x (per-server cap 15)`);
- 默认值可配置(常量),不学 Qwen 的硬限 2 连接(用户反噬教训:假"server down"、模型幻觉)——裁剪必须可见、可解释。

## 4A. `/mcp` 命令(主流修订,对齐 Claude `/mcp`)

`/mcp` 按 server 分组列出已加载 MCP 工具(工具名解析回 server)+ 装配诊断
(启动失败/裁剪)——server 维度视图;`/tools` 保持工具维度,`/status` 保持诊断区。

## 5. 分层与文件落点

```
tools/mcp/                 # 新子包;tools 层禁 core/session/ai/app,全部经 SDK/标准库
├── __init__.py            # 导出 load_mcp_tools
├── config.py              # parse_mcp_config(config_dir) -> list[McpServerSpec] | 诊断
├── client.py              # McpServerClient(后台线程+循环+SDK 会话+call_tool 同步桥)
├── adapter.py             # McpTool(AtomicTool 子类,{server}:{tool} 命名)
├── budget.py              # apply_budget 纯函数(global/per-server/desc 三上限)
└── loader.py              # load_mcp_tools(config_dir, tool_timeout=None)
                           #   -> (tools, diagnostics):解析→逐 server 启动→list→适配→预算

app/container.py           # create_agent_ports:tools = make_tools(...) + load_mcp_tools(CONFIG_DIR)
                           #   → MCP 工具追加到 AgentPorts.tools;收尾 dispose
app/config.py              # CONFIG_MCP_FILE = CONFIG_DIR / "mcp.json"(常量,可选)
pyproject.toml             # 新增 mcp 官方 SDK
```

装配时序:`load_mcp_tools` 在组合根装配时同步执行(server 启动 + initialize 阻塞至超时,如 10s/server);headless 单次也加载(用户配置了就是要用);懒加载留远期。

## 6. 测试策略(T-55)

- **mock server 两形态**:
  - SDK `InMemoryTransport` 脚本化(最稳,零进程)——同进程直连,断言 tools/list 与 call_tool 往返;
  - 脚本化 stdio 子进程(最小 mock server,`json` 逐行读写 stdin/stdout)——验证真实进程边界与后台线程桥;
- **断言点**:命名前缀 `{server}:{tool}`;成功/错误回填;超时保护;server 装配失败跳过 + 诊断;预算纯函数(40/15/200 边界,裁剪诊断);无配置文件 → 空工具列表;项目级配置不加载;MCP 工具出现在 `/tools` 列表与 `_cmd_tools`;
- **全量离线**:SDK 内存传输零网络;stdio mock 是本进程脚本;`uv run pytest` 全绿(基线 590 + 新增)。

## 7. 与后续阶段接缝

- **成本透明(阶段 3)**:MCP 工具调用无 token 成本,但工具结果进上下文占用量——usage 统计天然覆盖;
- **会话树(阶段 4)/Web(阶段 5)**:MCP 工具挂在共享 `AgentPorts.tools`,Web 会话接入自动继承;
- **插件系统(远期重估)**:插件"工具引用位" = MCP server 声明(Agent Plugins v1 的 mcp.json),本阶段落地后插件即薄包装。
