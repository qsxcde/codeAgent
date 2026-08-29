"""Agent execution bridge for the session runtime controller."""

from __future__ import annotations

import uuid
import asyncio
from dataclasses import fields, replace
from typing import Any

from codeagent.core import Agent, AgentContext, ToolDecision
from codeagent.core.contracts.events import AgentEvent, EventType
from codeagent.core.contracts.messages import Message
from codeagent.core.contracts.ports import ApprovalPolicy
from codeagent.core.context.contracts import TransformContext
from codeagent.core.orchestration.config import AgentLoopConfig


class SessionExecutionMixin:
    """Create and run one core Agent without owning runtime state."""

    async def execute(
        self,
        config: AgentLoopConfig,
        text: str,
        *,
        history: list[Message],
        recursion_limit: int,
        tool_timeout: float | None,
        policy: ApprovalPolicy | None = None,
        transform_context: TransformContext | None = None,
    ) -> list[Message]:
        if self.active_run_id is None:
            raise RuntimeError("run must be started before execution")
        run_id = self.active_run_id
        self.current_task = asyncio.current_task()
        context = AgentContext(messages=list(history), tools=list(config.tools))
        pending_steer = self._take_pending_steer()
        agent_config = self._build_agent_config(
            config,
            run_id,
            tool_timeout,
            policy,
            transform_context,
        )
        self.agent = self._agent_factory(context, agent_config, recursion_limit)
        set_run_id = getattr(self.agent, "set_run_id", None)
        if callable(set_run_id):
            set_run_id(run_id)
        for steer in pending_steer:
            self.agent.steer(steer)
        self.agent.subscribe(lambda event: self._handle_event(event, run_id))
        try:
            return await self.agent.prompt(text)
        finally:
            for diagnostic in getattr(self.agent, "hook_diagnostics", ()):
                if diagnostic.session_id is None:
                    diagnostic = replace(diagnostic, session_id=self._session_id)
                self._hook_diagnostics.append(diagnostic)

    def _take_pending_steer(self) -> list[str]:
        pending: list[str] = []
        while not self.inject_queue.empty():
            pending.append(self.inject_queue.get_nowait())
        return pending

    def _build_agent_config(
        self,
        config: AgentLoopConfig,
        run_id: str,
        tool_timeout: float | None,
        policy: ApprovalPolicy | None,
        transform_context: TransformContext | None,
    ) -> AgentLoopConfig:
        values = {item.name: getattr(config, item.name) for item in fields(AgentLoopConfig)}
        values.update(
            {
                "tools": list(values["tools"]),
                "before_tool_call": self._before_tool_call_factory(run_id, policy),
                "tool_timeout": tool_timeout,
                "transform_context": transform_context or values["transform_context"],
            }
        )
        return AgentLoopConfig(**values)

    def _before_tool_call_factory(self, run_id: str, policy: ApprovalPolicy | None):
        async def before_tool_call(call, _context):
            if policy is None:
                return ToolDecision.allow()
            decision = policy.decide(call.name, call.args)
            if decision.action == "allow":
                return ToolDecision.allow()
            if decision.action == "deny":
                return ToolDecision.block(decision.reason)
            request_id = str(uuid.uuid4())
            self.confirmation.register(request_id, timeout=self._confirmation_timeout)
            self._handle_event(
                AgentEvent(
                    EventType.CONFIRMATION_REQUESTED,
                    payload={
                        "request_id": request_id,
                        "tool_call_id": call.id,
                        "tool": call.name,
                        "args": call.args,
                        "reason": decision.reason,
                    },
                ),
                run_id,
            )
            approved = await self.confirmation.wait(
                request_id,
                timeout=self._confirmation_timeout,
            )
            return ToolDecision.allow() if approved else ToolDecision.block("用户拒绝执行")

        return before_tool_call


__all__ = ["SessionExecutionMixin"]
