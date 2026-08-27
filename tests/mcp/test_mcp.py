"""tests/mcp/test_mcp.py:MCP 客户端测试(配置/客户端/适配/预算/装配,全离线)。

进程级测试用 ``mock_server.py``(手写最小 stdio JSON-RPC server,与 SDK
客户端互操作);配置与预算为纯函数直测。零网络、零真实外部服务。
"""

from __future__ import annotations

import json
import asyncio
import io
import sys
from pathlib import Path

import pytest

from codeagent.tools.mcp.adapter import McpArgs, McpTool
from codeagent.tools.mcp.budget import apply_budget, truncate_description
from codeagent.tools.mcp.client import McpServerClient, McpToolInfo
from codeagent.tools.mcp.config import McpServerSpec, parse_mcp_config
from codeagent.tools.mcp.loader import close_mcp_tools, load_mcp_tools

MOCK_SERVER = str(Path(__file__).parent / "mock_server.py")


def _spec(name: str = "mock") -> McpServerSpec:
    return McpServerSpec(name=name, command=sys.executable, args=(MOCK_SERVER,))


def test_mock_server_protocol_output_is_utf8(monkeypatch):
    """stdio JSON-RPC 输出不应受 Windows 控制台 cp1252 编码影响。"""
    from tests.mcp import mock_server

    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stdout)

    mock_server._send({"description": "回显文本"})

    assert raw.getvalue().decode("utf-8").endswith("\n")


# ── 配置解析 ─────────────────────────────────────────


def test_parse_mcp_config_missing_file(tmp_path):
    """配置文件缺失 → 空列表,不报错(无 MCP 是常态)。"""
    assert parse_mcp_config(tmp_path) == ([], [])


def test_parse_mcp_config_valid(tmp_path):
    """合法配置 → server 列表(name/command/args/env)。"""
    (tmp_path / "mcp.json").write_text(
        json.dumps({"servers": [{"name": "s1", "command": "npx", "args": ["-y", "x"]}]}),
        encoding="utf-8",
    )
    servers, diags = parse_mcp_config(tmp_path)
    assert len(servers) == 1
    assert servers[0].name == "s1" and servers[0].args == ("-y", "x")
    assert diags == []


def test_parse_mcp_config_bad_json(tmp_path):
    """JSON 解析失败 → 诊断 + 跳过。"""
    (tmp_path / "mcp.json").write_text("{broken", encoding="utf-8")
    servers, diags = parse_mcp_config(tmp_path)
    assert servers == []
    assert any(d.startswith("parse_failed") for d in diags)


def test_parse_mcp_config_invalid_entries(tmp_path):
    """非法条目逐条诊断 + 跳过,合法条目照常。"""
    (tmp_path / "mcp.json").write_text(
        json.dumps({
            "servers": [
                {"name": "ok", "command": "echo"},
                {"name": "no-cmd"},
                {"command": "no-name"},
                {"name": "bad-args", "command": "x", "args": "nope"},
                "not-object",
            ]
        }),
        encoding="utf-8",
    )
    servers, diags = parse_mcp_config(tmp_path)
    assert [s.name for s in servers] == ["ok"]
    assert len(diags) == 4


# ── 客户端(真实子进程 + SDK)─────────────────────────


def test_client_discovers_and_calls_tools(resource_tracker):
    """tools/list 发现 + call_tool 往返(进程级互操作)。"""
    client = resource_tracker(McpServerClient("mock", _spec()))
    client.start(timeout=10)
    assert {t.name for t in client.tools} == {"echo", "fail"}
    text = client.call_tool("echo", {"text": "hello"})
    assert text == "echo:hello"


def test_client_error_tool_raises():
    """server 标记错误 → 抛异常(适配层转错误结果)。"""
    client = McpServerClient("mock", _spec())
    client.start(timeout=10)
    with pytest.raises(RuntimeError, match="boom"):
        client.call_tool("fail", {})
    client.close()


def test_client_start_timeout():
    """启动超时(无响应 server)→ TimeoutError,装配方可诊断跳过。"""
    spec = McpServerSpec(name="stuck", command=sys.executable, args=("-c", "import time; time.sleep(30)"))
    client = McpServerClient("stuck", spec)
    with pytest.raises(TimeoutError):
        client.start(timeout=0.5)
    client.close()


