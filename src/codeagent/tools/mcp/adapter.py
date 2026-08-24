"""tools/mcp/adapter.py:MCP 工具适配器——SDK 工具元数据 → AtomicTool。

- 命名 ``mcp__<server>__<tool>``(对齐 Claude Code / CodeBuddy 共识,mcp spec
  「外部工具接入」):与内建工具不冲突;统一 ``mcp__`` 命名空间为权限通配
  规则提供书写面(CodeBuddy 式 ``mcp__github`` / ``mcp__*``);
- ``Args`` 为 ``extra="allow"`` 的通用模型:参数透传 server(其 JSON Schema
  由 server 自行校验),与循环的 ``Args(**call.args)`` 实例化契约兼容;
- 结果:文本回填;server 标记错误 / 调用异常 → 抛错(循环转为错误结果);
- 大输出按既有 ``truncate_head`` 截断(对齐 Claude ``MAX_MCP_OUTPUT`` 思路)。

分层约束:tools 层,不 import core/session/ai/app。
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from codeagent.tools.base import AtomicTool
from codeagent.tools.mcp.client import McpServerClient, McpToolInfo
from codeagent.tools.shared import DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES, truncate_head

__all__ = ["McpArgs", "McpTool"]

#: MCP 工具限定名前缀(权限规则与命名空间的统一书写面)。
MCP_NAME_PREFIX = "mcp__"


class McpArgs(BaseModel):
    """MCP 工具通用参数容器(任意 schema 透传,server 自行校验)。"""

    model_config = ConfigDict(extra="allow")


class McpTool(AtomicTool):
    """把 MCP server 的工具适配为原子工具(同步桥)。"""

    Args: ClassVar[type[BaseModel]] = McpArgs

    def __init__(
        self,
        client: McpServerClient,
        info: McpToolInfo,
        cwd=None,
        ops=None,
        timeout: float | None = None,
    ) -> None:
        super().__init__(cwd=cwd, ops=ops)
        self._client = client
        self._info = info
        self._timeout = timeout
        self.name = f"{MCP_NAME_PREFIX}{client.name}__{info.name}"
        self.description = info.description

    @property
    def server_name(self) -> str:
        """所属 server 名(工具名解析回 server,/mcp 视图分组用)。"""
        return self._client.name

    @property
    def client(self) -> McpServerClient:
        """所属 server 客户端(装配收尾关闭用)。"""
        return self._client

    def _invoke(self, args: McpArgs) -> str:
        text = self._client.call_tool(
            self._info.name, args.model_dump(exclude_none=True), timeout=self._timeout
        )
        truncated, info = truncate_head(
            text, max_lines=DEFAULT_MAX_LINES, max_bytes=DEFAULT_MAX_BYTES
        )
        if info.truncated:
            truncated += "\n[输出已截断]"
        return truncated

    async def ainvoke(self, args: McpArgs) -> str:
        """Cancellable async bridge used by the core execution runtime."""
        text = await self._client.acall_tool(
            self._info.name, args.model_dump(exclude_none=True), timeout=self._timeout
        )
        truncated, info = truncate_head(
            text, max_lines=DEFAULT_MAX_LINES, max_bytes=DEFAULT_MAX_BYTES
        )
        if info.truncated:
            truncated += "\n[输出已截断]"
        return truncated
