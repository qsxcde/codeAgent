"""core 生产文件与函数规模护栏。"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.scale_scan import scan_app


CORE_ROOT = Path(__file__).resolve().parents[2] / "src" / "codeagent" / "core"


@pytest.mark.contract
def test_core_production_modules_stay_within_size_budget() -> None:
    violations = scan_app(CORE_ROOT)
    assert not violations, "core 规模超限:\n" + "\n".join(
        violation.format() for violation in violations
    )
