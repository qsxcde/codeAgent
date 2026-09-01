"""Terminal result contract for a delegated Subagent run."""

from __future__ import annotations

from dataclasses import dataclass

from codeagent.core.contracts.errors import SubagentContractError

from .subagent_lifecycle import SubagentFailure, SubagentStatus
from .subagent_results import (
    MAX_SUBAGENT_EVIDENCE,
    MAX_SUBAGENT_FINDINGS,
    MAX_SUBAGENT_SUMMARY_CHARS,
    SubagentArtifact,
    SubagentEvidence,
    SubagentFinding,
    SubagentUsage,
)

__all__ = ["SubagentResult"]


@dataclass(frozen=True)
class SubagentResult:
    """Immutable terminal result returned to the parent run."""

    delegation_id: str
    status: SubagentStatus
    child_run_id: str | None = None
    attempt_id: str | None = None
    summary: str = ""
    failure: SubagentFailure | None = None
    diagnostics: tuple[str, ...] = ()
    cleanup_uncertain: bool = False
    findings: tuple[SubagentFinding, ...] = ()
    evidence: tuple[SubagentEvidence, ...] = ()
    usage: SubagentUsage | None = None
    artifact: SubagentArtifact | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.delegation_id, str) or not self.delegation_id.strip():
            raise SubagentContractError(
                "delegation_id must be a non-empty string", code="invalid_result"
            )
        try:
            status = SubagentStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise SubagentContractError(
                f"unknown Subagent status: {self.status!r}", code="invalid_result"
            ) from exc
        object.__setattr__(self, "status", status)
        if not status.is_terminal:
            raise SubagentContractError(
                "SubagentResult status must be terminal", code="invalid_result"
            )
        if status is SubagentStatus.COMPLETED and self.failure is not None:
            raise SubagentContractError(
                "completed SubagentResult cannot contain a failure", code="invalid_result"
            )
        if status is not SubagentStatus.COMPLETED and self.failure is None:
            raise SubagentContractError(
                "non-completed SubagentResult requires a failure", code="invalid_result"
            )
        for name in ("child_run_id", "attempt_id"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise SubagentContractError(
                    f"{name} must be a non-empty string", code="invalid_result"
                )
        if not isinstance(self.summary, str):
            raise SubagentContractError("summary must be a string", code="invalid_result")
        if len(self.summary) > MAX_SUBAGENT_SUMMARY_CHARS:
            raise SubagentContractError(
                f"summary exceeds {MAX_SUBAGENT_SUMMARY_CHARS} characters",
                code="invalid_result",
            )
        diagnostics = (
            self.diagnostics
            if isinstance(self.diagnostics, tuple)
            else tuple(self.diagnostics)
        )
        if not all(isinstance(item, str) for item in diagnostics):
            raise SubagentContractError(
                "diagnostics must contain strings",
                code="invalid_result",
            )
        if not isinstance(self.cleanup_uncertain, bool):
            raise SubagentContractError(
                "cleanup_uncertain must be a bool", code="invalid_result"
            )
        findings = _result_tuple(
            self.findings, "findings", SubagentFinding, MAX_SUBAGENT_FINDINGS
        )
        evidence = _result_tuple(
            self.evidence, "evidence", SubagentEvidence, MAX_SUBAGENT_EVIDENCE
        )
        evidence_ids = {item.evidence_id for item in evidence}
        if len(evidence_ids) != len(evidence):
            raise SubagentContractError("evidence ids must be unique", code="invalid_result")
        for finding in findings:
            if not set(finding.evidence_ids).issubset(evidence_ids):
                raise SubagentContractError(
                    "finding references an unknown evidence id",
                    code="invalid_result",
                )
        if self.usage is not None and not isinstance(self.usage, SubagentUsage):
            raise SubagentContractError(
                "usage must be a SubagentUsage or None", code="invalid_result"
            )
        if self.artifact is not None and not isinstance(self.artifact, SubagentArtifact):
            raise SubagentContractError(
                "artifact must be a SubagentArtifact or None",
                code="invalid_result",
            )
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "evidence", evidence)

    def to_dict(self) -> dict[str, object]:
        """Return a detached JSON-safe representation of the terminal result."""
        return {
            "delegation_id": self.delegation_id,
            "status": self.status.value,
            "child_run_id": self.child_run_id,
            "attempt_id": self.attempt_id,
            "summary": self.summary,
            "failure": self.failure.as_metadata() if self.failure is not None else None,
            "diagnostics": list(self.diagnostics),
            "cleanup_uncertain": self.cleanup_uncertain,
            "findings": [item.to_dict() for item in self.findings],
            "evidence": [item.to_dict() for item in self.evidence],
            "usage": self.usage.to_dict() if self.usage is not None else None,
            "artifact": self.artifact.to_dict() if self.artifact is not None else None,
        }


def _result_tuple(
    value: object,
    name: str,
    item_type: type[object],
    max_items: int | None,
) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise SubagentContractError(f"{name} must be a list or tuple", code="invalid_result")
    if max_items is not None and len(value) > max_items:
        raise SubagentContractError(
            f"{name} exceeds {max_items} items",
            code="invalid_result",
        )
    if not all(isinstance(item, item_type) for item in value):
        raise SubagentContractError(
            f"{name} must contain {item_type.__name__} values",
            code="invalid_result",
        )
    return tuple(value)
