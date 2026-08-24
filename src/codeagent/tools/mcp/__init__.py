"""MCP 客户端子包:配置解析 → server 客户端(后台线程桥)→ 工具适配 → 分组预算。

入口 ``load_mcp_tools(config_dir)`` 由组合根调用,产出追加到工具列表的
MCP 工具(``{server}:{tool}`` 命名)。全部离线可测:mock server 经 SDK
内存传输或脚本化 stdio 子进程注入。
"""

from codeagent.tools.mcp.loader import close_mcp_clients, close_mcp_tools, load_mcp_tools

__all__ = ["close_mcp_clients", "close_mcp_tools", "load_mcp_tools"]
