"""AI 层中立模型类型与组合根工具适配测试。"""

import asyncio
import json

from codeagent.ai.model.types import ToolDefinition
from codeagent.ai.providers.fake import FakeClient
from codeagent.app.composition.model_factory import ChatModelPort
from codeagent.core.messages import Message


class _Args:
    @classmethod
    def model_json_schema(cls):
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }


class _Tool:
    name = "read"
    description = "读取文件"
    args_schema = _Args


def test_tool_definition_is_provider_neutral():
    definition = ToolDefinition.from_tool(_Tool())

    assert definition.name == "read"
    assert definition.description == "读取文件"
    assert definition.parameters["required"] == ["path"]
    assert definition.to_api_dict()["function"]["name"] == "read"


async def test_chat_model_port_converts_runtime_tools_before_model_call():
    client = FakeClient(response="ok")
    port = ChatModelPort(client)

    await (port.generate([Message(role="user", content="读取")], [_Tool()]))

    assert client.bound_tools == ["read"]
    assert client.call_history[0]["bound_tools"] == ["read"]


async def test_chat_model_port_agent_stream_emits_parsed_tool_calls() -> None:
    client = FakeClient(
        steps=[
            {
                "tool_calls": [
                    {"id": "c1", "name": "read", "args": {"path": "a.py"}}
                ]
            }
        ]
    )
    port = ChatModelPort(client)

    async def collect():
        return [event async for event in port.stream_agent([Message(role="user", content="read")])]

    events = await (collect())
    tool = next(event for event in events if event.type == "tool_call")

    assert tool.tool_name == "read"
    assert tool.tool_id == "c1"
    assert tool.arguments == {"path": "a.py"}


async def test_chat_model_port_agent_stream_reports_invalid_tool_arguments() -> None:
    client = FakeClient(
        steps=[{"tool_calls": [{"id": "c1", "name": "read", "args_json": "{broken"}]}]
    )
    port = ChatModelPort(client)

    async def collect():
        return [event async for event in port.stream_agent([Message(role="user", content="read")])]

    events = await (collect())
    tool = next(event for event in events if event.type == "tool_call")

    assert tool.arguments == {}
    assert tool.argument_error


async def test_chat_model_port_injects_system_prompt_at_adapter_boundary() -> None:
    client = FakeClient(response="ok")
    port = ChatModelPort(client, system_prompt="you are concise")

    await (port.generate([Message(role="user", content="hello")]))

    assert client.call_history[0]["messages"][0] == {
        "role": "system",
        "content": "you are concise",
    }


def test_chat_model_port_describes_the_same_system_and_tool_request_budget():
    client = FakeClient(response="ok")
    port = ChatModelPort(
        client,
        system_prompt="you are concise",
        context_window=1_000,
        output_reserve=100,
        reserve_tokens=50,
        window_source="catalog",
    )

    snapshot = port.describe_context_budget(
        [Message(role="user", content="read the workspace")], [_Tool()]
    )

    assert snapshot.context_window == 1_000
    assert snapshot.output_reserve == 100
    assert snapshot.reserve_tokens == 50
    assert snapshot.system_prompt_tokens > 0
    assert snapshot.tool_definitions_tokens > 0
    assert snapshot.conversation_tokens > 0
    assert snapshot.status == "estimate"


def test_chat_model_port_marks_fallback_window_as_uncertain():
    snapshot = ChatModelPort(FakeClient(response="ok")).describe_context_budget(
        [Message(role="user", content="hello")], []
    )

    assert snapshot.window_source == "fallback"
    assert snapshot.status == "uncertain"
