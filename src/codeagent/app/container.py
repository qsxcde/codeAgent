"""应用组合根导出入口。

实现按职责位于 :mod:`codeagent.app.composition`，本模块只导出组合根 API。
跨层装配实现不得反向导入本 façade。
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
    _LazyConfig,
    _LazySummarizer,
    _RUNTIMES_BY_CONFIG,
    close_runtime_for_config,
    close_runtime_for_config_async,
    create_agent_config,
    create_agent_runtime,
    runtime_for_config,
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
    "create_agent_config",
    "create_agent_runtime",
    "create_agent_session",
    "create_session_manager",
    "create_tools",
    "create_tui_app",
    "runtime_for_config",
    "close_runtime_for_config",
    "close_runtime_for_config_async",
    "agents_sources",
    "skills_view",
]
