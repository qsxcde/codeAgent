"""AI 层中立模型类型与组合根工具适配测试。"""

import asyncio

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


def test_chat_model_port_converts_runtime_tools_before_model_call():
    client = FakeClient(response="ok")
    port = ChatModelPort(client)

    asyncio.run(port.generate([Message(role="user", content="读取")], [_Tool()]))

    assert client.bound_tools == ["read"]
    assert client.call_history[0]["bound_tools"] == ["read"]
