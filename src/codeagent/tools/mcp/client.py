"""tools/mcp/client.py:MCP server 客户端——后台线程 + 事件循环 + 官方 SDK 会话。

设计(design mcp-client §1):同步工具层保持(Python 生态主流),官方 ``mcp``
SDK 的异步 ``ClientSession`` 运行在**每 server 一个后台线程 + 独立事件循环**
中;``call_tool`` 经 ``run_coroutine_threadsafe(...).result(timeout)`` 同步桥
接回工具层(与 langchain ``run_in_executor`` / openai-agents-python
``asyncio.to_thread`` 同构)。

- ``start(timeout)``:等待 initialize + tools/list 完成(失败抛错,装配方诊断跳过);
- ``call_tool``:并发安全——SDK 会话按 JSON-RPC id 匹配响应,stdio 写由 SDK
  内部串行化,无需额外锁;
- ``close()``:置停止事件 → 会话/传输随 ``async with`` 收尾 → 线程 join,
  防子进程泄漏。

分层约束:tools 层,仅标准库 + mcp SDK,不 import core/session/ai/app。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

__all__ = ["McpCallResult", "McpServerClient", "McpToolInfo"]

#: 调用兜底超时(SDK 无显式超时时防无限挂起;会话级 tool_timeout 可覆盖)。
DEFAULT_CALL_TIMEOUT = 60.0


@dataclass(frozen=True)
class McpCallResult:
    """Text projection plus explicit facts for non-text MCP content."""

    text: str
    metadata: dict[str, Any]


class McpToolInfo:
    """SDK ``tools/list`` 返回的工具元数据(适配器构造 McpTool 用)。"""

    def __init__(self, name: str, description: str, input_schema: dict[str, Any]) -> None:
        self.name = name
        self.description = description or ""
        self.input_schema = input_schema or {}


class McpServerClient:
    """一个 MCP server 的客户端壳(后台线程 + SDK 会话)。"""

    def __init__(self, server_name: str, params: StdioServerParameters) -> None:
        self._name = server_name
        self._params = params
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session: ClientSession | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._failed: Exception | None = None
        #: 停止信号必须是与后台循环同 loop 的 asyncio.Event(threading.Event
        #: 不可 await);close 经 call_soon_threadsafe 置位。
        self._stop: asyncio.Event | None = None
        self._tools: list[McpToolInfo] = []
        self._active_calls: set[concurrent.futures.Future[Any]] = set()
        self._closed = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def tools(self) -> list[McpToolInfo]:
        """已发现的工具元数据(``start`` 成功后可用)。"""
        return list(self._tools)

    def start(self, timeout: float = 10.0) -> None:
        """启动后台线程并等待 initialize + tools/list(同步阻塞)。

        失败抛异常(装配方诊断 + 跳过该 server);已启动则直接返回。
        """
        if self._thread is not None:
            return
        self._closed = False
        self._thread = threading.Thread(
            target=self._run_loop, name=f"mcp-{self._name}", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            self.close()
            raise TimeoutError(f"MCP server '{self._name}' 初始化超时({timeout}s)")
        if self._failed is not None:
            failure = self._failed
            self.close()
            raise failure

    def call_tool(self, name: str, arguments: dict[str, Any] | None, timeout: float | None = None) -> str:
        """同步调用 server 工具(桥接回后台事件循环),返回文本结果。

        - timeout 缺省 ``DEFAULT_CALL_TIMEOUT``(防无限挂起);会话级
          tool_timeout 可覆盖;
        - server 已死 / 调用失败 → 抛异常(适配器转为错误结果回填)。
        """
        loop = self._loop
        session = self._session
        if loop is None or session is None:
            raise RuntimeError(f"MCP server '{self._name}' 未初始化")
        timeout = timeout if timeout is not None else DEFAULT_CALL_TIMEOUT
        future = self.submit_tool(name, arguments, timeout)
        try:
            result = future.result(timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError(f"MCP 工具 {self._name}:{name} 调用超时({timeout}s)")
        extracted = _extract_result(result)
        text = extracted.text
        if getattr(result, "is_error", False):
            raise RuntimeError(f"MCP 工具 {self._name}:{name} 返回错误: {text}")
        return text

    def call_tool_result(
        self, name: str, arguments: dict[str, Any] | None, timeout: float | None = None
    ) -> McpCallResult:
        """Return a structured MCP result for the concrete tool adapter."""
        loop = self._loop
        session = self._session
        if loop is None or session is None:
            raise RuntimeError(f"MCP server '{self._name}' 未初始化")
        timeout = timeout if timeout is not None else DEFAULT_CALL_TIMEOUT
        future = self.submit_tool(name, arguments, timeout)
        try:
            result = future.result(timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError(f"MCP 工具 {self._name}:{name} 调用超时({timeout}s)")
        extracted = _extract_result(result)
        if getattr(result, "is_error", False):
            raise RuntimeError(f"MCP 工具 {self._name}:{name} 返回错误: {extracted.text}")
        return extracted

    def submit_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        timeout: float | None = None,
    ) -> concurrent.futures.Future[Any]:
        """Submit a tracked coroutine to the server loop."""
        loop = self._loop
        session = self._session
        if loop is None or session is None or loop.is_closed() or self._closed:
            raise RuntimeError(f"MCP server '{self._name}' 未初始化")
        call_timeout = timeout if timeout is not None else DEFAULT_CALL_TIMEOUT
        future = asyncio.run_coroutine_threadsafe(
            session.call_tool(name, arguments, read_timeout_seconds=call_timeout), loop
        )
        self._active_calls.add(future)
        future.add_done_callback(self._active_calls.discard)
        return future

    async def acall_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        timeout: float | None = None,
    ) -> str:
        """Async bridge that cancels the background Future on task cancel."""
        future = self.submit_tool(name, arguments, timeout)
        wrapped = asyncio.wrap_future(future)
        try:
            result = await wrapped
        except asyncio.CancelledError:
            future.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(wrapped), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, concurrent.futures.CancelledError):
                pass
            raise
        extracted = _extract_result(result)
        text = extracted.text
        if getattr(result, "is_error", False):
            raise RuntimeError(f"MCP 工具 {self._name}:{name} 返回错误: {text}")
        return text

    async def acall_tool_result(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        timeout: float | None = None,
    ) -> McpCallResult:
        """Async structured counterpart used by ``McpTool.ainvoke``."""
        future = self.submit_tool(name, arguments, timeout)
        wrapped = asyncio.wrap_future(future)
        try:
            result = await wrapped
        except asyncio.CancelledError:
            future.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(wrapped), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, concurrent.futures.CancelledError):
                pass
            raise
        extracted = _extract_result(result)
        if getattr(result, "is_error", False):
            raise RuntimeError(f"MCP 工具 {self._name}:{name} 返回错误: {extracted.text}")
        return extracted

    def close(self) -> None:
        """停止后台循环并等待线程退出(会话/子进程随 async with 收尾)。

        幂等:循环已关闭(启动失败/重复调用)时安全跳过。
        """
        self._closed = True
        for future in list(self._active_calls):
            future.cancel()
        if self._stop is not None and self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._stop.set)
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        self._thread = None
        self._session = None
        self._stop = None

    # -- 内部 ---------------------------------------------------------------

    def _run_loop(self) -> None:
        """后台线程入口:生命周期内持有一个事件循环与 SDK 会话。"""
        try:
            asyncio.run(self._serve())
        except Exception as exc:  # noqa: BLE001 - 装配失败由调用方诊断
            self._failed = exc
        finally:
            self._ready.set()

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        params = StdioServerParameters(
            command=self._params.command,
            args=list(self._params.args),
            env=self._params.env,
        )
        async with stdio_client(params) as (read_stream, write_stream):
            session = ClientSession(read_stream, write_stream)
            async with session:
                await session.initialize()
                listed = await session.list_tools()
                self._session = session
                self._tools = [
                    McpToolInfo(t.name, t.description, dict(t.input_schema))
                    for t in listed.tools
                ]
                self._ready.set()
                await self._stop.wait()


def _extract_text(result: Any) -> str:
    """兼容旧调用方的文本投影。"""
    return _extract_result(result).text


def _extract_result(result: Any) -> McpCallResult:
    """Extract text and explicit diagnostics for every MCP content block."""
    parts: list[str] = []
    unsupported: list[dict[str, Any]] = []
    for block in getattr(result, "content", []) or []:
        if isinstance(block, TextContent):
            parts.append(block.text)
        else:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
                continue
            block_type = str(getattr(block, "type", type(block).__name__))
            reference = getattr(block, "uri", None) or getattr(block, "url", None)
            unsupported.append(
                {
                    "type": block_type,
                    "reference": str(reference) if reference else None,
                    "mime_type": getattr(block, "mimeType", None)
                    or getattr(block, "mime_type", None),
                }
            )
    text = "\n".join(parts).strip()
    if unsupported:
        suffix = "\n".join(
            f"[MCP 内容不支持直接显示: {item['type']}"
            + (f",引用={item['reference']}" if item["reference"] else "")
            + "]"
            for item in unsupported
        )
        text = f"{text}\n{suffix}" if text else suffix
    return McpCallResult(
        text,
        {
            "completeness": "unsupported" if unsupported else "complete",
            "unsupported_blocks": unsupported,
            "artifact_ref": next(
                (item["reference"] for item in unsupported if item["reference"]),
                None,
            ),
            "source": "mcp",
        },
    )
