"""Provider-independent context diagnostics and immutable view helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from codeagent.core.context.budget import ContextBudgetSnapshot
from codeagent.core.context.diagnostic_models import (
    CompactionDiagnostic,
    ToolResultDiagnostic,
    WindowCertainty,
)
from codeagent.core.context.preflight import ContextPreflightResult

@dataclass(frozen=True)
class ContextDiagnostics:
    """Read-only, cross-layer snapshot for context budget observability."""

    model_id: str | None = None
    context_window: int | None = None
    window_source: str = "unknown"
    window_certainty: WindowCertainty = "unknown"
    budget_status: str | None = None
    input_budget: int | None = None
    input_tokens: int | None = None
    headroom: int | None = None
    system_prompt_tokens: int | None = None
    tool_definitions_tokens: int | None = None
    conversation_tokens: int | None = None
    tool_result_tokens: int | None = None
    output_reserve: int | None = None
    reserve_tokens: int | None = None
    preflight_status: str | None = None
    preflight_allowed: bool | None = None
    preflight_reason: str | None = None
    warning_boundary: int | None = None
    actual_input_tokens: int | None = None
    actual_output_tokens: int | None = None
    actual_cached_tokens: int | None = None
    compaction: CompactionDiagnostic | None = None
    tool_results: tuple[ToolResultDiagnostic, ...] = ()
    last_failure: dict[str, str] | None = None

    @classmethod
    def empty(cls) -> "ContextDiagnostics":
        """Return an explicit empty state for sessions without observations."""
        return cls()

    @classmethod
    def from_budget(
        cls,
        snapshot: ContextBudgetSnapshot,
        *,
        model_id: str | None = None,
    ) -> "ContextDiagnostics":
        """Create a diagnostic view using exactly one budget snapshot."""
        certainty: WindowCertainty
        if snapshot.status == "uncertain":
            certainty = "uncertain"
        elif snapshot.window_source in {"fallback", "unknown", "compaction"}:
            certainty = (
                "fallback" if snapshot.window_source == "fallback" else "uncertain"
            )
        else:
            certainty = "known"
        return cls(
            model_id=model_id,
            context_window=snapshot.context_window,
            window_source=snapshot.window_source,
            window_certainty=certainty,
            budget_status=snapshot.status,
            input_budget=snapshot.input_budget,
            input_tokens=snapshot.input_tokens,
            headroom=snapshot.headroom,
            system_prompt_tokens=snapshot.system_prompt_tokens,
            tool_definitions_tokens=snapshot.tool_definitions_tokens,
            conversation_tokens=snapshot.conversation_tokens,
            tool_result_tokens=snapshot.tool_result_tokens,
            output_reserve=snapshot.output_reserve,
            reserve_tokens=snapshot.reserve_tokens,
        )

    @property
    def components(self) -> dict[str, int]:
        """Return known token components with stable presentation names."""
        values = {
            "system_prompt": self.system_prompt_tokens,
            "tool_definitions": self.tool_definitions_tokens,
            "conversation": self.conversation_tokens,
            "tool_results": self.tool_result_tokens,
            "output_reserve": self.output_reserve,
            "reserve": self.reserve_tokens,
        }
        return {name: value for name, value in values.items() if value is not None}

    @property
    def usage_percent(self) -> float | None:
        """Return a percentage only when the window is known precisely."""
        if (
            self.window_certainty != "known"
            or self.context_window is None
            or self.context_window <= 0
            or self.input_tokens is None
        ):
            return None
        return max(0.0, min(100.0, self.input_tokens / self.context_window * 100))

    def with_preflight(self, result: ContextPreflightResult) -> "ContextDiagnostics":
        """Attach the latest preflight while keeping other observations."""
        base = self._replace_budget(result.snapshot)
        return replace(
            base,
            preflight_status=result.status,
            preflight_allowed=result.allowed,
            preflight_reason=result.reason,
            warning_boundary=result.warning_boundary,
        )

    def with_actual_usage(
        self,
        *,
        input_tokens: int,
        output_tokens: int = 0,
        cached_tokens: int = 0,
    ) -> "ContextDiagnostics":
        """Attach provider usage without replacing the request estimate."""
        return replace(
            self,
            actual_input_tokens=input_tokens,
            actual_output_tokens=output_tokens,
            actual_cached_tokens=cached_tokens,
        )

    def with_compaction(
        self,
        *,
        trigger: str,
        status: str,
        reason_code: str | None = None,
        reason: str | None = None,
        before_input_tokens: int | None = None,
        after_input_tokens: int | None = None,
        target_tokens: int | None = None,
        summarized_entry_ids: tuple[str, ...] = (),
        kept_entry_ids: tuple[str, ...] = (),
    ) -> "ContextDiagnostics":
        """Attach bounded compaction metadata without message contents."""
        return replace(
            self,
            compaction=CompactionDiagnostic(
                trigger=trigger,
                status=status,
                reason_code=reason_code,
                reason=reason,
                before_input_tokens=before_input_tokens,
                after_input_tokens=after_input_tokens,
                target_tokens=target_tokens,
                summarized_entry_ids=tuple(summarized_entry_ids),
                kept_entry_ids=tuple(kept_entry_ids),
            ),
        )

    def with_tool_result(
        self,
        *,
        tool_call_id: str | None,
        status: str,
        original_bytes: int | None,
        shown_bytes: int | None,
        action: str,
        reason: str | None,
        facts_complete: bool | None,
    ) -> "ContextDiagnostics":
        """Append one tool result and bound the runtime-only collection."""
        item = ToolResultDiagnostic(
            tool_call_id=tool_call_id,
            status=status,
            original_bytes=original_bytes,
            shown_bytes=shown_bytes,
            action=action,
            reason=reason,
            facts_complete=facts_complete,
        )
        return replace(self, tool_results=(*self.tool_results, item)[-8:])

    def with_failure(
        self,
        *,
        code: str,
        message: str,
        phase: str,
    ) -> "ContextDiagnostics":
        """Attach a local failure without implying committed provider usage."""
        return replace(
            self,
            last_failure={"code": code, "message": message, "phase": phase},
            actual_input_tokens=None,
            actual_output_tokens=None,
            actual_cached_tokens=None,
        )

    def _replace_budget(self, snapshot: ContextBudgetSnapshot) -> "ContextDiagnostics":
        current = ContextDiagnostics.from_budget(snapshot, model_id=self.model_id)
        return replace(
            current,
            actual_input_tokens=self.actual_input_tokens,
            actual_output_tokens=self.actual_output_tokens,
            actual_cached_tokens=self.actual_cached_tokens,
            compaction=self.compaction,
            tool_results=self.tool_results,
            last_failure=self.last_failure,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a detached, stable representation for CLI/TUI renderers."""
        window: Any = "unknown"
        if self.context_window is not None:
            window = {
                "value": self.context_window,
                "source": self.window_source,
                "certainty": self.window_certainty,
            }
        budget: Any = "unknown"
        if self.input_budget is not None:
            budget = {
                "input_budget": self.input_budget,
                "input_tokens": self.input_tokens,
                "headroom": self.headroom,
                "status": self.budget_status,
            }
        preflight: Any = "not_available"
        if self.preflight_status is not None:
            preflight = {
                "status": self.preflight_status,
                "allowed": self.preflight_allowed,
                "reason": self.preflight_reason,
                "warning_boundary": self.warning_boundary,
            }
        return {
            "model": self.model_id or "unknown",
            "window": window,
            "budget": budget,
            "components": self.components,
            "input_tokens": self.input_tokens,
            "headroom": self.headroom,
            "usage_percent": self.usage_percent,
            "actual_usage": self._actual_usage_dict(),
            "preflight": preflight,
            "compaction": (
                self.compaction.as_dict()
                if self.compaction is not None
                else "not_available"
            ),
            "tool_results": [item.as_dict() for item in self.tool_results],
            "last_failure": dict(self.last_failure) if self.last_failure else None,
        }

    def _actual_usage_dict(self) -> dict[str, int] | str:
        if self.actual_input_tokens is None:
            return "not_available"
        return {
            "input_tokens": self.actual_input_tokens,
            "output_tokens": self.actual_output_tokens or 0,
            "cached_tokens": self.actual_cached_tokens or 0,
        }


__all__ = [
    "CompactionDiagnostic",
    "ContextDiagnostics",
    "ToolResultDiagnostic",
    "WindowCertainty",
]
