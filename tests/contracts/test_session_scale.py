"""Session production files obey the repository size limits."""

from pathlib import Path

import pytest

from scripts.scale_scan import scan_app


SESSION_ROOT = Path(__file__).resolve().parents[2] / "src" / "codeagent" / "session"


@pytest.mark.contract
def test_session_production_modules_stay_within_size_budget() -> None:
    violations = scan_app(SESSION_ROOT)
    assert not violations, "session 规模超限:\n" + "\n".join(
        violation.format() for violation in violations
    )
