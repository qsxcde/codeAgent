"""扫描应用层生产文件和函数规模。"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_LINES = 300
MAX_FUNCTION_LINES = 80
DEFAULT_APP_ROOT = Path(__file__).resolve().parents[1] / "src" / "codeagent" / "app"

# 迁移收口后不允许兼容外观；若未来出现例外，必须逐项登记原因。
COMPATIBILITY_EXCEPTIONS: dict[str, str] = {}


@dataclass(frozen=True)
class ScaleViolation:
    path: Path
    kind: str
    actual: int
    limit: int
    symbol: str | None = None

    def format(self) -> str:
        location = f"::{self.symbol}" if self.symbol else ""
        return f"{self.path}{location}: {self.kind} {self.actual} > {self.limit}"


def _function_violations(path: Path) -> list[ScaleViolation]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[ScaleViolation] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end_lineno = getattr(node, "end_lineno", node.lineno)
        actual = end_lineno - node.lineno + 1
        if actual > MAX_FUNCTION_LINES:
            violations.append(
                ScaleViolation(path, "函数行数", actual, MAX_FUNCTION_LINES, node.name)
            )
    return violations


def scan_app(app_root: Path = DEFAULT_APP_ROOT) -> list[ScaleViolation]:
    """返回应用层生产文件及函数的规模超限项。"""
    violations: list[ScaleViolation] = []
    for path in sorted(app_root.rglob("*.py")):
        relative = path.relative_to(app_root).as_posix()
        if relative in COMPATIBILITY_EXCEPTIONS:
            continue
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > MAX_FILE_LINES:
            violations.append(ScaleViolation(path, "文件行数", line_count, MAX_FILE_LINES))
        violations.extend(_function_violations(path))
    return violations


def main() -> int:
    violations = scan_app()
    if violations:
        print("\n".join(violation.format() for violation in violations))
        return 1
    print("应用层规模检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
