"""Budget views used by automatic session compaction."""

from __future__ import annotations

import inspect
from dataclasses import replace
from typing import Any

from codeagent.core.context.budget import (
    ContextBudgetInput,
    ContextBudgetSnapshot,
    estimate_context_budget,
)
from codeagent.core.contracts.messages import Message
from codeagent.core.model.request import neutral_tool_definitions
from codeagent.session.constants import SUMMARY_ID_PREFIX, SUMMARY_PREFIX


class SessionCompactionBudgetMixin:
    """Build model-visible budget snapshots without changing session state."""

    async def _next_request_budget(self) -> ContextBudgetSnapshot | None:
        """Estimate the model-visible context after the latest committed turn."""
        messages = list(self._history)
        if self._summary is not None and self._summary_entry_id:
            messages.insert(
                0,
                Message(
                    role="user",
                    content=SUMMARY_PREFIX + self._summary,
                    id=f"{SUMMARY_ID_PREFIX}{self._summary_entry_id}",
                    parent_id=self._summary_entry_id,
                ),
            )
        return await self._describe_context_budget(messages)

    async def _estimate_compaction_candidate(
        self,
        summary: str,
        kept: list[Message],
    ) -> ContextBudgetSnapshot:
        candidate = Message(
            role="user",
            content=SUMMARY_PREFIX + summary,
            id=f"{SUMMARY_ID_PREFIX}candidate",
        )
        result = await self._describe_context_budget([candidate, *kept])
        if result is None:
            raise ValueError("压缩候选预算不可用")
        return result

    async def _describe_context_budget(
        self,
        messages: list[Message],
    ) -> ContextBudgetSnapshot | None:
        provider = getattr(self._config, "context_budget", None)
        if provider is None:
            provider = getattr(self._config.model, "describe_context_budget", None)
        if provider is None:
            result = self._fallback_context_budget(messages)
        else:
            describe = getattr(provider, "describe_context_budget", None)
            if describe is None and callable(provider):
                describe = provider
            if describe is None:
                raise TypeError("context budget provider lacks describe_context_budget")
            result = describe(list(messages), list(getattr(self._config, "tools", [])))
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, ContextBudgetSnapshot):
                raise TypeError("context budget provider must return ContextBudgetSnapshot")
        if result is None:
            return None
        result = self._rebase_context_window(result)
        self._budget_state.record_estimate(result)
        return result

    def _fallback_context_budget(self, messages: list[Message]) -> ContextBudgetSnapshot:
        model = self._config.model
        output_reserve = getattr(model, "output_reserve", 0)
        reserve_tokens = getattr(model, "reserve_tokens", 0)
        output_reserve = min(max(0, int(output_reserve)), self._context_window)
        reserve_tokens = min(
            max(0, int(reserve_tokens)),
            max(0, self._context_window - output_reserve),
        )
        definitions = neutral_tool_definitions(list(getattr(self._config, "tools", [])))
        return estimate_context_budget(
            ContextBudgetInput(
                context_window=self._context_window,
                output_reserve=output_reserve,
                reserve_tokens=reserve_tokens,
                system_prompt=str(getattr(model, "_system_prompt", "") or ""),
                tool_definitions=tuple(definition.as_dict() for definition in definitions),
                messages=tuple(messages),
                window_source="fallback",
            )
        )

    def _rebase_context_window(
        self,
        snapshot: ContextBudgetSnapshot,
    ) -> ContextBudgetSnapshot:
        output_reserve = min(snapshot.output_reserve, self._context_window)
        reserve_tokens = min(
            snapshot.reserve_tokens,
            max(0, self._context_window - output_reserve),
        )
        input_budget = max(0, self._context_window - output_reserve - reserve_tokens)
        return replace(
            snapshot,
            context_window=self._context_window,
            output_reserve=output_reserve,
            reserve_tokens=reserve_tokens,
            input_budget=input_budget,
            headroom=input_budget - snapshot.input_tokens,
        )

    def _manual_compaction_budget(self, decision: Any) -> int:
        explicit = self._compaction_policy.compact_budget
        if explicit is not None:
            return explicit
        if decision is not None and decision.target_budget > 0:
            return decision.target_budget
        return max(1, round(self._context_window * 0.65))

    def _compaction_fingerprint(self, snapshot: ContextBudgetSnapshot) -> tuple[Any, ...]:
        return (
            self._summary_entry_id,
            tuple(message.id for message in self._history),
            snapshot.context_window,
            snapshot.output_reserve,
            snapshot.reserve_tokens,
            snapshot.input_tokens,
            snapshot.input_budget,
        )


__all__ = ["SessionCompactionBudgetMixin"]
