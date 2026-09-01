"""Extract bounded, structured facts from a completed child session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from codeagent.core.contracts.messages import ToolOutputMetadata
from codeagent.core.contracts.subagent_results import (
    MAX_SUBAGENT_ARTIFACT_REF_CHARS,
    MAX_SUBAGENT_ARTIFACT_LABEL_CHARS,
    MAX_SUBAGENT_CONTINUATION_CHARS,
    MAX_SUBAGENT_EVIDENCE,
    MAX_SUBAGENT_EVIDENCE_EXCERPT_CHARS,
    MAX_SUBAGENT_EVIDENCE_ID_CHARS,
    MAX_SUBAGENT_EVIDENCE_LOCATOR_CHARS,
    MAX_SUBAGENT_EVIDENCE_SOURCE_CHARS,
    MAX_SUBAGENT_EVIDENCE_SUMMARY_CHARS,
)
from codeagent.core.contracts.subagents import (
    SubagentArtifact,
    SubagentEvidence,
    SubagentFinding,
    SubagentUsage,
)


@dataclass(frozen=True)
class ChildResultFacts:
    """Structured facts extracted without retaining child runtime objects."""

    findings: tuple[SubagentFinding, ...] = ()
    evidence: tuple[SubagentEvidence, ...] = ()
    usage: SubagentUsage | None = None
    artifact: SubagentArtifact | None = None


def extract_child_facts(session: Any) -> ChildResultFacts:
    """Extract tool observations and usage from one completed child session."""
    history = getattr(session, "history", ())
    tool_names: dict[str, str] = {}
    evidence: list[SubagentEvidence] = []
    artifact: SubagentArtifact | None = None

    for message in history or ():
        if getattr(message, "role", None) == "assistant":
            _remember_tool_names(tool_names, message)
            continue
        if len(evidence) >= MAX_SUBAGENT_EVIDENCE:
            break
        if getattr(message, "role", None) != "tool":
            continue
        metadata = _metadata_of(message)
        if metadata is None:
            continue
        tool_call_id = str(getattr(message, "tool_call_id", None) or "unknown")
        tool_name = tool_names.get(tool_call_id, "unknown")
        source = _clip(f"tool:{tool_name}", MAX_SUBAGENT_EVIDENCE_SOURCE_CHARS)
        content = str(getattr(message, "content", "") or "")
        evidence_id = _clip(
            f"evidence-{len(evidence) + 1}",
            MAX_SUBAGENT_EVIDENCE_ID_CHARS,
        )
        evidence.append(
            SubagentEvidence(
                evidence_id=evidence_id,
                source=source,
                summary=_evidence_summary(content, source, metadata),
                locator=_locator(metadata),
                excerpt=_clip(content, MAX_SUBAGENT_EVIDENCE_EXCERPT_CHARS) or None,
                completeness=metadata.completeness,
                continuation=(
                    _clip(metadata.continuation, MAX_SUBAGENT_CONTINUATION_CHARS)
                    or None
                ),
            )
        )
        if artifact is None:
            artifact = _artifact(metadata, source)

    return ChildResultFacts(
        evidence=tuple(evidence),
        usage=child_usage(session),
        artifact=artifact,
    )


def child_usage(session: Any) -> SubagentUsage | None:
    """Read the widest available run-total usage view from a session double."""
    runtime = getattr(session, "_runtime", None)
    candidates = (
        getattr(session, "run_usage", None),
        getattr(runtime, "turn_usage", None),
        getattr(session, "last_actual_usage", None),
        getattr(session, "usage", None),
        getattr(session, "committed_usage", None),
    )
    for candidate in candidates:
        usage = _usage_of(candidate)
        if usage is not None:
            return usage
    return None


def _remember_tool_names(names: dict[str, str], message: Any) -> None:
    for call in getattr(message, "tool_calls", ()) or ():
        call_id = getattr(call, "id", None)
        if call_id:
            names[str(call_id)] = str(getattr(call, "name", None) or "unknown")


def _metadata_of(message: Any) -> ToolOutputMetadata | None:
    metadata = getattr(message, "tool_output", None)
    if isinstance(metadata, ToolOutputMetadata):
        return metadata
    if isinstance(metadata, dict):
        return ToolOutputMetadata.from_dict(metadata)
    return None


def _evidence_summary(
    content: str,
    source: str,
    metadata: ToolOutputMetadata,
) -> str:
    if metadata.change_summary:
        return _clip(metadata.change_summary, MAX_SUBAGENT_EVIDENCE_SUMMARY_CHARS)
    for line in content.splitlines():
        if line.strip():
            return _clip(line.strip(), MAX_SUBAGENT_EVIDENCE_SUMMARY_CHARS)
    return _clip(
        f"{source} 输出 ({metadata.completeness})",
        MAX_SUBAGENT_EVIDENCE_SUMMARY_CHARS,
    )


def _locator(metadata: ToolOutputMetadata) -> str | None:
    if metadata.path:
        if metadata.range_start is not None and metadata.range_end is not None:
            value = f"{metadata.path}:{metadata.range_start + 1}-{metadata.range_end}"
        else:
            value = metadata.path
        return _clip(value, MAX_SUBAGENT_EVIDENCE_LOCATOR_CHARS)
    reference = metadata.artifact_ref or metadata.artifact_path
    return (
        _clip(reference, MAX_SUBAGENT_EVIDENCE_LOCATOR_CHARS)
        if reference
        else None
    )


def _artifact(
    metadata: ToolOutputMetadata,
    source: str,
) -> SubagentArtifact | None:
    reference = metadata.artifact_ref or metadata.artifact_path
    if not reference:
        return None
    return SubagentArtifact(
        ref=_clip(reference, MAX_SUBAGENT_ARTIFACT_REF_CHARS),
        kind="tool_output",
        label=_clip(source, MAX_SUBAGENT_ARTIFACT_LABEL_CHARS),
    )


def _usage_of(value: Any) -> SubagentUsage | None:
    if value is None:
        return None
    fields = {}
    for name in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens"):
        raw = value.get(name) if isinstance(value, dict) else getattr(value, name, None)
        if raw is None:
            raw = 0
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            return None
        fields[name] = raw
    if not any(fields.values()):
        return None
    return SubagentUsage(**fields)


def _clip(value: Any, limit: int) -> str:
    if value is None:
        return ""
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


__all__ = ["ChildResultFacts", "child_usage", "extract_child_facts"]
