"""Runtime-only aggregation of context budget and governance observations."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from codeagent.core.context.budget import ContextBudgetSnapshot
from codeagent.core.context.diagnostics import ContextDiagnostics
from codeagent.core.context.preflight import ContextPreflightResult
from codeagent.session.persistence.models import UsageStats


@dataclass
class SessionBudgetState:
    """Runtime-only budget, usage, and context diagnostics for one session."""

    latest_estimate: ContextBudgetSnapshot | None = None
    latest_preflight: ContextPreflightResult | None = None
    latest_actual_usage: UsageStats | None = None
    diagnostics: ContextDiagnostics = field(default_factory=ContextDiagnostics.empty)

    def reset_request(self) -> None:
        """Clear request-local observations before a new session run."""
        self.latest_estimate = None
        self.latest_preflight = None
        self.latest_actual_usage = None
        previous = self.diagnostics
        self.diagnostics = ContextDiagnostics(
            model_id=previous.model_id,
            compaction=previous.compaction,
            tool_results=previous.tool_results,
        )

    def reset_for_model(self, model_id: str | None) -> None:
        """Drop budget facts that belong to a previous model configuration."""
        self.latest_estimate = None
        self.latest_preflight = None
        self.latest_actual_usage = None
        previous = self.diagnostics
        self.diagnostics = ContextDiagnostics(
            model_id=model_id,
            compaction=previous.compaction,
            tool_results=previous.tool_results,
        )

    def record_estimate(
        self,
        snapshot: ContextBudgetSnapshot,
        *,
        model_id: str | None = None,
    ) -> None:
        self.latest_estimate = snapshot
        current = ContextDiagnostics.from_budget(snapshot, model_id=model_id)
        self.diagnostics = replace(
            current,
            compaction=self.diagnostics.compaction,
            tool_results=self.diagnostics.tool_results,
        )

    def record_preflight(self, result: ContextPreflightResult) -> None:
        self.latest_preflight = result
        self.diagnostics = self.diagnostics.with_preflight(result)

    def record_actual_usage(self, payload: dict[str, Any]) -> None:
        self.latest_actual_usage = UsageStats(
            input_tokens=int(payload.get("input_tokens", 0) or 0),
            output_tokens=int(payload.get("output_tokens", 0) or 0),
            reasoning_tokens=int(payload.get("reasoning_tokens", 0) or 0),
            cached_tokens=int(payload.get("cached_tokens", 0) or 0),
        )
        self.diagnostics = self.diagnostics.with_actual_usage(
            input_tokens=self.latest_actual_usage.input_tokens,
            output_tokens=(
                self.latest_actual_usage.output_tokens
                + self.latest_actual_usage.reasoning_tokens
            ),
            cached_tokens=self.latest_actual_usage.cached_tokens,
        )

    def record_compaction(self, metadata: dict[str, Any]) -> None:
        """Merge structured compaction metadata into the latest snapshot."""
        self.diagnostics = self.diagnostics.with_compaction(
            trigger=str(metadata.get("trigger") or "unknown"),
            status=str(metadata.get("status") or "unknown"),
            reason_code=_optional_text(
                metadata.get("reason_code") or metadata.get("error_code")
            ),
            reason=_optional_text(metadata.get("reason") or metadata.get("error_message")),
            before_input_tokens=_optional_int(
                metadata.get("before_input_tokens", metadata.get("input_tokens"))
            ),
            after_input_tokens=_optional_int(metadata.get("after_input_tokens")),
            target_tokens=_optional_int(
                metadata.get("target_budget", metadata.get("target_tokens"))
            ),
            summarized_entry_ids=_entry_ids(metadata.get("summarized_entry_ids")),
            kept_entry_ids=_entry_ids(metadata.get("kept_entry_ids")),
        )

    def record_tool_result(self, metadata: dict[str, Any]) -> None:
        """Merge bounded tool-result governance metadata."""
        output = metadata.get("output_metadata")
        fields = output if isinstance(output, dict) else metadata
        completeness = str(fields.get("completeness") or "")
        facts_complete = (
            True
            if completeness == "complete"
            else False
            if completeness in {"truncated", "incomplete", "unsupported"}
            or fields.get("truncated_by")
            else None
        )
        self.diagnostics = self.diagnostics.with_tool_result(
            tool_call_id=_optional_text(
                metadata.get("tool_call_id") or fields.get("tool_call_id")
            ),
            status=str(metadata.get("status") or "unknown"),
            original_bytes=_optional_int(
                fields.get("total_bytes", fields.get("original_bytes"))
            ),
            shown_bytes=_optional_int(fields.get("shown_bytes")),
            action=str(fields.get("truncated_by") or fields.get("action") or "none"),
            reason=_optional_text(fields.get("truncated_by") or fields.get("reason")),
            facts_complete=facts_complete,
        )

    def record_failure(self, metadata: dict[str, Any]) -> None:
        """Record a failed request without treating it as committed usage."""
        code = _optional_text(metadata.get("error_code")) or "runtime_error"
        message = _optional_text(
            metadata.get("error_message") or metadata.get("error")
        ) or "发生错误"
        phase = _optional_text(metadata.get("phase")) or "unknown"
        self.diagnostics = self.diagnostics.with_failure(
            code=code,
            message=message,
            phase=phase,
        )


def _optional_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    return None if value is None or not str(value) else str(value)


def _entry_ids(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if item is not None and str(item))


__all__ = ["SessionBudgetState"]
