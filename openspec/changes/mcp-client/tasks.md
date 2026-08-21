# MCP 客户端接入 — 任务分解

> 对应 v0.3 阶段 2(T-53~T-55,F-20)。设计见 `design.md`,行为契约见 `specs/`。

## 1. 依赖与配置

- [x] 1.1 新增依赖官方 `mcp` SDK(`pyproject.toml`,`uv sync`;确认离线测试不受影响)
- [x] 1.2 `tools/mcp/config.py`:`parse_mcp_config(config_dir)` 解析 `mcp.json`(servers: name/command/args/env;缺省 env 空),文件缺失/空 → 空列表;格式错误 → 诊断 + 跳过;`app/config.py` 补 `CONFIG_MCP_FILE` 常量

## 2. 客户端与适配(T-53)

- [x] 2.1 `tools/mcp/client.py`:`McpServerClient`——后台线程 + `asyncio` 事件循环 + SDK `ClientSession`(stdio transport);`start()`(同步等待 initialize + tools/list,超时如 10s,失败返回诊断);`call_tool(name, args)` 同步桥(`run_coroutine_threadsafe(...).result(timeout)`);`close()`(aclose + 线程收尾)
- [x] 2.2 `tools/mcp/adapter.py`:`McpTool(AtomicTool)`——name = `{server}:{tool}`,Args = `extra="allow"` BaseModel,`_invoke` 调 `call_tool`,文本/错误回填,大输出按既有 truncate 截断
- [x] 2.3 `tools/mcp/loader.py`:`load_mcp_tools(config_dir, tool_timeout=None) -> (tools, diagnostics)`——解析 → 逐 server 启动(client.start 失败 → 诊断 + 跳过,不中断)→ 适配 → 预算;`McpServerSpec` 数据类

## 3. 分组预算(T-54)

- [x] 3.1 `tools/mcp/budget.py`:`apply_budget(tools_by_server, global_cap=40, per_server_cap=15, desc_cap=200) -> (kept, diagnostics)` 纯函数:内建不参与;超限确定性裁剪 + `dropped` 诊断;描述截断标记

## 4. 组合根接线

- [x] 4.1 `app/container.py`:`create_agent_ports` 中 `tools = make_tools(...) + load_mcp_tools(CONFIG_DIR)` 的 MCP 部分追加(内建恒保留);收尾注册 dispose(`session.aclose()` 逐 server,`atexit` 兜底)
- [x] 4.2 诊断可见性:复用 `skills_view` 同款模式——MCP 诊断并入 `/status` 展示(`_cmd_status` 增 MCP 区;`/tools` 天然覆盖 MCP 工具名)

## 5. 测试与收尾(T-55)

- [x] 5.1 mock server 双形态:`InMemoryTransport` 脚本化(零进程,最稳)+ 脚本化 stdio 子进程(最小 JSON-RPC server,验证真实进程边界与线程桥)
- [x] 5.2 `tests/mcp/` 测试:命名前缀、成功/错误回填、超时、装配失败跳过 + 诊断、无配置空列表、项目级配置不加载、`apply_budget` 边界(40/15/200)与裁剪诊断
- [x] 5.3 组合根/TUI 测试:create_agent_ports 装配 MCP 工具(注入内存 config_dir)、`/tools` 列表含 `{server}:{tool}`、`/status` MCP 诊断区
- [x] 5.4 全量回归:`uv run pytest` 全绿(基线 590/590 + 新增,零网络零密钥);`tests/test_decoupling.py` 覆盖 `tools/mcp/`(tools 层禁 core/session/ai/app)


## 6. 主流对齐修订(2026-08-20,实查 CC/CodeBuddy/Codex/Qwen 后定案)

- [x] 6.1 命名对齐:`mcp__<server>__<tool>`(adapter 前缀 + 既有测试更新)
- [x] 6.2 权限模型:`McpPermissionRules`(deny/ask/allow + 通配,deny>ask>allow,未命中放行)+ `parse_mcp_permissions`(mcp.json permissions 段)+ `classify_mcp`(security.py)+ `_create_policy` 注入(headless ask→deny 既有逻辑自动生效)
- [x] 6.3 `/mcp` 命令:commands.py 注册 + view.py `_cmd_mcp`(按 server 分组列出工具 + 诊断)
- [x] 6.4 测试:权限规则解析/匹配语义/分类器/headless 降级;`/mcp` 分组展示;命名更新回归