# ── 适配器 ──────────────────────────────────────────


def test_mcp_tool_name_prefix_and_invoke():
    """命名 {server}:{tool};Args extra=allow 透传;结果文本回填。"""
    client = McpServerClient("mock", _spec())
    client.start(timeout=10)
    tool = McpTool(client, client.tools[0])
    assert tool.name == "mcp__mock__echo"
    assert tool.description == "回显文本"
    assert tool.invoke(McpArgs(text="hi")) == "echo:hi"
    client.close()


def test_mcp_tool_marks_truncated_output():
    class LargeClient(_FakeClient):
        def call_tool(self, name, arguments, timeout=None):
            return "\n".join(f"line-{i}" for i in range(2500))

    tool = McpTool(LargeClient("srv"), McpToolInfo("large", "", {}))

    result = tool.invoke(McpArgs())

    assert "[输出已截断]" in result


def test_mcp_tool_error_result():
    """server 错误 → 调用抛错(循环层转为错误结果,不炸会话)。"""
    client = McpServerClient("mock", _spec())
    client.start(timeout=10)
    fail = McpTool(client, next(t for t in client.tools if t.name == "fail"))
    with pytest.raises(RuntimeError):
        fail.invoke(McpArgs())
    client.close()


async def test_mcp_tool_async_cancellation_releases_call():
    """The async adapter propagates cancellation to the server bridge."""

    class AsyncClient:
        name = "async"

        def __init__(self):
            self.started = asyncio.Event()
            self.cancelled = False

        async def acall_tool(self, name, arguments, timeout=None):
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    async def scenario():
        client = AsyncClient()
        tool = McpTool(client, McpToolInfo("wait", "", {}))
        task = asyncio.create_task(tool.ainvoke(McpArgs()))
        await client.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return client

    client = await (scenario())
    assert client.cancelled is True


def test_close_mcp_tools_idempotent():
    """close_mcp_tools 按 client 去重、幂等。"""
    client = McpServerClient("mock", _spec())
    client.start(timeout=10)
    tools = [McpTool(client, info) for info in client.tools]
    close_mcp_tools(tools)
    close_mcp_tools(tools)  # 幂等
    assert client._thread is None or not client._thread.is_alive()


# ── 分组预算(纯函数)─────────────────────────────────


class _FakeClient:
    """适配器测试用假 client(不经协议)。"""

    def __init__(self, name: str) -> None:
        self.name = name

    def call_tool(self, name, arguments, timeout=None):
        return f"ok:{name}"


def _make_tool(name: str, description: str = "描述") -> McpTool:
    return McpTool(_FakeClient("srv"), McpToolInfo(name, description, {}))


def test_apply_budget_per_server_cap():
    """每 server 超限 → 裁尾部 + 裁剪诊断,不静默。"""
    by_server = {"srv": [_make_tool(f"t{i}") for i in range(20)]}
    kept, diags = apply_budget(by_server, per_server_cap=5)
    assert [t.name for t in kept] == [f"mcp__srv__t{i}" for i in range(5)]
    assert any("dropped" in d and "t19" in d for d in diags)


def test_apply_budget_global_cap():
    """总量超限 → 从末尾逆序释放 + 诊断。"""
    by_server = {
        "a": [_make_tool(f"a{i}") for i in range(3)],
        "b": [_make_tool(f"b{i}") for i in range(3)],
    }
    kept, diags = apply_budget(by_server, global_cap=4, per_server_cap=10)
    assert len(kept) == 4
    assert any("global" in d or "总量" in d for d in diags)


def test_apply_budget_description_truncated():
    """描述超长 → 截断并标记,工具仍可用。"""
    long_desc = "长" * 300
    kept, _ = apply_budget({"srv": [_make_tool("t", long_desc)]})
    assert "已截断" in kept[0].description
    assert len(kept[0].description) < 300


def test_truncate_description_short_kept():
    """短描述不截断。"""
    assert truncate_description("短描述") == "短描述"


# ── 装配(loader)─────────────────────────────────────


def test_load_mcp_tools_no_config(tmp_path):
    """无配置 → 空工具列表,无诊断。"""
    tools, diags = load_mcp_tools(tmp_path)
    assert tools == [] and diags == []


