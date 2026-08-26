"""AI 层规范导入路径与旧兼容模块删除边界。"""

import importlib
import importlib.util

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
    from codeagent.app.composition.model_selection import (
        create_llm,
        get_available_providers,
        split_model_pattern,
    )

    assert all(
        value is not None
        for value in (
            ChatClient,
            ChatMessage,
            ChatResponse,
            Provider,
            StreamEvent,
            StreamEventType,
            ToolCall,
            ToolDefinition,
            Transport,
            SSEParser,
            create_llm,
            get_available_providers,
            split_model_pattern,
        )
    )


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
