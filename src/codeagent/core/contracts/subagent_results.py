"""Bounded, provider-neutral values returned by delegated Subagents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from codeagent.core.contracts.errors import SubagentContractError
from codeagent.core.contracts.output import OutputCompleteness

MAX_SUBAGENT_FINDINGS = 16
MAX_SUBAGENT_EVIDENCE = 32
MAX_SUBAGENT_SUMMARY_CHARS = 16_000
MAX_SUBAGENT_FINDING_CHARS = 2_000
MAX_SUBAGENT_EVIDENCE_ID_CHARS = 128
MAX_SUBAGENT_EVIDENCE_SOURCE_CHARS = 512
MAX_SUBAGENT_EVIDENCE_LOCATOR_CHARS = 512
MAX_SUBAGENT_EVIDENCE_SUMMARY_CHARS = 2_000
MAX_SUBAGENT_EVIDENCE_EXCERPT_CHARS = 1_200
MAX_SUBAGENT_CONTINUATION_CHARS = 512
MAX_SUBAGENT_ARTIFACT_REF_CHARS = 512
MAX_SUBAGENT_ARTIFACT_KIND_CHARS = 128
MAX_SUBAGENT_ARTIFACT_LABEL_CHARS = 200

__all__ = [
    "MAX_SUBAGENT_ARTIFACT_KIND_CHARS",
    "MAX_SUBAGENT_ARTIFACT_LABEL_CHARS",
    "MAX_SUBAGENT_ARTIFACT_REF_CHARS",
    "MAX_SUBAGENT_CONTINUATION_CHARS",
    "MAX_SUBAGENT_EVIDENCE",
    "MAX_SUBAGENT_EVIDENCE_EXCERPT_CHARS",
    "MAX_SUBAGENT_EVIDENCE_ID_CHARS",
    "MAX_SUBAGENT_EVIDENCE_LOCATOR_CHARS",
    "MAX_SUBAGENT_EVIDENCE_SOURCE_CHARS",
    "MAX_SUBAGENT_EVIDENCE_SUMMARY_CHARS",
    "MAX_SUBAGENT_FINDING_CHARS",
    "MAX_SUBAGENT_FINDINGS",
    "MAX_SUBAGENT_SUMMARY_CHARS",
    "SubagentArtifact",
    "SubagentEvidence",
    "SubagentFinding",
    "SubagentUsage",
]


@dataclass(frozen=True)
class SubagentFinding:
    """One explicit conclusion and the evidence ids that support it."""

    summary: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _bounded_text(self.summary, "finding summary", MAX_SUBAGENT_FINDING_CHARS)
        evidence_ids = _text_tuple(
            self.evidence_ids,
            "finding evidence_ids",
            MAX_SUBAGENT_EVIDENCE,
            MAX_SUBAGENT_EVIDENCE_ID_CHARS,
        )
        object.__setattr__(self, "evidence_ids", evidence_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class SubagentEvidence:
    """A bounded observation derived from an actual child tool result."""

    evidence_id: str
    source: str
    summary: str
    locator: str | None = None
    excerpt: str | None = None
    completeness: str = OutputCompleteness.UNKNOWN
    continuation: str | None = None

    def __post_init__(self) -> None:
        _bounded_text(
            self.evidence_id,
            "evidence_id",
            MAX_SUBAGENT_EVIDENCE_ID_CHARS,
        )
        _bounded_text(
            self.source,
            "evidence source",
            MAX_SUBAGENT_EVIDENCE_SOURCE_CHARS,
        )
        _bounded_text(
            self.summary,
            "evidence summary",
            MAX_SUBAGENT_EVIDENCE_SUMMARY_CHARS,
        )
        _optional_bounded_text(
            self.locator,
            "evidence locator",
            MAX_SUBAGENT_EVIDENCE_LOCATOR_CHARS,
        )
        _optional_bounded_text(
            self.excerpt,
            "evidence excerpt",
            MAX_SUBAGENT_EVIDENCE_EXCERPT_CHARS,
        )
        if self.completeness not in OutputCompleteness.ALL:
            raise _invalid(f"unsupported evidence completeness: {self.completeness!r}")
        _optional_bounded_text(
            self.continuation,
            "evidence continuation",
            MAX_SUBAGENT_CONTINUATION_CHARS,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source": self.source,
            "summary": self.summary,
            "locator": self.locator,
            "excerpt": self.excerpt,
            "completeness": self.completeness,
            "continuation": self.continuation,
        }


@dataclass(frozen=True)
class SubagentUsage:
    """Normalized token usage for one child run."""

    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0

    def __post_init__(self) -> None:
        for name in (
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cached_tokens",
        ):
            _nonnegative_int(getattr(self, name), name)

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_tokens": self.cached_tokens,
        }


@dataclass(frozen=True)
class SubagentArtifact:
    """A reference to an externally produced artifact, without its contents."""

    ref: str
    kind: str = "unknown"
    label: str = ""

    def __post_init__(self) -> None:
        _bounded_text(self.ref, "artifact ref", MAX_SUBAGENT_ARTIFACT_REF_CHARS)
        _bounded_text(self.kind, "artifact kind", MAX_SUBAGENT_ARTIFACT_KIND_CHARS)
        if not isinstance(self.label, str):
            raise _invalid("artifact label must be a string")
        if len(self.label) > MAX_SUBAGENT_ARTIFACT_LABEL_CHARS:
            raise _invalid(
                f"artifact label exceeds {MAX_SUBAGENT_ARTIFACT_LABEL_CHARS} characters"
            )

    def to_dict(self) -> dict[str, str]:
        return {"ref": self.ref, "kind": self.kind, "label": self.label}


def _bounded_text(value: object, name: str, limit: int) -> None:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{name} must be a non-empty string")
    if len(value) > limit:
        raise _invalid(f"{name} exceeds {limit} characters")


def _optional_bounded_text(
    value: object,
    name: str,
    limit: int,
    *,
    allow_empty: bool = False,
) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise _invalid(f"{name} must be a string or None")
    if not allow_empty and not value.strip():
        raise _invalid(f"{name} must be non-empty when provided")
    if len(value) > limit:
        raise _invalid(f"{name} exceeds {limit} characters")


def _text_tuple(
    value: object,
    name: str,
    max_items: int,
    item_limit: int,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise _invalid(f"{name} must be a list or tuple")
    if len(value) > max_items:
        raise _invalid(f"{name} exceeds {max_items} items")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise _invalid(f"{name} must contain non-empty strings")
        if len(item) > item_limit:
            raise _invalid(f"{name} item exceeds {item_limit} characters")
        result.append(item)
    return tuple(result)


def _nonnegative_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid(f"{name} must be a non-negative integer")


def _invalid(message: str) -> SubagentContractError:
    return SubagentContractError(message, code="invalid_result")
