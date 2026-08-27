"""异步任务、客户端和其他可关闭资源的测试生命周期。"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def task_tracker() -> Callable[[asyncio.Task[Any]], asyncio.Task[Any]]:
    """跟踪后台任务,在 teardown 中取消并等待其结束。"""
    tasks: list[asyncio.Task[Any]] = []

    def track(task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        tasks.append(task)
        return task

    yield track

    for task in reversed(tasks):
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest_asyncio.fixture
async def async_resource_tracker() -> Callable[[Any], Any]:
    """跟踪 async/sync closeable 资源,按创建逆序释放。"""
    resources: list[Any] = []

    def track(resource: Any) -> Any:
        resources.append(resource)
        return resource

    yield track

    for resource in reversed(resources):
        close = getattr(resource, "aclose", None)
        if close is None:
            close = getattr(resource, "close", None)
        if not callable(close):
            continue
        result = close()
        if inspect.isawaitable(result):
            await result


@pytest.fixture
def resource_tracker() -> Callable[[Any], Any]:
    """跟踪 MCP client 等同步资源,在 teardown 中可靠关闭。"""
    resources: list[Any] = []

    def track(resource: Any) -> Any:
        resources.append(resource)
        return resource

    yield track

    for resource in reversed(resources):
        close = getattr(resource, "close", None)
        if callable(close):
            close()
