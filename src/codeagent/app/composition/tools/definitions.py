"""Convert concrete application tools into provider-neutral AI definitions."""

from __future__ import annotations

from typing import Any

from codeagent.ai.model.types import ToolDefinition


class ToolDefinitionConversionError(ValueError):
    """A concrete tool could not expose a valid model-visible schema."""


def tool_definition_for(tool: Any) -> ToolDefinition:
    """Build a validated AI definition without leaking tool conventions into AI."""
    name = str(getattr(tool, "name", "") or getattr(tool, "__name__", ""))
    description = str(getattr(tool, "description", "") or "")
    schema_factory = getattr(getattr(tool, "args_schema", None), "model_json_schema", None)
    if not callable(schema_factory):
        return ToolDefinition(name=name, description=description)
    try:
        parameters = schema_factory()
    except Exception as exc:  # noqa: BLE001 - retain the tool/schema diagnostic
        raise ToolDefinitionConversionError(f"工具 {name or '<unknown>'} 的 schema 无法转换: {exc}") from exc
    if not isinstance(parameters, dict):
        raise ToolDefinitionConversionError(f"工具 {name or '<unknown>'} 的 schema 必须是对象")
    return ToolDefinition(name=name, description=description, parameters=parameters)
