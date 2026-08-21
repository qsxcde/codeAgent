"""tests/mcp/mock_server.py:手写最小 stdio MCP server(测试夹具)。

按 MCP 协议最小面(JSON-RPC 2.0,换行分隔)实现 initialize / tools/list /
tools/call / ping——**刻意不用官方 SDK 的服务端**,从"另一侧"验证
客户端(SDK)与标准协议 framing 的互操作性;也是进程级测试的确定性夹具。

工具:
- ``echo``:返回 ``echo:{text}``;
- ``fail``:返回错误结果(``isError: true``);
- 未暴露工具名直接调用 → 错误结果。
"""

from __future__ import annotations

import json
import sys

TOOLS = [
    {
        "name": "echo",
        "description": "回显文本",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
        },
    },
    {
        "name": "fail",
        "description": "总是返回错误",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _reply(request: dict, result: dict | None = None, error: dict | None = None) -> None:
    message: dict = {"jsonrpc": "2.0", "id": request.get("id")}
    if error is not None:
        message["error"] = error
    else:
        message["result"] = result
    _send(message)


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = request.get("method")
        params = request.get("params") or {}
        if request.get("id") is None:
            continue  # notification(如 notifications/initialized)
        if method == "initialize":
            version = params.get("protocolVersion", "2024-11-05")
            _reply(request, {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mock", "version": "1.0"},
            })
        elif method == "tools/list":
            _reply(request, {"tools": TOOLS})
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if name == "echo":
                _reply(request, {
                    "content": [{"type": "text", "text": f"echo:{arguments.get('text', '')}"}],
                })
            elif name == "fail":
                _reply(request, {
                    "content": [{"type": "text", "text": "boom"}],
                    "isError": True,
                })
            else:
                _reply(request, {
                    "content": [{"type": "text", "text": f"未知工具: {name}"}],
                    "isError": True,
                })
        elif method == "ping":
            _reply(request, {})
        else:
            _reply(request, error={"code": -32601, "message": f"method not found: {method}"})


if __name__ == "__main__":
    main()
