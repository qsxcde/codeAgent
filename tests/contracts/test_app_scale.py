"""应用层生产文件与函数规模护栏。"""

from __future__ import annotations

import pytest

from scripts.scale_scan import COMPATIBILITY_EXCEPTIONS, scan_app


@pytest.mark.contract
def test_app_production_modules_stay_within_size_budget() -> None:
    violations = scan_app()
    assert not violations, "应用层规模超限:\n" + "\n".join(v.format() for v in violations)


@pytest.mark.contract
def test_compatibility_exceptions_have_explicit_reasons() -> None:
    for relative, reason in COMPATIBILITY_EXCEPTIONS.items():
        assert relative.endswith(".py")
        assert reason.strip(), f"兼容外观 {relative} 缺少例外理由"
