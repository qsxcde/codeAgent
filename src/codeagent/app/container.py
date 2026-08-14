"""组合根:跨层 import 只发生在这里。"""

from __future__ import annotations

from typing import Any


def create_tools(cfg: Any = None) -> list[Any]:
    """工具层接线:产出可 bind_tools 的 langchain BaseTool 列表。

    延迟导入 langchain(保持启动路径轻量)。
    """
    from codeagent.tools.registry import make_tools

    return make_tools(cfg)


def create_agent_graph(
    cfg: Any = None,
    *,
    registry: Any = None,
    checkpointer: Any = None,
    reasoning_effort: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> Any:
    """组合根:装配完整的 LangGraph ReAct 图。

    - ``llm = make_llm(cfg)`` → ``tools = make_tools(cfg)`` → ``bind_tools``
      → ``to_langchain_runnable`` 包装(langchain 桥接只在组合根发生);
    - ``ToolNode`` 包住工具执行器,默认注入内存 checkpointer(InMemorySaver)
      以实现会话维度 thread 累积(开箱即用可对话);
    - ``registry`` 注入已构建的模型注册表(不重复读 models.json,M11);
    - ``checkpointer`` 可注入共享实例(仅 effort 切换换图时保留 thread 上下文,H8);
    - ``reasoning_effort``/``provider``/``model`` 显式覆盖(运行时重建时传入)。
    - 返回编译后的图,供 ``create_agent_session`` 或 langgraph.json 使用。
    """
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.prebuilt import ToolNode

    from codeagent.ai.bridge.langchain import to_langchain_runnable
    from codeagent.ai.factory import create_llm
    from codeagent.core import AgentPorts, build_graph

    checkpointer = checkpointer or InMemorySaver()
    llm = create_llm(
        cfg=cfg,
        registry=registry,
        reasoning_effort=reasoning_effort,
        provider=provider,
        model=model,
    )
    tools = create_tools(cfg)
    bound = to_langchain_runnable(llm.bind_tools(tools))  # ★ 工具/模型唯一交汇行
    ports = AgentPorts(
        bound_model=bound,
        tool_executor=ToolNode(tools),
        checkpointer=checkpointer,
    )
    return build_graph(ports)


def create_agent_session(
    cfg: Any = None,
    *,
    registry: Any = None,
    checkpointer: Any = None,
    reasoning_effort: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> Any:
    """组合根:创建有状态会话壳(CLI 入口)。

    ``cfg.recursion_limit``(存在时)作为会话的循环上限,缺省用 AgentSession 默认值;
    ``registry``/``checkpointer``/``reasoning_effort``/``provider``/``model`` 透传给
    create_agent_graph(M11 注入 + H8 重建支持)。
    """
    from codeagent.session import AgentSession, EventBus

    graph = create_agent_graph(
        cfg,
        registry=registry,
        checkpointer=checkpointer,
        reasoning_effort=reasoning_effort,
        provider=provider,
        model=model,
    )
    recursion_limit = getattr(cfg, "recursion_limit", None) if cfg is not None else None
    if recursion_limit is not None:
        return AgentSession(graph, EventBus(), recursion_limit=recursion_limit)
    return AgentSession(graph, EventBus())


def create_tui_app(
    cfg: Any = None,
    *,
    backend: Any = None,
    registry: Any = None,
    reasoning_effort: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> Any:
    """组合根:TUI 装配——session + 后端 + footer 的 model/effort(design D5)。

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
        checkpointer=None,
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


