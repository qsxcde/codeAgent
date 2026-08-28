"""AI 层规范导入路径与旧兼容模块删除边界。"""

import importlib
import importlib.util
from pathlib import Path

import pytest


def _find_spec_or_none(module_name: str):
    try:
        return importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        return None


def test_canonical_ai_imports_are_available():
    from codeagent.ai.model import (
        ChatClient,
        ChatMessage,
        ChatResponse,
        Provider,
        StreamEvent,
        StreamEventType,
        ToolCall,
        ToolDefinition,
        Transport,
    )
    from codeagent.ai.transport.sse import SSEParser
    from codeagent.app.composition.model.selection import (
        create_llm,
        get_available_providers,
        split_model_pattern,
    )
    assert all(
        value is not None
        for value in (
            ChatClient, ChatMessage, ChatResponse, Provider, StreamEvent,
            StreamEventType, ToolCall, ToolDefinition, Transport, SSEParser,
            create_llm, get_available_providers, split_model_pattern,
        )
    )


def test_ai_package_does_not_adapt_concrete_tool_schemas():
    ai_root = Path(__file__).resolve().parents[2] / "src" / "codeagent" / "ai"
    assert all("args_schema" not in path.read_text(encoding="utf-8") for path in ai_root.rglob("*.py"))


@pytest.mark.parametrize(
    "module_name",
    (
        "codeagent.ai.factory",
        "codeagent.ai.model_pattern",
        "codeagent.ai.protocol",
        "codeagent.ai.protocol.messages",
        "codeagent.ai.protocol.sse",
    ),
)
def test_legacy_ai_module_is_removed(module_name: str):
    assert _find_spec_or_none(module_name) is None
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)