def test_load_mcp_tools_success(tmp_path):
    """合法配置 → 工具列表 + 可调用。"""
    (tmp_path / "mcp.json").write_text(
        json.dumps({"servers": [{"name": "mock", "command": sys.executable, "args": [MOCK_SERVER]}]}),
        encoding="utf-8",
    )
    tools, diags = load_mcp_tools(tmp_path)
    assert {t.name for t in tools} == {"mcp__mock__echo", "mcp__mock__fail"}
    assert diags == []
    echo = next(t for t in tools if t.name == "mcp__mock__echo")
    assert echo.invoke(McpArgs(text="x")) == "echo:x"
    close_mcp_tools(tools)


def test_load_mcp_tools_start_failure_skipped(tmp_path):
    """server 启动失败 → 诊断 + 跳过,其余 server 照常。"""
    (tmp_path / "mcp.json").write_text(
        json.dumps({
            "servers": [
                {"name": "bad", "command": sys.executable, "args": ["-c", "exit(1)"]},
                {"name": "mock", "command": sys.executable, "args": [MOCK_SERVER]},
            ]
        }),
        encoding="utf-8",
    )
    tools, diags = load_mcp_tools(tmp_path)
    assert {t.name for t in tools} == {"mcp__mock__echo", "mcp__mock__fail"}
    assert any("start_failed" in d and "bad" in d for d in diags)
    close_mcp_tools(tools)


# ── 权限规则(CodeBuddy 式三级)───────────────────────


def test_permissions_parse_from_config(tmp_path):
    """mcp.json permissions 段 → 三级规则;缺省/非法 → 空规则。"""
    (tmp_path / "mcp.json").write_text(
        json.dumps({
            "permissions": {
                "deny": ["mcp__db"],
                "ask": ["mcp__github", "mcp__github__delete_*"],
                "allow": ["mcp__github__read_issue"],
            }
        }),
        encoding="utf-8",
    )
    from codeagent.tools.mcp.config import parse_mcp_permissions

    rules = parse_mcp_permissions(tmp_path)
    assert "mcp__db" in rules.deny
    assert "mcp__github" in rules.ask
    assert rules.decide("mcp__db__query") == "deny"
    assert rules.decide("mcp__github__list_issues") == "ask"
    assert rules.decide("mcp__other__x") is None


def test_permissions_missing_config_empty():
    """无配置文件 → 空规则(默认全部放行)。"""
    import tempfile

    from codeagent.tools.mcp.config import parse_mcp_permissions

    with tempfile.TemporaryDirectory() as td:
        rules = parse_mcp_permissions(td)
    assert rules.deny == () and rules.ask == () and rules.allow == ()
    assert rules.decide("mcp__anything") is None


def test_classify_mcp_rules():
    """安全分类器:deny/ask 命中;未命中与无规则 → 默认放行。"""
    from codeagent.tools.security import classify_mcp
    from codeagent.tools.mcp.config import McpPermissionRules

    rules = McpPermissionRules(deny=("mcp__db",), ask=("mcp__github",))
    denied = classify_mcp("mcp__db__query", rules)
    assert denied.action == "deny"
    asked = classify_mcp("mcp__github__push", rules)
    assert asked.action == "ask"
    allowed = classify_mcp("mcp__other__x", rules)
    assert allowed.action == "allow"
    assert classify_mcp("mcp__any__x", None).action == "allow"


def test_policy_mcp_headless_deny(tmp_path, monkeypatch):
    """组合根策略:ask 规则在 headless(deny)下降级拒绝(fail closed)。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".codeagent").mkdir(exist_ok=True)
    (tmp_path / ".codeagent" / "mcp.json").write_text(
        json.dumps({"permissions": {"ask": ["mcp__github"]}}),
        encoding="utf-8",
    )
    from codeagent.app.container import _create_policy

    policy = _create_policy(approval_mode="deny")
    decision = policy.decide("mcp__github__push", {})
    assert decision.action == "deny"
    assert "headless" in decision.reason
    assert policy.decide("mcp__other__x", {}).action == "allow"
    interactive = _create_policy(approval_mode="interactive")
    assert interactive.decide("mcp__github__push", {}).action == "ask"
