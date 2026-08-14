"""组合根:跨层 import 只发生在这里(自研编排版,2026-08-14)。

装配链:``create_llm``(ai 层 ChatClient)→ ``ChatModelPort`` 适配为 core
模型端口 → 与 ``make_tools`` 工具列表、可选的 ``SessionStore`` 组装成
``AgentPorts`` → ``AgentSession`` 事件壳。langgraph 桥接层已删除,
适配(Message 互转 / usage 归一)全部收敛在本文件。
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from codeagent.ai.protocol.messages import ChatMessage, ToolCall as AiToolCall
from codeagent.core.messages import Message, ToolCall
from codeagent.core.ports import AgentPorts, ModelResponse, StreamEvent


def create_tools(cfg: Any = None) -> list[Any]:
    """工具层接线:产出自研原子工具列表。"""
    from codeagent.tools.registry import make_tools

    return make_tools(cfg)


# -- 模型端口适配 ---------------------------------------------------------


def _to_chat_message(m: Message) -> ChatMessage:
    """core Message → ai 层 ChatMessage(OpenAI 形状,经组合根适配)。"""
    if m.role == "tool":
        return ChatMessage(role="tool", content=m.content, tool_call_id=m.tool_call_id)
    if m.role == "assistant":
        return ChatMessage(
            role="assistant",
            content=m.content,
            tool_calls=[
                AiToolCall(
                    id=tc.id,
                    name=tc.name,
                    arguments=json.dumps(tc.args, ensure_ascii=False),
                )
                for tc in m.tool_calls
            ],
        )
    return ChatMessage(role="user", content=m.content)


def _usage_of(usage: dict[str, Any] | None) -> dict[str, int] | None:
    """usage 归一为 core 形状;兼容 OpenAI 口径(prompt/completion_tokens)。"""
    if not usage:
        return None
    input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    output_tokens = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    details = usage.get("output_token_details") or {}
    reasoning = details.get("reasoning") or usage.get("reasoning_tokens") or 0
    return {
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "reasoning_tokens": int(reasoning),
    }


class ChatModelPort:
    """把 ai 层 ``ChatClient`` 适配为 core ``ModelPort``(组合根唯一适配处)。

    流式事件逐项透传(thinking / content / tool_call_arg / usage / finish);
    工具参数为 JSON 字符串分片,由 core 循环累积组装。
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    @property
    def model_id(self) -> str:
        return self._client.model_id

    def stream(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        return self._stream(messages, tools)

    async def _stream(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        chat = [_to_chat_message(m) for m in messages]
        async for ev in self._client.stream(chat, tools):
            yield StreamEvent(
                type=ev.type,
                text=ev.text,
                tool_index=ev.tool_index,
                arg_delta=ev.arg_delta,
                tool_name=ev.tool_name,
                tool_id=ev.tool_id,
                finish_reason=ev.finish_reason,
                usage=_usage_of(ev.usage),
            )

    async def generate(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> ModelResponse:
        chat = [_to_chat_message(m) for m in messages]
        resp = await self._client.generate(chat, tools)
        calls: list[ToolCall] = []
        for tc in resp.tool_calls:
            try:
                args = json.loads(tc.arguments) if tc.arguments else {}
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc.id, name=tc.name, args=args))
        return ModelResponse(
            content=resp.content,
            tool_calls=calls,
            usage=_usage_of(resp.usage),
            finish_reason=resp.finish_reason,
            model=resp.model,
        )


# -- 装配 -----------------------------------------------------------------


def create_agent_ports(
    cfg: Any = None,
    *,
    registry: Any = None,
    store: Any = None,
    reasoning_effort: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> AgentPorts:
    """组合根:装配自研编排端口(模型端口 + 工具 + 可选会话存储)。"""
    from codeagent.ai.factory import create_llm

    client = create_llm(
        cfg=cfg,
        registry=registry,
        reasoning_effort=reasoning_effort,
        provider=provider,
        model=model,
    )
    return AgentPorts(
        model=ChatModelPort(client),
        tools=create_tools(cfg),
        store=store,
    )


def create_agent_session(
    cfg: Any = None,
    *,
    registry: Any = None,
    store: Any = None,
    session_id: str | None = None,
    reasoning_effort: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    recursion_limit: int | None = None,
    tool_timeout: float | None = None,
) -> Any:
    """组合根:创建有状态会话壳(CLI / TUI 入口)。

    - ``store`` 缺省 None(一次性 headless 不持久化);注入 SessionStore
      后会话可恢复、可继续(v0.2 会话层);
    - ``session_id`` 缺省自动分配;注入既有 id 恢复既有会话;
    - ``recursion_limit`` / ``tool_timeout`` 可单会话覆盖。
    """
    from codeagent.session import AgentSession, EventBus

    ports = create_agent_ports(
        cfg,
        registry=registry,
        store=store,
        reasoning_effort=reasoning_effort,
        provider=provider,
        model=model,
    )
    return AgentSession(
        ports,
        EventBus(),
        store=store,
        session_id=session_id,
        recursion_limit=recursion_limit or 50,
        tool_timeout=tool_timeout,
    )


def create_tui_app(
    cfg: Any = None,
    *,
    backend: Any = None,
    registry: Any = None,
    store: Any = None,
    reasoning_effort: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> Any:
    """组合根:TUI 装配——session + backend + footer 的 model/effort(design D5)。

    - footer 信息在装配时解析固化:``model:effort`` 内联后缀 > ``reasoning_effort``
      > provider 配置默认;model:effort 解析唯一引用 ``split_model_pattern``;
    - backend 缺省构造 TextualBackend(textual 延迟到此处 import,保持启动路径轻量);
    - TUI 层不读配置/不跨层:model/effort 作为显式依赖注入 ``TuiApp``。
    """
    from codeagent.app.tui.components import FooterInfo
    from codeagent.app.tui.view import TuiApp

    session = create_agent_session(
        cfg,
        registry=registry,
        store=store,
        reasoning_effort=reasoning_effort,
        provider=provider,
        model=model,
    )
    if backend is None:
        from codeagent.app.tui.textual_backend import TextualBackend

        backend = TextualBackend()
    return TuiApp(
        session,
        backend,
        footer=_resolve_footer_info(cfg, provider, model, reasoning_effort),
    )


def _resolve_footer_info(
    cfg: Any,
    provider: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> Any:
    """解析底部状态栏装配数据:``(model, effort, cwd)``(组合根专用,design D5)。

    与 ``create_llm`` 同优先级:``model:effort`` 内联后缀 > ``reasoning_effort``
    > provider 配置默认;默认 model 从 provider 的 ``*Config`` 类读取(其
    BaseSettings 字段即生效配置,含 env 覆盖);``cwd`` 取配置或当前工作目录。
    """
    import importlib
    from pathlib import Path

    from codeagent.ai.model_pattern import split_model_pattern
    from codeagent.ai.providers import PROVIDERS
    from codeagent.app.config import Settings
    from codeagent.app.tui.components import FooterInfo

    provider = provider or getattr(cfg, "llm_provider", None) or Settings().llm_provider
    base, inline = split_model_pattern(model) if model else (None, None)
    effort = inline or reasoning_effort
    model_id = base
    factory = PROVIDERS.get(provider)
    if factory is not None:
        module = importlib.import_module(factory.__module__)
        config_cls = next(
            (v for n, v in vars(module).items() if n.endswith("Config") and isinstance(v, type)),
            None,
        )
        if config_cls is not None:
            defaults = config_cls()
            if model_id is None:
                model_id = defaults.model
            if effort is None:
                effort = defaults.reasoning_effort
    cwd = getattr(cfg, "cwd", None) if cfg is not None else None
    cwd = str(Path(cwd or Path.cwd()).expanduser().resolve())
    return FooterInfo(model=model_id or "", effort=effort or "", cwd=cwd)
