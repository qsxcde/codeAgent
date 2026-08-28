"""lifecycle behavior tests."""

from tests.app.container.fixtures import *  # noqa: F401,F403


def test_create_agent_config_injects_shared_tool_runtime():
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_agent_config
        from codeagent.core.execution import ToolExecutionRuntime

        config = create_agent_config()

        assert isinstance(config.tool_runtime, ToolExecutionRuntime)



async def test_agent_runtime_close_is_idempotent():
    """Composition-root runtime closes model resources exactly once."""
    from codeagent.app.container import AgentRuntime
    from codeagent.core.ports import AgentLoopConfig

    class Closable:
        model_id = "stub"

        def __init__(self):
            self.closed = 0

        async def aclose(self):
            self.closed += 1

    client = Closable()
    config = AgentLoopConfig(model=client, tools=[])
    runtime = AgentRuntime(config, None, client, [])
    await (runtime.close())
    await (runtime.close())
    assert client.closed == 1


async def test_agent_runtime_waits_for_sync_model_close():
    from codeagent.app.container import AgentRuntime
    from codeagent.core.ports import AgentLoopConfig

    class SyncClosable:
        def __init__(self):
            self.closed = 0

        def close(self):
            self.closed += 1

    client = SyncClosable()
    config = AgentLoopConfig(model=client, tools=[])
    runtime = AgentRuntime(config, None, client, [])

    await runtime.close()

    assert client.closed == 1


async def test_concurrent_agent_runtime_close_waits_for_one_shared_close():
    from codeagent.app.container import AgentRuntime
    from codeagent.core.ports import AgentLoopConfig

    started = asyncio.Event()
    release = asyncio.Event()

    class Closable:
        async def aclose(self):
            started.set()
            await release.wait()

    client = Closable()
    config = AgentLoopConfig(model=client, tools=[])
    runtime = AgentRuntime(config, None, client, [])
    first = asyncio.create_task(runtime.close())
    await started.wait()
    second = asyncio.create_task(runtime.close())
    await asyncio.sleep(0)

    assert not second.done()
    release.set()
    await asyncio.gather(first, second)


async def test_agent_runtime_closes_model_after_active_tool_is_cancelled():
    from codeagent.app.container import AgentRuntime
    from codeagent.core.execution import ToolExecutionRuntime
    from codeagent.core.ports import AgentLoopConfig

    started = asyncio.Event()
    order: list[str] = []

    class SlowTool:
        async def execute(self, tool_call_id, arguments, *, signal=None, on_update=None):
            started.set()
            await asyncio.Event().wait()

    class Closable:
        model_id = "stub"

        async def aclose(self):
            order.append("model_close")
            assert tool_runtime.active_operations == {}

    from codeagent.core.messages import ToolCall

    tool_runtime = ToolExecutionRuntime()
    tool_task = asyncio.create_task(
        tool_runtime.execute(SlowTool(), ToolCall("c1", "slow", {}), operation_id="op-1")
    )
    await started.wait()
    client = Closable()
    config = AgentLoopConfig(model=client, tools=[], tool_runtime=tool_runtime)
    runtime = AgentRuntime(config, None, client, [], tool_runtime)

    await runtime.close()

    assert order == ["model_close"]
    with pytest.raises(asyncio.CancelledError):
        await tool_task



async def test_agent_runtime_is_removed_from_registry_after_close():
    from codeagent.app.container import AgentRuntime, runtime_for_config
    from codeagent.core.ports import AgentLoopConfig

    class Closable:
        async def aclose(self):
            pass

    client = Closable()
    config = AgentLoopConfig(model=client, tools=[])
    runtime = AgentRuntime(config, None, client, [])
    from codeagent.app.composition.runtime_factory import _RUNTIMES_BY_CONFIG

    _RUNTIMES_BY_CONFIG[id(config)] = runtime
    await (runtime.close())
    assert runtime_for_config(config) is None



def test_rebuild_config_closes_realized_previous_runtime():
    """TUI 热切换在新端口构造成功后释放旧模型客户端。"""
    from codeagent.app.container import create_tui_app

    class ClosableClient:
        model_id = "fake-model"

        def __init__(self):
            self.closed = 0

        async def aclose(self):
            self.closed += 1

    clients: list[ClosableClient] = []

    def make_client(*args, **kwargs):
        client = ClosableClient()
        clients.append(client)
        return client

    with patch("codeagent.app.composition.model_selection.create_llm", side_effect=make_client):
        app = create_tui_app(provider="fake", backend=_StubBackend())
        # TUI 端口是 lazy 的，先访问共享工具以实现旧 runtime。
        _ = app._manager.tools
        assert len(clients) == 1
        app._rebuild_ports("fake", "fake-model:high", None)

    assert len(clients) == 2
    assert clients[0].closed == 1
    assert clients[1].closed == 0

