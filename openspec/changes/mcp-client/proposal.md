# MCP 客户端接入(F-20)

## Why

v0.3 阶段 2(T-53~T-55,F-20):接入 MCP(Model Context Protocol)作为**外部工具通道**——插件系统已移出(E5),工具扩展的唯一通道就是 MCP。MCP 是 2026 年 agent 生态的事实标准(Claude/Codex/Qwen Code 全部支持,生态 4000+ server),codeagent 需要它来获得外部工具能力(数据库、GitHub、浏览器等),这是生态护城河(G10)的关键一块。

## What Changes

- **新增依赖**:官方 `mcp` Python SDK(Anthropic 维护,async-first)——协议正确性(版本协商/错误形状/通知)交给官方,不手写 JSON-RPC
- **同步工具层保持**(Python 生态主流,与 langchain `run_in_executor`、openai-agents-python `asyncio.to_thread` 同构):MCP 客户端运行在**每 server 一个后台线程 + 独立事件循环**中,`McpTool.invoke`(同步)经 `run_coroutine_threadsafe(...).result(timeout)` 桥接
- **配置**:`~/.codeagent/mcp.json`(用户级唯一配置源 = 信任边界;项目级 `.mcp.json` **不做**——仓库引导启动任意外部进程是恶意向量,比项目级技能危险一个量级)
- **`tools/mcp/` 子包**:`client.py`(McpServerClient:后台线程 + initialize/tools/list/call_tool 同步桥)、`adapter.py`(McpTool:name = `{server}:{tool}`,Args extra=allow)、`config.py`(mcp.json 解析)、`budget.py`(分组预算纯函数)、`loader.py`(`load_mcp_tools(config_dir)` 装配入口)
- **工具命名**:`mcp__<server>__<tool>`(对齐 Claude Code / CodeBuddy 共识;统一 `mcp__` 命名空间为权限通配规则提供书写面)
- **权限规则**:CodeBuddy 式三级 **deny/ask/allow** + 通配(`mcp__github` server 级 / `mcp__github__tool` 工具级 / `mcp__*` 全部),优先级 deny > ask > allow;未命中默认放行(用户级配置即信任);headless 下 ask 降级 deny(fail closed,既有模式)
- **分组预算**(T-54):global 40 / per-server 15 / 描述 200 字符截断;裁剪出诊断,不静默丢弃(Qwen 2 连接上限的用户反噬教训)
- **失败语义**:装配时 server 起不来/initialize 失败 → 诊断 + 跳过该 server,不中断装配;调用时崩溃 → 单条错误结果,不自动重启
- **可见性**:`/tools` 自动覆盖 MCP 工具名;server 诊断进 `/status`;**`/mcp` 命令**按 server 分组列出工具 + 诊断(对齐 Claude `/mcp` 的 server 维度视图)
- **输出截断**:MCP 大文本返回按既有 truncate 设施截断(对齐 Claude `MAX_MCP_OUTPUT` 思路)

## Capabilities

### New Capabilities

- `mcp`: MCP 客户端——server 配置与信任边界、后台线程桥、工具接入(命名/适配/预算)、失败语义与可见性

### Modified Capabilities

- `tools`: 「工具注册与装配」需求变更——`make_tools` 产出的工具列表经组合根追加 MCP 工具(内建工具恒保留);工具命名含 `{server}:{tool}` 形态

## Impact

- **依赖**:新增 `mcp` 官方 SDK(连带 anyio 等;httpx/pydantic 已有)
- **新增文件**:`tools/mcp/`(client/config/adapter/budget/loader 五模块);`tests/mcp/` 测试镜像
- **修改文件**:`app/container.py`(`create_agent_ports` 调 `load_mcp_tools(CONFIG_DIR)` 并入工具表 + 收尾 dispose);`app/config.py`(`CONFIG_MCP_FILE` 常量,可选)
- **不改动**:core 循环、session 层、安全分类器(未知工具默认 ALLOW 语义保持)
- **测试**:mock MCP server(SDK 内存传输或脚本化 stdio 子进程);预算纯函数断言;装配诊断断言;全部离线零网络
