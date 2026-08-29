"""执行前安全策略的组合根适配。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codeagent.core.contracts.ports import PolicyDecision


def _create_policy(cfg: Any = None, approval_mode: str = "deny") -> Any:
    """按形态装配执行前安全策略。"""
    from codeagent.app.config import CONFIG_DIR
    from codeagent.tools.mcp.permissions import parse_mcp_permissions
    from codeagent.tools.security import classify_tool

    workspace = getattr(cfg, "cwd", None) if cfg is not None else None
    workspace = str(Path(workspace or Path.cwd()).expanduser().resolve())
    mcp_rules = parse_mcp_permissions(CONFIG_DIR)

    def _target_exists(target: str) -> bool:
        path = Path(target)
        if not path.is_absolute():
            path = Path(workspace) / path
        return path.exists()

    class _Policy:
        def decide(self, tool_name: str, args: dict) -> PolicyDecision:
            decision = classify_tool(
                tool_name,
                args,
                workspace=workspace,
                cwd=workspace,
                exists=_target_exists,
                mcp_rules=mcp_rules,
            )
            if decision.action == "ask" and approval_mode == "deny":
                return PolicyDecision("deny", f"未确认不得执行(headless): {decision.reason}")
            if decision.action == "ask" and approval_mode == "allow":
                return PolicyDecision("allow", decision.reason)
            return PolicyDecision(decision.action, decision.reason, decision.warning)

    return _Policy()
