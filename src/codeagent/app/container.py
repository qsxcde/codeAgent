"""应用组合根兼容入口。

实现按职责位于 :mod:`codeagent.app.composition`，本模块只保留稳定导入
路径和兼容符号。跨层装配实现不得反向导入本 façade。
"""

from __future__ import annotations

from codeagent.app.composition.model_factory import (
    ChatModelPort,
    LlmSummarizer,
    _resolve_context_window,
    _resolve_model_effort,
    _to_chat_message,
    _usage_of,
)
from codeagent.app.composition.policy_factory import _create_policy
from codeagent.app.composition.prompt_builder import (
    _build_system_prompt,
    _load_skills,
    _workspace,
    agents_sources,
    skills_view,
)
from codeagent.app.composition.runtime_factory import (
    AgentRuntime,
    _LazyPorts,
    _LazySummarizer,
    _RUNTIMES_BY_PORTS,
    close_runtime_for_ports,
    create_agent_ports,
    create_agent_runtime,
    runtime_for_ports,
)
from codeagent.app.composition.session_factory import (
    create_agent_session,
    create_session_manager,
)
from codeagent.app.composition.tool_factory import _load_mcp_tools, create_tools
from codeagent.app.composition.tui_factory import (
    TuiAssembler,
    _configured_providers,
    _resolve_candidates,
    _resolve_footer_info,
    create_tui_app,
)

__all__ = [
    "AgentRuntime",
    "ChatModelPort",
    "LlmSummarizer",
    "TuiAssembler",
    "create_agent_ports",
    "create_agent_runtime",
    "create_agent_session",
    "create_session_manager",
    "create_tools",
    "create_tui_app",
    "runtime_for_ports",
    "close_runtime_for_ports",
    "agents_sources",
    "skills_view",
]
