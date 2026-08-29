"""应用组合根导出入口。

实现按职责位于 :mod:`codeagent.app.composition`，本模块只导出组合根 API。
跨层装配实现不得反向导入本 façade。
"""

from __future__ import annotations

from codeagent.app.composition.model.factory import (
    ChatModelPort,
    LlmSummarizer,
    _resolve_context_window,
    _resolve_model_effort,
    _to_chat_message,
    _usage_of,
)
from codeagent.app.composition.policy import _create_policy
from codeagent.app.composition.prompts import (
    _build_system_prompt,
    _load_skills,
    _workspace,
    agents_sources,
    skills_view,
)
from codeagent.app.composition.runtime.factory import (
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
from codeagent.app.composition.runtime.extensions import (
    RuntimeExtensions,
    normalize_runtime_extensions,
)
from codeagent.app.composition.session.factory import (
    create_agent_session,
    create_session_manager,
)
from codeagent.app.composition.tools.factory import _load_mcp_tools, create_tools
from codeagent.app.composition.tui.factory import (
    TuiAssembler,
    _configured_providers,
    _resolve_candidates,
    _resolve_footer_info,
    create_tui_app,
)

__all__ = [
    "AgentRuntime",
    "RuntimeExtensions",
    "ChatModelPort",
    "LlmSummarizer",
    "TuiAssembler",
    "create_agent_config",
    "create_agent_runtime",
    "create_agent_session",
    "create_session_manager",
    "create_tools",
    "create_tui_app",
    "normalize_runtime_extensions",
    "runtime_for_config",
    "close_runtime_for_config",
    "close_runtime_for_config_async",
    "agents_sources",
    "skills_view",
]
