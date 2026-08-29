from __future__ import annotations

from codeagent.ai.errors import ProviderError
from codeagent.session.runtime.error_policy import classify_error
from codeagent.session.runtime.state import RunPhase


def test_session_preserves_non_retryable_provider_classification() -> None:
    failure = classify_error(
        ProviderError(
            kind="invalid_request",
            retryable=False,
            detail="unsupported request field",
            provider="test-provider",
            model="test-model",
        ),
        phase=RunPhase.MODEL_WAIT,
    )

    assert failure.code == "model_invalid_request"
    assert failure.retryable is False
    assert "unsupported request field" in failure.message


def test_session_provider_retryability_still_requires_no_side_effects() -> None:
    error = ProviderError(
        kind="server",
        retryable=True,
        detail="temporarily unavailable",
        provider="test-provider",
        model="test-model",
    )

    safe = classify_error(error, phase=RunPhase.MODEL_WAIT)
    unsafe = classify_error(
        error,
        phase=RunPhase.MODEL_WAIT,
        side_effect_state="possible",
    )

    assert safe.code == "model_server"
    assert safe.retryable is True
    assert unsafe.retryable is False


def test_provider_error_in_tool_phase_is_not_a_model_retry() -> None:
    failure = classify_error(
        ProviderError(
            kind="server",
            retryable=True,
            detail="tool-side provider failure",
        ),
        phase=RunPhase.TOOL_RUNNING,
    )

    assert failure.code == "tool_error"
    assert failure.retryable is False
